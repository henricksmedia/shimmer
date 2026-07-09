// remix.js — Orchestrates the Remix tab: upload, Demucs separation,
// per-stem channel strips (mute/solo/gain + effects rack), a looped
// A/B mini-player, and full-length render/download.

import { uploadFile, dropSession, openSSE, resultUrl } from './api.js';
import { fmtTime } from './visualizer.js';

const RENDER_DEBOUNCE_MS = 300;

const STRIPS = [
    { key: 'vocals', label: 'Vocals', color: '#6c5ce7' },
    { key: 'drums',  label: 'Drums',  color: '#d4a55a' },
    { key: 'bass',   label: 'Bass',   color: '#3fbf7f' },
    { key: 'other',  label: 'Other',  color: '#5aa7d4' },
];

// Per-effect UI spec: key, label, params [{key, label, min, max, step, def}]
const EFFECTS = [
    { key: 'formant', label: 'Voice shape', params: [
        { key: 'ratio', label: 'Deeper ↔ Thinner', min: 0.7, max: 1.4,
          step: 0.01, def: 0.88 },
    ]},
    { key: 'saturation', label: 'Grit', params: [
        { key: 'drive_db', label: 'Drive', min: 0, max: 24, step: 0.5, def: 8 },
    ]},
    { key: 'doubler', label: 'Doubler', params: [
        { key: 'mix', label: 'Amount', min: 0, max: 1, step: 0.05, def: 0.45 },
        { key: 'detune_cents', label: 'Detune', min: 2, max: 40, step: 1, def: 12 },
    ]},
    { key: 'reverb', label: 'Space', params: [
        { key: 'mix', label: 'Amount', min: 0, max: 1, step: 0.05, def: 0.25 },
        { key: 'size', label: 'Size', min: 0, max: 1, step: 0.05, def: 0.5 },
    ]},
];


async function renderRemixPreview(payload) {
    const res = await fetch('/api/remix/preview', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error(await res.text() || `Preview failed (${res.status})`);
    const buf = await res.arrayBuffer();
    const view = new DataView(buf);
    const jsonLen = view.getUint32(0, true);
    const meta = JSON.parse(
        new TextDecoder().decode(new Uint8Array(buf, 4, jsonLen)));
    return { meta, wav: buf.slice(4 + jsonLen) };
}


export async function initRemixTab() {
    const $ = (id) => document.getElementById(id);
    const dropzone = $('remix-dropzone');
    const fileInput = $('remix-file-input');
    const pickBtn = $('remix-pick-btn');
    const selectedFile = $('remix-selected-file');
    const sepBtn = $('remix-separate-btn');
    const sepStatus = $('remix-sep-status');
    const sepProgress = $('remix-sep-progress');
    const stripsHost = $('remix-strips');
    const renderBlock = $('remix-render-block');
    const renderBtn = $('remix-render-btn');
    const renderProgress = $('remix-render-progress');
    const masterEnabled = $('remix-master-enabled');
    const formatSel = $('remix-format');
    const statusEl = $('remix-status');
    const metricsEl = $('remix-metrics');

    const tabOriginal = $('remix-tab-original');
    const tabRemix = $('remix-tab-remix');
    const windowSel = $('remix-window');
    const loopHereBtn = $('remix-loop-here');
    const playBtn = $('remix-play');
    const timeLabel = $('remix-time');
    const origEl = $('remix-audio-original');
    const remixEl = $('remix-audio-remix');

    const state = {
        file: null,
        sessionId: null,
        digest: null,
        saveTimer: null,
        durationS: 0,
        stemsReady: false,
        loopStart: 0,
        loopEnd: 10,
        active: 'original',
        playing: false,
        remixBlobUrl: null,
        origBlobUrl: null,
        debounce: null,
        inflight: false,
        pending: false,
        strips: {},   // key -> strip state {mute, solo, gain_db, fx:{...}}
    };

    function setStatus(text, kind = '') {
        statusEl.textContent = text;
        statusEl.classList.remove('live', 'error');
        if (kind) statusEl.classList.add(kind);
    }

    // ── Strip state + payload ────────────────────────────────────────
    function resetStrips() {
        for (const s of STRIPS) {
            state.strips[s.key] = {
                mute: false, solo: false, gain_db: 0,
                fx: Object.fromEntries(EFFECTS.map(e => [e.key, {
                    enabled: false,
                    ...Object.fromEntries(e.params.map(p => [p.key, p.def])),
                }])),
            };
        }
    }
    resetStrips();

    // ── Per-track project persistence (disk-side, keyed by file hash) ─
    function saveProject() {
        if (!state.digest) return;
        if (state.saveTimer) clearTimeout(state.saveTimer);
        state.saveTimer = setTimeout(() => {
            state.saveTimer = null;
            fetch(`/api/project/${state.digest}`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    name: state.file ? state.file.name : '',
                    remix: {strips: state.strips},
                }),
            }).catch(() => {});
        }, 800);
    }

    function restoreProject(remix) {
        if (!remix || !remix.strips) return false;
        let restored = false;
        for (const spec of STRIPS) {
            const saved = remix.strips[spec.key];
            if (!saved) continue;
            const st = state.strips[spec.key];
            if (typeof saved.mute === 'boolean') st.mute = saved.mute;
            if (typeof saved.solo === 'boolean') st.solo = saved.solo;
            if (Number.isFinite(saved.gain_db)) st.gain_db = saved.gain_db;
            for (const e of EFFECTS) {
                const sfx = saved.fx && saved.fx[e.key];
                if (!sfx) continue;
                st.fx[e.key].enabled = !!sfx.enabled;
                for (const p of e.params) {
                    if (Number.isFinite(sfx[p.key])) {
                        st.fx[e.key][p.key] = sfx[p.key];
                    }
                }
            }
            restored = true;
        }
        return restored;
    }

    function stemsPayload() {
        const anySolo = STRIPS.some(s => state.strips[s.key].solo);
        const out = {};
        for (const s of STRIPS) {
            const st = state.strips[s.key];
            const effects = {};
            for (const e of EFFECTS) {
                const fx = st.fx[e.key];
                effects[e.key] = { enabled: fx.enabled };
                for (const p of e.params) effects[e.key][p.key] = fx[p.key];
            }
            out[s.key] = {
                gain_db: st.gain_db,
                mute: anySolo ? !st.solo : st.mute,
                effects,
            };
        }
        return out;
    }

    // ── Channel strips UI ────────────────────────────────────────────
    function buildStrips() {
        stripsHost.innerHTML = '';
        for (const spec of STRIPS) {
            const st = state.strips[spec.key];
            const strip = document.createElement('div');
            strip.className = 'remix-strip';
            strip.style.setProperty('--strip-color', spec.color);

            const head = document.createElement('div');
            head.className = 'remix-strip-head';

            const name = document.createElement('span');
            name.className = 'remix-strip-name';
            name.textContent = spec.label;

            const muteBtn = document.createElement('button');
            muteBtn.type = 'button';
            muteBtn.className = 'remix-ms-btn';
            muteBtn.textContent = 'M';
            muteBtn.title = 'Mute this stem';
            const soloBtn = document.createElement('button');
            soloBtn.type = 'button';
            soloBtn.className = 'remix-ms-btn solo';
            soloBtn.textContent = 'S';
            soloBtn.title = 'Solo this stem';

            const refreshMS = () => {
                muteBtn.classList.toggle('on', st.mute);
                soloBtn.classList.toggle('on', st.solo);
            };
            refreshMS();
            muteBtn.addEventListener('click', () => {
                st.mute = !st.mute; refreshMS(); onEdit();
            });
            soloBtn.addEventListener('click', () => {
                st.solo = !st.solo; refreshMS(); onEdit();
            });

            const gainWrap = document.createElement('div');
            gainWrap.className = 'remix-gain-wrap';
            const gain = document.createElement('input');
            gain.type = 'range';
            gain.min = '-24'; gain.max = '12'; gain.step = '0.5';
            gain.value = String(st.gain_db);
            gain.title = 'Stem level (dB)';
            const gainVal = document.createElement('span');
            gainVal.className = 'remix-gain-val';
            const fmtGain = () =>
                `${st.gain_db > 0 ? '+' : ''}${st.gain_db.toFixed(1)} dB`;
            gainVal.textContent = fmtGain();
            gain.addEventListener('input', () => {
                st.gain_db = parseFloat(gain.value);
                gainVal.textContent = fmtGain();
                onEdit();
            });
            gainWrap.append(gain, gainVal);

            head.append(name, muteBtn, soloBtn, gainWrap);
            strip.appendChild(head);

            const fxRow = document.createElement('div');
            fxRow.className = 'remix-fx-row';
            for (const e of EFFECTS) {
                const fx = st.fx[e.key];
                const box = document.createElement('div');
                box.className = 'remix-fx';

                const toggle = document.createElement('label');
                toggle.className = 'remix-fx-toggle';
                const check = document.createElement('input');
                check.type = 'checkbox';
                check.checked = fx.enabled;
                const tname = document.createElement('span');
                tname.textContent = e.label;
                toggle.append(check, tname);
                box.appendChild(toggle);

                const params = document.createElement('div');
                params.className = 'remix-fx-params';
                params.hidden = !fx.enabled;
                box.classList.toggle('on', fx.enabled);
                for (const p of e.params) {
                    const row = document.createElement('label');
                    row.className = 'remix-fx-param';
                    const lbl = document.createElement('span');
                    lbl.textContent = p.label;
                    const range = document.createElement('input');
                    range.type = 'range';
                    range.min = String(p.min);
                    range.max = String(p.max);
                    range.step = String(p.step);
                    range.value = String(fx[p.key]);
                    range.addEventListener('input', () => {
                        fx[p.key] = parseFloat(range.value);
                        onEdit();
                    });
                    row.append(lbl, range);
                    params.appendChild(row);
                }
                check.addEventListener('change', () => {
                    fx.enabled = check.checked;
                    params.hidden = !check.checked;
                    box.classList.toggle('on', check.checked);
                    onEdit();
                });
                box.appendChild(params);
                fxRow.appendChild(box);
            }
            strip.appendChild(fxRow);
            stripsHost.appendChild(strip);
        }
        stripsHost.hidden = false;
    }

    // ── Mini A/B loop player ─────────────────────────────────────────
    function clampLoop() {
        const win = parseFloat(windowSel.value) || 10;
        let start = Math.max(0, Math.min(state.loopStart,
            Math.max(0, state.durationS - win)));
        state.loopStart = start;
        state.loopEnd = Math.min(state.durationS || win, start + win);
    }

    function positionInTrack() {
        if (state.active === 'remix') {
            return state.loopStart + (remixEl.currentTime || 0);
        }
        return origEl.currentTime || 0;
    }

    function updateTime() {
        timeLabel.textContent =
            `${fmtTime(positionInTrack())} / ${fmtTime(state.durationS)}`;
    }

    origEl.addEventListener('timeupdate', () => {
        if (state.active === 'original' && state.playing &&
            origEl.currentTime >= state.loopEnd) {
            origEl.currentTime = state.loopStart;
        }
        updateTime();
    });
    remixEl.addEventListener('timeupdate', updateTime);
    remixEl.loop = true;

    function activeEl() {
        return state.active === 'remix' ? remixEl : origEl;
    }

    async function play() {
        try { await activeEl().play(); state.playing = true; } catch (_) {}
        playBtn.textContent = state.playing ? '⏸' : '▶';
    }
    function pause() {
        origEl.pause(); remixEl.pause();
        state.playing = false;
        playBtn.textContent = '▶';
    }
    playBtn.addEventListener('click', () => {
        if (state.playing) pause();
        else {
            if (state.active === 'original' &&
                (origEl.currentTime < state.loopStart ||
                 origEl.currentTime >= state.loopEnd)) {
                origEl.currentTime = state.loopStart;
            }
            play();
        }
    });

    function setTrack(which) {
        if (which === state.active) return;
        const offset = Math.max(0, Math.min(
            positionInTrack() - state.loopStart,
            state.loopEnd - state.loopStart - 0.05));
        const wasPlaying = state.playing;
        pause();
        state.active = which;
        tabOriginal.classList.toggle('active', which === 'original');
        tabRemix.classList.toggle('active', which === 'remix');
        if (which === 'remix') {
            remixEl.currentTime = offset;
        } else {
            origEl.currentTime = state.loopStart + offset;
        }
        if (wasPlaying) play();
    }
    tabOriginal.addEventListener('click', () => setTrack('original'));
    tabRemix.addEventListener('click', () => {
        if (!tabRemix.disabled) setTrack('remix');
    });

    loopHereBtn.addEventListener('click', () => {
        state.loopStart = positionInTrack();
        clampLoop();
        scheduleRender(0);
    });
    windowSel.addEventListener('change', () => {
        clampLoop();
        scheduleRender(0);
    });

    // ── Preview render loop ──────────────────────────────────────────
    async function doRender() {
        if (!state.stemsReady || !state.sessionId) return;
        if (state.inflight) { state.pending = true; return; }
        state.inflight = true;
        clampLoop();
        setStatus(`Rendering ${fmtTime(state.loopStart)}–${fmtTime(state.loopEnd)}…`);
        try {
            const r = await renderRemixPreview({
                session_id: state.sessionId,
                start_s: state.loopStart,
                end_s: state.loopEnd,
                stems: stemsPayload(),
            });
            const offset = state.active === 'remix'
                ? (remixEl.currentTime || 0) : null;
            const wasPlaying = state.playing && state.active === 'remix';
            if (state.remixBlobUrl) URL.revokeObjectURL(state.remixBlobUrl);
            state.remixBlobUrl = URL.createObjectURL(
                new Blob([r.wav], {type: 'audio/wav'}));
            remixEl.src = state.remixBlobUrl;
            if (offset != null) remixEl.currentTime = offset;
            if (wasPlaying) { try { await remixEl.play(); } catch (_) {} }
            tabRemix.disabled = false;
            renderBlock.hidden = false;
            setStatus(`Live · loop ${fmtTime(state.loopStart)}–${fmtTime(state.loopEnd)} · ${r.meta.render_ms} ms`, 'live');
        } catch (e) {
            setStatus(`Preview failed: ${e.message}`, 'error');
        } finally {
            state.inflight = false;
            if (state.pending) { state.pending = false; doRender(); }
        }
    }

    function scheduleRender(delay = RENDER_DEBOUNCE_MS) {
        if (!state.stemsReady) return;
        if (state.debounce) clearTimeout(state.debounce);
        state.debounce = setTimeout(() => {
            state.debounce = null;
            doRender();
        }, delay);
    }

    // Every user edit re-renders the loop AND persists the project.
    function onEdit() {
        saveProject();
        scheduleRender();
    }

    // ── File adoption + separation ───────────────────────────────────
    function adoptFile(file) {
        state.file = file;
        state.stemsReady = false;
        state.pending = false;
        state.digest = null;
        resetStrips();
        pause();
        tabRemix.disabled = true;
        setTrack('original');
        stripsHost.hidden = true;
        renderBlock.hidden = true;
        metricsEl.hidden = true;
        if (state.sessionId) { dropSession(state.sessionId); state.sessionId = null; }
        if (state.origBlobUrl) URL.revokeObjectURL(state.origBlobUrl);
        state.origBlobUrl = URL.createObjectURL(file);
        origEl.src = state.origBlobUrl;
        selectedFile.hidden = false;
        selectedFile.textContent = `${file.name}  (${(file.size / 1048576).toFixed(1)} MB)`;
        dropzone.classList.add('has-file');
        pickBtn.textContent = 'Change…';
        sepBtn.disabled = false;
        sepStatus.textContent = 'Ready — click "Separate stems".';
        setStatus('');
    }

    pickBtn.addEventListener('click', () => fileInput.click());
    dropzone.addEventListener('click', (e) => {
        if (e.target === pickBtn) return;
        fileInput.click();
    });
    fileInput.addEventListener('change', () => {
        if (fileInput.files && fileInput.files[0]) adoptFile(fileInput.files[0]);
    });
    const stopDefault = (e) => { e.preventDefault(); e.stopPropagation(); };
    ['dragenter', 'dragover'].forEach(ev =>
        dropzone.addEventListener(ev, (e) => {
            stopDefault(e); dropzone.classList.add('drag-over');
        }));
    ['dragleave', 'drop'].forEach(ev =>
        dropzone.addEventListener(ev, (e) => {
            stopDefault(e); dropzone.classList.remove('drag-over');
        }));
    dropzone.addEventListener('drop', (e) => {
        if (e.dataTransfer && e.dataTransfer.files[0]) {
            adoptFile(e.dataTransfer.files[0]);
        }
    });

    sepBtn.addEventListener('click', async () => {
        if (!state.file) return;
        sepBtn.disabled = true;
        sepProgress.hidden = false;
        sepProgress.value = 0;
        try {
            if (!state.sessionId) {
                sepStatus.textContent = 'Uploading…';
                const r = await uploadFile(state.file);
                state.sessionId = r.session_id;
                state.durationS = r.duration_s;
                state.digest = r.digest || null;
                if (r.project && restoreProject(r.project.remix)) {
                    sepStatus.textContent = 'Previous mix restored.';
                }
                if (r.stems_cached) {
                    sepStatus.textContent += ' Stems cached — this will be quick.';
                }
                clampLoop();
                updateTime();
            }
            sepStatus.textContent = 'Starting separation…';
            const res = await fetch('/api/stems/separate', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({session_id: state.sessionId}),
            });
            if (!res.ok) throw new Error(await res.text());
            const {job_id} = await res.json();
            await new Promise((resolve, reject) => {
                openSSE(`/api/progress/${job_id}`, {
                    onMessage: (msg) => {
                        if (typeof msg.fraction === 'number') {
                            sepProgress.value = msg.fraction;
                        }
                        if (msg.message) sepStatus.textContent = msg.message;
                        if (msg.error) reject(new Error(msg.error));
                    },
                    onDone: (msg) => msg.error
                        ? reject(new Error(msg.error)) : resolve(),
                    onError: reject,
                });
            });
            state.stemsReady = true;
            sepStatus.textContent = 'Stems ready — tweak away.';
            buildStrips();
            doRender();
        } catch (e) {
            sepStatus.textContent = `Failed: ${e.message}`;
            sepBtn.disabled = false;
        } finally {
            sepProgress.hidden = true;
        }
    });

    // ── Full render + download ───────────────────────────────────────
    renderBtn.addEventListener('click', async () => {
        if (!state.stemsReady) return;
        renderBtn.disabled = true;
        renderProgress.hidden = false;
        renderProgress.value = 0;
        try {
            const res = await fetch('/api/remix/render', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    session_id: state.sessionId,
                    stems: stemsPayload(),
                    output_format: formatSel.value,
                    mastering: {enabled: masterEnabled.checked},
                }),
            });
            if (!res.ok) throw new Error(await res.text());
            const {job_id} = await res.json();
            await new Promise((resolve, reject) => {
                openSSE(`/api/progress/${job_id}`, {
                    onMessage: (msg) => {
                        if (typeof msg.fraction === 'number') {
                            renderProgress.value = msg.fraction;
                        }
                        if (msg.error) reject(new Error(msg.error));
                    },
                    onDone: (msg) => msg.error
                        ? reject(new Error(msg.error)) : resolve(),
                    onError: reject,
                });
            });
            const a = document.createElement('a');
            a.href = resultUrl(job_id, 'processed');
            a.download = '';
            document.body.appendChild(a);
            a.click();
            a.remove();
            metricsEl.hidden = false;
            metricsEl.textContent = 'Remix rendered — check your downloads.';
        } catch (e) {
            metricsEl.hidden = false;
            metricsEl.textContent = `Render failed: ${e.message}`;
        } finally {
            renderBtn.disabled = false;
            renderProgress.hidden = true;
        }
    });

    window.addEventListener('beforeunload', () => {
        if (state.sessionId) dropSession(state.sessionId);
    });
}
