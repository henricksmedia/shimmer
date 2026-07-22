// remix.js — Orchestrates the Remix tab: upload, Demucs separation,
// per-stem channel strips (mute/solo/gain + effects rack), a looped
// A/B mini-player, and full-length render/download.

import { uploadFile, dropSession, openSSE, resultUrl,
         fetchPresets, fetchMetrics } from './api.js';
import { fmtTime } from './visualizer.js';

const RENDER_DEBOUNCE_MS = 300;

const STRIPS = [
    { key: 'vocals', label: 'Vocals', color: '#6c5ce7' },
    { key: 'drums',  label: 'Drums',  color: '#d4a55a' },
    { key: 'bass',   label: 'Bass',   color: '#3fbf7f' },
    { key: 'other',  label: 'Other',  color: '#5aa7d4' },
];

// Per-effect UI spec. `label` is the industry term; `desc` is a short
// plain-language descriptor shown muted beside it; `help` is the full
// hover explanation. Params likewise: pro term + optional muted hint.
const EFFECTS = [
    { key: 'formant', label: 'Formant', desc: 'voice character',
      help: 'Formant shifting changes the character of a voice without ' +
            'changing the pitch or melody — like the same performance from ' +
            'a different singer. Meant for vocals; sounds strange on drums.',
      params: [
        { key: 'ratio', label: 'Shift', hint: 'deeper ↔ thinner',
          min: 0.7, max: 1.4, step: 0.01, def: 0.88,
          help: 'Left = bigger, darker, more masculine voice. ' +
                'Right = smaller, brighter, younger. Center (1.0) = unchanged.' },
    ]},
    { key: 'saturation', label: 'Saturation', desc: 'warmth & drive',
      help: 'Tape/tube-style harmonic saturation. A little = thicker and ' +
            'closer; a lot = fuzzy and aggressive. Also punches up drums ' +
            'and makes bass audible on small speakers.',
      params: [
        { key: 'drive_db', label: 'Drive', hint: 'dB',
          min: 0, max: 24, step: 0.5, def: 8,
          help: '4–8 dB = warmth. 10–16 = obvious grit. 20+ = megaphone.' },
    ]},
    { key: 'doubler', label: 'Doubler', desc: 'double-tracking',
      help: 'Simulated double-tracking: slightly delayed, detuned copies ' +
            'under the original. Reads as "thick, wide, produced" — great ' +
            'on chorus vocals.',
      params: [
        { key: 'mix', label: 'Mix', hint: 'wet level',
          min: 0, max: 1, step: 0.05, def: 0.45,
          help: 'Level of the doubled takes under the dry signal.' },
        { key: 'detune_cents', label: 'Detune', hint: 'cents',
          min: 2, max: 40, step: 1, def: 12,
          help: 'Pitch offset of the copies in cents. More = wider but ' +
                'blurrier; less = tighter and subtler.' },
    ]},
    { key: 'reverb', label: 'Reverb', desc: 'room & depth',
      help: 'Puts the stem in a space. Dry = close and intimate; wet = ' +
            'distant and epic. A touch on vocals is the fastest ' +
            '"finished record" feel.',
      params: [
        { key: 'mix', label: 'Mix', hint: 'dry ↔ wet',
          min: 0, max: 1, step: 0.05, def: 0.25,
          help: 'Wet/dry balance. 0.15–0.3 = polish; 0.5+ = cathedral.' },
        { key: 'size', label: 'Size', hint: 'room ↔ hall',
          min: 0, max: 1, step: 0.05, def: 0.5,
          help: 'Small = tight room, large = huge hall with a long decay tail.' },
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
    const toolbar = $('remix-toolbar');
    const resetBtn = $('remix-reset');
    const renderBlock = $('remix-render-block');
    const renderBtn = $('remix-render-btn');
    const renderProgress = $('remix-render-progress');
    const masterEnabled = $('remix-master-enabled');
    const masterOptions = $('remix-master-options');
    const masterTarget = $('remix-master-target');
    const masterIntensity = $('remix-master-intensity');
    const masterTilt = $('remix-master-tilt');
    const cleanupSel = $('remix-cleanup');
    const abMatch = $('remix-ab-match');
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
        lufsOriginal: null,   // per-slice LUFS from the last preview render
        lufsRemix: null,
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
                    remix: {
                        strips: state.strips,
                        master: masteringPayload(),
                        cleanup: cleanupSel.value,
                    },
                }),
            }).catch(() => {});
        }, 800);
    }

    function restoreProject(remix) {
        if (!remix || !remix.strips) return false;
        let restored = false;
        const m = remix.master;
        if (m && typeof m === 'object') {
            if (typeof m.enabled === 'boolean') masterEnabled.checked = m.enabled;
            const setSel = (sel, v) => {
                if (v && [...sel.options].some(o => o.value === v)) sel.value = v;
            };
            setSel(masterTarget, m.target);
            setSel(masterIntensity, m.intensity);
            setSel(masterTilt, m.tilt);
            updateMasterUI();
        }
        if (typeof remix.cleanup === 'string' && remix.cleanup) {
            // Preset options load async; Auto/Off always exist. If the
            // saved preset isn't in the list yet, retry after they load.
            const apply = () => {
                if ([...cleanupSel.options].some(o => o.value === remix.cleanup)) {
                    cleanupSel.value = remix.cleanup;
                }
            };
            apply();
            if (cleanupSel.value !== remix.cleanup) setTimeout(apply, 1500);
        }
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

    function masteringPayload() {
        return {
            enabled: masterEnabled.checked,
            target: masterTarget.value,
            intensity: masterIntensity.value,
            tilt: masterTilt.value,
        };
    }

    function updateMasterUI() {
        masterOptions.style.opacity = masterEnabled.checked ? '' : '0.5';
        masterOptions.style.pointerEvents =
            masterEnabled.checked ? '' : 'none';
    }
    updateMasterUI();

    // Fill the artifact-cleanup select with the visible presets after the
    // built-in Auto-detect / Off choices.
    fetchPresets().then(({presets}) => {
        for (const p of presets.filter(p => p.visible !== false)) {
            const opt = document.createElement('option');
            opt.value = p.name;
            opt.textContent = p.label;
            cleanupSel.appendChild(opt);
        }
    }).catch(() => { /* Auto/Off still work without the list */ });

    // Attenuate the louder side so A/B judges the mix, not the level —
    // a mastered remix is typically much hotter than the original.
    function applyAbMatch() {
        let volO = 1, volR = 1;
        if (abMatch.checked &&
            Number.isFinite(state.lufsOriginal) &&
            Number.isFinite(state.lufsRemix)) {
            const delta = state.lufsRemix - state.lufsOriginal;
            if (delta > 0) volR = Math.pow(10, -delta / 20);
            else volO = Math.pow(10, delta / 20);
        }
        origEl.volume = Math.min(1, Math.max(0, volO));
        remixEl.volume = Math.min(1, Math.max(0, volR));
    }
    abMatch.addEventListener('change', applyAbMatch);

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
        // Exclusive solo clears other strips' solos, so every strip's
        // M/S buttons need refreshing on any solo click.
        const msRefreshers = [];
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
            soloBtn.title = 'Solo this stem (Ctrl+click to solo several together)';

            const refreshMS = () => {
                muteBtn.classList.toggle('on', st.mute);
                soloBtn.classList.toggle('on', st.solo);
            };
            msRefreshers.push(refreshMS);
            refreshMS();
            muteBtn.addEventListener('click', () => {
                st.mute = !st.mute; refreshMS(); onEdit();
            });
            soloBtn.addEventListener('click', (e) => {
                if (e.ctrlKey || e.metaKey || e.shiftKey) {
                    // Additive (DAW-style): build a solo group.
                    st.solo = !st.solo;
                } else if (st.solo) {
                    st.solo = false;   // clicking the lit S un-solos
                } else {
                    // Exclusive: this stem only; clear any other solos.
                    for (const k of Object.keys(state.strips)) {
                        state.strips[k].solo = false;
                    }
                    st.solo = true;
                }
                msRefreshers.forEach(fn => fn());
                onEdit();
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

            // Effect toggles sit in one fixed 4-across row; each enabled
            // effect's knobs render full-width in a details area below, so
            // expanding one never wrecks the grid.
            const fxRow = document.createElement('div');
            fxRow.className = 'remix-fx-row';
            const fxDetails = document.createElement('div');
            fxDetails.className = 'remix-fx-details';
            for (const e of EFFECTS) {
                const fx = st.fx[e.key];
                const box = document.createElement('div');
                box.className = 'remix-fx';

                const toggle = document.createElement('label');
                toggle.className = 'remix-fx-toggle';
                toggle.title = e.help || '';
                const check = document.createElement('input');
                check.type = 'checkbox';
                check.checked = fx.enabled;
                const tname = document.createElement('span');
                tname.textContent = e.label;
                toggle.append(check, tname);
                box.appendChild(toggle);
                box.classList.toggle('on', fx.enabled);

                const params = document.createElement('div');
                params.className = 'remix-fx-params';
                params.hidden = !fx.enabled;
                const ptitle = document.createElement('div');
                ptitle.className = 'remix-fx-params-title';
                ptitle.textContent = e.label;
                ptitle.title = e.help || '';
                if (e.desc) {
                    const d = document.createElement('span');
                    d.className = 'remix-fx-desc';
                    d.textContent = e.desc;
                    ptitle.appendChild(d);
                }
                params.appendChild(ptitle);
                for (const p of e.params) {
                    const row = document.createElement('label');
                    row.className = 'remix-fx-param';
                    row.title = p.help || '';
                    const lbl = document.createElement('span');
                    lbl.textContent = p.label;
                    if (p.hint) {
                        const h = document.createElement('em');
                        h.className = 'remix-fx-hint';
                        h.textContent = p.hint;
                        lbl.appendChild(h);
                    }
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
                fxRow.appendChild(box);
                fxDetails.appendChild(params);
            }
            strip.appendChild(fxRow);
            strip.appendChild(fxDetails);
            stripsHost.appendChild(strip);
        }
        stripsHost.hidden = false;
    }

    // ── Waveform timeline (click to seek, shaded loop window) ────────
    const waveCanvas = $('remix-wave');
    const waveCtx = waveCanvas.getContext('2d');
    let wavePeaks = null;   // Float32Array of per-column max magnitudes
    let waveRaf = 0;

    async function decodeWaveform(file) {
        wavePeaks = null;
        drawWave();
        try {
            const ac = new (window.AudioContext || window.webkitAudioContext)();
            const buf = await ac.decodeAudioData(await file.arrayBuffer());
            const cols = 800;
            const peaks = new Float32Array(cols);
            const ch0 = buf.getChannelData(0);
            const step = Math.max(1, Math.floor(ch0.length / cols));
            for (let c = 0; c < cols; c++) {
                let m = 0;
                const base = c * step;
                for (let i = 0; i < step; i += 16) {
                    const v = Math.abs(ch0[base + i] || 0);
                    if (v > m) m = v;
                }
                peaks[c] = m;
            }
            wavePeaks = peaks;
            ac.close();
        } catch (_) { /* waveform is decorative; seeking still works */ }
        drawWave();
    }

    function drawWave() {
        const rect = waveCanvas.getBoundingClientRect();
        if (rect.width < 10) return;
        const dpr = window.devicePixelRatio || 1;
        if (waveCanvas.width !== Math.round(rect.width * dpr)) {
            waveCanvas.width = Math.round(rect.width * dpr);
            waveCanvas.height = Math.round(rect.height * dpr);
        }
        const W = rect.width, H = rect.height;
        waveCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
        waveCtx.clearRect(0, 0, W, H);

        // Loop window shading
        if (state.durationS > 0) {
            const x0 = (state.loopStart / state.durationS) * W;
            const x1 = (state.loopEnd / state.durationS) * W;
            waveCtx.fillStyle = 'rgba(108, 92, 231, 0.18)';
            waveCtx.fillRect(x0, 0, Math.max(2, x1 - x0), H);
        }

        // Peaks
        if (wavePeaks) {
            waveCtx.fillStyle = 'rgba(192, 192, 208, 0.55)';
            const mid = H / 2;
            const colW = W / wavePeaks.length;
            for (let c = 0; c < wavePeaks.length; c++) {
                const h = Math.max(1, wavePeaks[c] * (H - 4));
                waveCtx.fillRect(c * colW, mid - h / 2, Math.max(1, colW), h);
            }
        }

        // Playhead
        if (state.durationS > 0) {
            const x = (positionInTrack() / state.durationS) * W;
            waveCtx.fillStyle = '#f0a500';
            waveCtx.fillRect(x - 1, 0, 2, H);
        }
    }

    function waveAnimate() {
        drawWave();
        waveRaf = state.playing ? requestAnimationFrame(waveAnimate) : 0;
    }

    waveCanvas.addEventListener('click', (e) => {
        if (!state.durationS) return;
        const rect = waveCanvas.getBoundingClientRect();
        const t = ((e.clientX - rect.left) / rect.width) * state.durationS;
        // Clicking outside the loop moves the loop window there — for BOTH
        // tracks. (Seeking Original outside the loop used to get snapped
        // back by the loop-wrap on the next timeupdate, so clicks past the
        // window looked dead.)
        if (t < state.loopStart || t >= state.loopEnd) {
            state.loopStart = t;
            clampLoop();
            if (state.stemsReady) scheduleRender(0);
        }
        if (state.active === 'remix') {
            const off = Math.max(0, t - state.loopStart);
            if (off < (remixEl.duration || Infinity)) remixEl.currentTime = off;
        } else {
            origEl.currentTime = t;
        }
        drawWave();
        updateTime();
    });

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
        if (!waveRaf) drawWave();
    });
    remixEl.addEventListener('timeupdate', () => {
        updateTime();
        if (!waveRaf) drawWave();
    });
    remixEl.loop = true;

    function activeEl() {
        return state.active === 'remix' ? remixEl : origEl;
    }

    async function play() {
        try { await activeEl().play(); state.playing = true; } catch (_) {}
        playBtn.textContent = state.playing ? '⏸' : '▶';
        if (state.playing && !waveRaf) waveAnimate();
    }
    function pause() {
        origEl.pause(); remixEl.pause();
        state.playing = false;
        playBtn.textContent = '▶';
        if (waveRaf) { cancelAnimationFrame(waveRaf); waveRaf = 0; }
        drawWave();
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
                mastering: masteringPayload(),
            });
            state.lufsOriginal = Number.isFinite(r.meta.lufs_original)
                ? r.meta.lufs_original : null;
            state.lufsRemix = Number.isFinite(r.meta.lufs_remix)
                ? r.meta.lufs_remix : null;
            applyAbMatch();
            const offset = state.active === 'remix'
                ? (remixEl.currentTime || 0) : null;
            const wasPlaying = state.playing && state.active === 'remix';
            if (state.remixBlobUrl) URL.revokeObjectURL(state.remixBlobUrl);
            state.remixBlobUrl = URL.createObjectURL(
                new Blob([r.wav], {type: 'audio/wav'}));
            // Seeking before metadata loads is silently dropped, which made
            // every re-render restart the loop from 0 — wait for it.
            await new Promise((resolve) => {
                remixEl.addEventListener('loadedmetadata', resolve, {once: true});
                remixEl.src = state.remixBlobUrl;
            });
            if (offset != null && offset < (remixEl.duration || Infinity)) {
                remixEl.currentTime = offset;
            }
            if (wasPlaying) { try { await remixEl.play(); } catch (_) {} }
            drawWave();
            tabRemix.disabled = false;
            renderBlock.hidden = false;
            const masteredTag = r.meta.mastered ? ' · mastered' : '';
            setStatus(`Live · loop ${fmtTime(state.loopStart)}–${fmtTime(state.loopEnd)} · ${r.meta.render_ms} ms${masteredTag}`, 'live');
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
    // Edits only affect the Remix track, so if the user is monitoring
    // Original, switch them over — otherwise solo/mute/knob changes are
    // inaudible and look broken.
    function onEdit() {
        if (state.active === 'original' && !tabRemix.disabled) {
            setTrack('remix');
        }
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
        toolbar.hidden = true;
        renderBlock.hidden = true;
        metricsEl.hidden = true;
        if (state.sessionId) { dropSession(state.sessionId); state.sessionId = null; }
        if (state.origBlobUrl) URL.revokeObjectURL(state.origBlobUrl);
        state.origBlobUrl = URL.createObjectURL(file);
        origEl.src = state.origBlobUrl;
        decodeWaveform(file);
        origEl.addEventListener('loadedmetadata', () => {
            if (!state.durationS) {
                state.durationS = origEl.duration || 0;
                clampLoop();
                updateTime();
                drawWave();
            }
        }, {once: true});
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
            toolbar.hidden = false;
            doRender();
        } catch (e) {
            sepStatus.textContent = `Failed: ${e.message}`;
            sepBtn.disabled = false;
        } finally {
            sepProgress.hidden = true;
        }
    });

    resetBtn.addEventListener('click', () => {
        resetStrips();
        buildStrips();       // re-render the strip UI from the fresh state
        saveProject();       // persist the reset like any other edit
        scheduleRender(0);
    });

    // Mastering changes are audible in the loop — treat them like any
    // other edit (auto-switch to the Remix track, save, re-render).
    masterEnabled.addEventListener('change', () => {
        updateMasterUI();
        onEdit();
    });
    for (const sel of [masterTarget, masterIntensity, masterTilt]) {
        sel.addEventListener('change', onEdit);
    }
    // Cleanup only runs at export — persist the choice, no re-render.
    cleanupSel.addEventListener('change', saveProject);

    // ── Full render + download ───────────────────────────────────────
    function metricChip(text, cls = '') {
        const span = document.createElement('span');
        span.className = 'metric-chip' + (cls ? ` ${cls}` : '');
        span.textContent = text;
        return span;
    }

    function renderReport(m) {
        metricsEl.innerHTML = '';
        metricsEl.hidden = false;
        if (!m) {
            metricsEl.textContent = 'Remix rendered — check your downloads.';
            return;
        }
        const chips = [];
        const clean = m.cleaning || {};
        if (clean.enabled && clean.label) {
            const conf = Number.isFinite(clean.detected_confidence)
                ? ` (${Math.round(clean.detected_confidence * 100)}%)` : '';
            chips.push(metricChip(`Cleaned · ${clean.label}${conf}`));
        }
        const mast = m.mastering || {};
        if (mast.enabled) {
            const b = mast.before || {}, a = mast.after || {};
            if (Number.isFinite(b.lufs_i) && Number.isFinite(a.lufs_i)) {
                chips.push(metricChip(
                    `${b.lufs_i.toFixed(1)} → ${a.lufs_i.toFixed(1)} LUFS` +
                    (Number.isFinite(mast.target_lufs)
                        ? ` (target ${mast.target_lufs.toFixed(0)})` : '')));
            }
            if (Number.isFinite(a.true_peak_dbtp)) {
                chips.push(metricChip(
                    `True peak ${a.true_peak_dbtp.toFixed(1)} dBTP`));
            }
            const gr = (mast.limiter || {}).max_gain_reduction_db;
            if (Number.isFinite(gr)) {
                chips.push(metricChip(
                    `Limiter ${Math.abs(gr).toFixed(1)} dB max GR`));
            }
        } else {
            chips.push(metricChip('Not mastered'));
            const lufs = (m.loudness || {}).output_lufs_i;
            if (Number.isFinite(lufs)) {
                chips.push(metricChip(`${lufs.toFixed(1)} LUFS`));
            }
        }
        if (Number.isFinite(m.duration_s)) {
            chips.push(metricChip(`${fmtTime(m.duration_s)} · ${formatSel.value.toUpperCase()}`));
        }
        metricsEl.append(...chips);
    }

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
                    mastering: masteringPayload(),
                    cleaning: {preset: cleanupSel.value},
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
            let metrics = null;
            try { metrics = await fetchMetrics(job_id); } catch (_) {}
            renderReport(metrics);
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
