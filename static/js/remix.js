// remix.js — The Remix tab: upload → separate → mix → render or export.
//
// The mixer is one lane per stem (Original on top as the reference,
// the Residual at the bottom), each lane a row of [name · M · S · fader ·
// FX] beside its own waveform. Every edit re-renders the loop the bridge
// plays; the dock on the right holds the two stage buttons (2 Separate,
// 3 Render & Download) with the quality tier under the first.

import { uploadFile, dropSession, openSSE, resultUrl,
         fetchPresets, fetchMetrics } from './api.js';
import { fmtTime } from './visualizer.js';
import { processModal } from './progress-chain.js';
import { loadRules, stagePhases } from './rules.js';

// The processing window's phases for the three Remix jobs.
const SEP_PHASES = [
    ['setup',    'Engine setup', '#22d3ee'],
    ['separate', 'Separate',     '#a78bfa'],
    ['load',     'Load',         '#c084fc'],
    ['null',     'Check',        '#2dd4bf'],
];

// Fallback tier list for the chooser when /api/stems/engine is slow or
// unreachable; the server's answer replaces it.
const TIER_FALLBACK = [
    { key: 'fast', label: 'Fast', model: 'htdemucs', stems: 4, download_mb: 80, gpu_s_per_min: 1.4, cpu_s_per_min: 20, author: 'Meta Platforms (Demucs)', license: 'MIT' },
    { key: 'best', label: 'Best', model: 'htdemucs_ft', stems: 4, download_mb: 330, gpu_s_per_min: 4.2, cpu_s_per_min: 55, author: 'Meta Platforms (Demucs)', license: 'MIT' },
    { key: 'six', label: '6 stems', model: 'htdemucs_6s', stems: 6, download_mb: 80, gpu_s_per_min: 1.4, cpu_s_per_min: 20, author: 'Meta Platforms (Demucs)', license: 'MIT' },
    { key: 'ultra', label: 'Ultra', model: 'htdemucs_ft+htdemucs+hdemucs_mmi', stems: 4, download_mb: 570, gpu_s_per_min: 19, cpu_s_per_min: 250, author: 'Meta Platforms (Demucs)', license: 'MIT' },
    { key: 'studio', label: 'Studio', model: 'kim_melroformer+htdemucs_ft', stems: 4, download_mb: 915, gpu_s_per_min: 18, cpu_s_per_min: 200, engine: 'hybrid', author: 'Kimberley Jensen (vocal model) · Meta (Demucs)', license: 'MIT' },
];
const TIER_DESC = {
    fast: 'vocals · drums · bass · other — one pass, the quickest split',
    best: 'vocals · drums · bass · other — fine-tuned, one specialist model per stem',
    six: 'vocals · drums · bass · guitar · piano · other — experimental; guitar and piano can be thin',
    ultra: 'vocals · drums · bass · other — Best averaged with two more models, two shift passes, wider overlap: less bleed and fewer seams, about 4× slower',
    studio: 'vocals · drums · bass · other — the best open vocal model (Mel-Band RoFormer, 12.6 dB) takes the vocal out, then Best splits the rest: the cleanest vocal lane',
};
// The render window: the stem mix, then the engine's stages from /api/rules
// (reading and trimming a file are not part of a remix render).
const renderPhases = (rules) => [['mix', 'Mix', '#2dd4bf'], ...stagePhases(rules, ['load', 'edit'])];
const EXPORT_PHASES = [
    ['mix',    'Stems', '#a78bfa'],
    ['export', 'Pack',  '#fbbf24'],
];

const RENDER_DEBOUNCE_MS = 300;
const SKIP_S = 5;

// One colour per lane, everywhere the lane appears (dot, meter, waveform).
const LANE_COLORS = {
    vocals: '#a78bfa', drums: '#f5a524', bass: '#4ade80', guitar: '#fb7185',
    piano: '#f472b6', other: '#38bdf8', residual: '#8b95a3',
};
const LANE_SUB = {
    vocals: 'lead & backing', drums: 'kit & percussion', bass: 'bass',
    guitar: 'guitar', piano: 'piano & keys',
    other: 'synths · keys · strings · FX',
    residual: 'what the separator dropped · keeps the lanes adding up to the original',
};
const laneColor = (key) => LANE_COLORS[key] || '#7d8894';

// Per-effect UI spec. `label` is the industry term; `desc` is a short
// plain-language descriptor; `help` is the full hover explanation.
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

function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
}

const fmtDb = (v) => `${v > 0 ? '+' : ''}${Number(v).toFixed(1)} dB`;
const fmtPct = (v) => {
    const p = v * 100;
    return p >= 10 ? `${Math.round(p)}%` : p >= 1 ? `${p.toFixed(1)}%` : p >= 0.05 ? `${p.toFixed(2)}%` : '<0.05%';
};
const fmtSecs = (s) => s < 90 ? `about ${Math.max(5, Math.round(s / 5) * 5)} s`
                             : `about ${Math.round(s / 60)} min`;

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

async function postJob(url, payload) {
    const res = await fetch(url, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error(await res.text() || `Request failed (${res.status})`);
    return (await res.json()).job_id;
}

// Follow a job's SSE stream into the processing window. Resolves when
// the job is done, rejects with the server's message on failure.
function followJob(jobId, { onMessage } = {}) {
    return new Promise((resolve, reject) => {
        openSSE(`/api/progress/${jobId}`, {
            onMessage: (msg) => {
                if (msg.stage) processModal.stage(msg.stage, msg.status || msg.message, msg.detail || '');
                else if (msg.message) processModal.stage(null, msg.message, '');
                if (typeof msg.fraction === 'number') processModal.progress(msg.fraction);
                if (onMessage) onMessage(msg);
                if (msg.error) reject(new Error(msg.error));
            },
            onDone: (msg) => msg.error ? reject(new Error(msg.error)) : resolve(msg),
            onError: () => reject(new Error('Lost the connection to the server')),
        });
    });
}

// Never save an error message as a file: probe the result first (the
// server may have restarted since the run), then download for real.
async function downloadResult(href) {
    const probe = await fetch(href);
    const ct = probe.headers.get('content-type') || '';
    if (!probe.ok || ct.startsWith('application/json')) {
        let msg = `Download failed (${probe.status}).`;
        try {
            const body = await probe.json();
            if (body && body.detail) msg = `Download failed: ${body.detail}.`;
        } catch (_) { /* no JSON body */ }
        if (/unknown job/i.test(msg)) {
            msg += ' The server was restarted since this run, so the result is gone. Render again.';
        }
        throw new Error(msg);
    }
    try { await probe.body?.cancel(); } catch (_) { /* drained */ }
    const a = document.createElement('a');
    a.href = href;
    a.download = '';
    document.body.appendChild(a);
    a.click();
    a.remove();
}


export async function initRemixTab() {
    const $ = (id) => document.getElementById(id);
    // Empty / working states
    const emptyEl = $('remix-empty');
    const workEl = $('remix-work');
    const dropzone = $('remix-dropzone');
    const dzSlot = $('remix-dropzone-slot');
    const fileInput = $('remix-file-input');
    const pickBtn = $('remix-pick-btn');
    const selectedFile = $('remix-selected-file');
    const engineLine = $('remix-engine-line');
    const steps = [$('rstep-upload'), $('rstep-separate'), $('rstep-mix')];
    // Mixer
    const mixerHost = $('remix-mixer');
    const mixerEmpty = $('remix-mixer-empty');
    const mixerFoot = $('remix-mixer-foot');
    const mixerGloss = $('remix-mixer-gloss');
    const sepPill = $('remix-sep-pill');
    const quickBar = $('remix-quick');
    const resetBtn = $('remix-reset');
    // Dock + inspector
    const sepBtn = $('remix-separate-btn');
    const sepBtnText = sepBtn.querySelector('.adb-text');
    const tierSel = $('remix-tier');
    const tierStatus = $('remix-tier-status');
    const renderBtn = $('remix-render-btn');
    const dockStatus = $('remix-dock-status');
    const masterEnabled = $('remix-master-enabled');
    const masterOptions = $('remix-master-options');
    const masterTarget = $('remix-master-target');
    const masterIntensity = $('remix-master-intensity');
    const masterTilt = $('remix-master-tilt');
    const cleanupSel = $('remix-cleanup');
    const formatSel = $('remix-format');
    const stateMaster = $('state-remix-master');
    const stateOutput = $('state-remix-output');
    const stateStems = $('state-remix-stems');
    const exportDryBtn = $('remix-export-dry');
    const exportMixedBtn = $('remix-export-mixed');
    // Result
    const resultCard = $('remix-result-card');
    const doneBanner = $('remix-done-banner');
    const doneChips = $('remix-done-chips');
    const downloadLink = $('remix-download-link');
    const metricsEl = $('remix-metrics');
    // Bridge (transport / monitor / loop)
    const abMatch = $('remix-ab-match');
    const abNote = $('remix-ab-match-note');
    const statusEl = $('remix-status');
    const tabOriginal = $('remix-tab-original');
    const tabRemix = $('remix-tab-remix');
    const windowSel = $('remix-window');
    const loopHereBtn = $('remix-loop-here');
    const playBtn = $('remix-play');
    const timeLabel = $('remix-time');
    const startBtn = $('remix-start');
    const backBtn = $('remix-back');
    const fwdBtn = $('remix-fwd');
    const seekEl = $('remix-seek');
    const seekFill = $('remix-seek-fill');
    const seekThumb = $('remix-seek-thumb');
    const seekLoop = $('remix-seek-loop');
    const tpCur = $('remix-tp-cur');
    const tpTotal = $('remix-tp-total');
    const origEl = $('remix-audio-original');
    const remixEl = $('remix-audio-remix');

    const state = {
        file: null,
        sessionId: null,
        digest: null,
        cachedTiers: [],
        uploading: null,        // promise while the upload is in flight
        saveTimer: null,
        durationS: 0,
        stemsReady: false,
        separating: false,
        info: null,             // /api/stems/info payload
        lanes: [],              // [{key, label, share, rms_db, peak_db, peaks}]
        loopStart: 0,
        loopEnd: 10,
        active: 'original',
        playing: false,
        remixBlobUrl: null,
        origBlobUrl: null,
        debounce: null,
        inflight: false,
        pending: false,
        strips: {},             // key -> {mute, solo, gain_db, fx:{...}}
        lufsOriginal: null,
        lufsRemix: null,
        engine: null,           // /api/stems/engine payload
        loaded: false,          // working layout shown
        lastRender: null,       // {jobId, format}
    };

    function setStatus(text, kind = '') {
        statusEl.textContent = text;
        statusEl.classList.remove('live', 'error', 'busy');
        if (kind) statusEl.classList.add(kind);
    }

    function setStep(step) {
        steps.forEach((s, i) => {
            if (!s) return;
            s.classList.toggle('active', i <= step);
            s.classList.toggle('done', i < step);
        });
    }

    // ── Engine + tiers ───────────────────────────────────────────────
    const tierByKey = () => Object.fromEntries((state.engine?.tiers || []).map(t => [t.key, t]));

    function estimateSeconds(tier) {
        if (!tier) return null;
        const mins = (state.durationS || 240) / 60;
        const rate = state.engine?.cuda ? tier.gpu_s_per_min : tier.cpu_s_per_min;
        return (state.engine?.load_overhead_s || 3) + rate * mins;
    }

    function fillTierSelect() {
        const tiers = state.engine?.tiers || [];
        const prev = tierSel.value || readSavedTier() || state.engine?.default_tier || 'fast';
        tierSel.innerHTML = '';
        for (const t of tiers) {
            const opt = document.createElement('option');
            opt.value = t.key;
            const est = estimateSeconds(t);
            opt.textContent = `${t.label} · ${t.stems} stems` + (est ? ` · ${fmtSecs(est)}` : '');
            tierSel.appendChild(opt);
        }
        if (tiers.some(t => t.key === prev)) tierSel.value = prev;
        else if (tiers.length) tierSel.value = state.engine?.default_tier || tiers[0].key;
        syncDock();
    }

    function readSavedTier() {
        try { return localStorage.getItem('shimmer.remix.tier') || ''; } catch (_) { return ''; }
    }
    function saveTier(key) {
        try { localStorage.setItem('shimmer.remix.tier', key); } catch (_) { /* no storage */ }
    }

    async function loadEngine() {
        try {
            const res = await fetch('/api/stems/engine');
            if (!res.ok) throw new Error(`engine status ${res.status}`);
            state.engine = await res.json();
        } catch (_) {
            state.engine = null;
        }
        fillTierSelect();
        renderEngineLine();
        if (state.file && !state.stemsReady) buildChooser();
    }

    // Stage 2 as a question in the mixer: one card per tier; clicking a
    // card picks that split and separates. Nothing runs on its own, and
    // the user's pick is never switched to a cached one.
    const chooseCards = $('remix-choose-cards');
    function buildChooser() {
        if (!chooseCards) return;
        chooseCards.innerHTML = '';
        const tiers = (state.engine && state.engine.tiers && state.engine.tiers.length)
            ? state.engine.tiers : TIER_FALLBACK;
        const last = tierSel.value || readSavedTier();
        for (const t of tiers) {
            const card = el('button', 'rc-card');
            card.type = 'button';
            card.dataset.tier = t.key;
            const cached = state.cachedTiers.includes(t.key);
            card.classList.toggle('cached', cached);
            card.classList.toggle('last', t.key === last);
            const head = el('div', 'rc-head');
            head.append(el('span', 'rc-badge', '2'), el('span', 'rc-title', t.label),
                        el('span', 'rc-count', `${t.stems} stems`));
            card.appendChild(head);
            card.appendChild(el('div', 'rc-desc', TIER_DESC[t.key] || t.blurb || ''));
            const est = estimateSeconds(t);
            const meta = [t.model];
            if (cached) meta.push('cached for this track · instant');
            else if (est) meta.push(`${state.engine && !state.engine.cuda ? 'CPU' : 'GPU'} · ${fmtSecs(est)}`);
            if (!cached && t.engine === 'hybrid' && state.engine && state.engine.roformer === false) {
                meta.push('installs the RoFormer runner first (about 300 MB)');
            }
            if (!cached && t.downloaded === false) meta.push(`downloads ${t.download_mb} MB first`);
            card.appendChild(el('div', 'rc-meta', meta.join(' · ')));
            if (t.author || t.license) {
                const lic = el('div', 'rc-license', `${t.author || ''}${t.author && t.license ? ' · ' : ''}${t.license || ''}`);
                lic.title = 'Who trained the model and its licence. Every model offered may be used on music you release and sell; the full list is in NOTICE and the About tab.';
                card.appendChild(lic);
            }
            const chips = el('div', 'rc-chips');
            if (cached) chips.appendChild(el('span', 'chip rc-chip-cached', 'cached · instant'));
            if (t.key === last && state.projectTier === t.key) chips.appendChild(el('span', 'chip', 'last time'));
            if (chips.childElementCount) card.appendChild(chips);
            card.title = `Separate into ${t.stems} stems with ${t.label} (${t.model})`;
            card.addEventListener('click', () => {
                tierSel.value = t.key;
                saveTier(t.key);
                syncDock();
                separate();
            });
            chooseCards.appendChild(card);
        }
    }

    function renderEngineLine() {
        const e = state.engine;
        if (!engineLine) return;
        if (!e) { engineLine.hidden = true; return; }
        const parts = [];
        if (!e.installed) {
            parts.push('<b>Separation engine not installed</b> · the first Separate installs it (about 3 GB, one time)');
        } else if (e.ready === false) {
            parts.push('<b>Separation engine found but not importable</b> · the first Separate repairs it');
        } else {
            parts.push(`<b>Separation engine ready</b>${e.demucs ? ` · Demucs ${e.demucs}` : ''}`);
        }
        parts.push(e.cuda ? `GPU: ${e.gpu || 'NVIDIA'}` : 'no NVIDIA GPU found · CPU mode, several times slower');
        const best = (e.tiers || []).find(t => t.key === 'best');
        const fast = (e.tiers || []).find(t => t.key === 'fast');
        if (fast && best) {
            const f = estimateSeconds(fast), b = estimateSeconds(best);
            parts.push(`a four-minute song: Fast ${fmtSecs(f).replace('about ', '~')}, Best ${fmtSecs(b).replace('about ', '~')}`);
        }
        engineLine.innerHTML = parts.join(' <span class="sep">·</span> ');
        engineLine.hidden = false;
    }

    // ── Dock: the two stage buttons and their status lines ───────────
    function syncDock() {
        const tier = tierByKey()[tierSel.value];
        const hasFile = !!state.file;
        const cached = tier && state.cachedTiers.includes(tier.key);
        sepBtn.disabled = !hasFile || state.separating;
        sepBtn.classList.toggle('busy', state.separating);
        sepBtn.classList.toggle('done', state.stemsReady && !state.separating);
        const current = state.info && tier && state.info.tier === tier.key;
        if (state.separating) sepBtnText.textContent = 'Separating…';
        else if (state.stemsReady && current) sepBtnText.textContent = `Separated · ${tier.label}`;
        else if (state.stemsReady) sepBtnText.textContent = `Separate again · ${tier ? tier.label : ''}`;
        else sepBtnText.textContent = 'Separate stems';

        const bits = [];
        if (tier) {
            bits.push(tier.model);
            if (cached) bits.push('cached for this track · instant');
            else {
                const est = estimateSeconds(tier);
                if (est) bits.push(state.engine?.cuda ? `GPU · ${fmtSecs(est)}` : `CPU · ${fmtSecs(est)}`);
                if (tier.downloaded === false) bits.push(`downloads ${tier.download_mb} MB first`);
            }
        }
        tierStatus.textContent = bits.join(' · ');
        tierStatus.title = tier ? tier.blurb : '';

        renderBtn.disabled = !state.stemsReady;
        exportDryBtn.disabled = !state.stemsReady;
        exportMixedBtn.disabled = !state.stemsReady;
        syncInspectorStates();
    }

    function syncInspectorStates() {
        // The level, read from the menu's own label (filled from /api/rules).
        const opt = masterTarget.selectedOptions[0];
        const target = ((opt && opt.textContent.match(/[−-]\d+(?:\.\d+)? LUFS/)) || [masterTarget.value])[0];
        if (stateMaster) stateMaster.textContent = masterEnabled.checked
            ? `${target} · match ${masterIntensity.value}` : 'off';
        if (stateOutput) {
            const clean = cleanupSel.value === 'off' ? 'no cleanup'
                : cleanupSel.value === 'auto' ? 'auto cleanup'
                : (cleanupSel.selectedOptions[0]?.textContent || cleanupSel.value);
            stateOutput.textContent = `${formatSel.value.toUpperCase()} · ${clean}`;
        }
        if (stateStems && !stateStems.dataset.sticky) {
            stateStems.textContent = state.stemsReady ? `${state.lanes.length} lanes` : '';
        }
        dockStatus.hidden = !state.stemsReady;
        if (state.stemsReady) {
            const m = masterEnabled.checked ? `master to ${target}` : 'no mastering';
            const c = cleanupSel.value === 'off' ? 'no cleanup' : 'cleanup auto';
            dockStatus.textContent = `${m} · ${c} · ${formatSel.value.toUpperCase()}`;
        }
    }

    tierSel.addEventListener('change', () => { saveTier(tierSel.value); syncDock(); saveProject(); });

    // ── Strip state + payload ────────────────────────────────────────
    function freshStrip() {
        return {
            mute: false, solo: false, gain_db: 0, pan: 0,
            fx: Object.fromEntries(EFFECTS.map(e => [e.key, {
                enabled: false,
                ...Object.fromEntries(e.params.map(p => [p.key, p.def])),
            }])),
        };
    }
    // Reset in place: the rows and FX panels hold references to these
    // objects, so replacing them would leave the controls showing the
    // old state.
    function resetStrips() {
        for (const lane of state.lanes) {
            const st = stripFor(lane.key);
            const fresh = freshStrip();
            st.mute = fresh.mute; st.solo = fresh.solo;
            st.gain_db = fresh.gain_db; st.pan = fresh.pan;
            for (const e of EFFECTS) Object.assign(st.fx[e.key], fresh.fx[e.key]);
        }
    }
    function stripFor(key) {
        if (!state.strips[key]) state.strips[key] = freshStrip();
        return state.strips[key];
    }
    const anySolo = () => state.lanes.some(l => stripFor(l.key).solo);
    const effectiveMute = (key) => {
        const st = stripFor(key);
        return anySolo() ? !st.solo : st.mute;
    };

    function stemsPayload() {
        const out = {};
        for (const lane of state.lanes) {
            const st = stripFor(lane.key);
            const effects = {};
            for (const e of EFFECTS) {
                const fx = st.fx[e.key];
                effects[e.key] = { enabled: fx.enabled };
                for (const p of e.params) effects[e.key][p.key] = fx[p.key];
            }
            out[lane.key] = { gain_db: st.gain_db, pan: st.pan || 0,
                              mute: effectiveMute(lane.key), effects };
        }
        return out;
    }

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
                        tier: tierSel.value,
                        format: formatSel.value,
                    },
                }),
            }).catch(() => {});
        }, 800);
    }

    function restoreProject(remix) {
        if (!remix || typeof remix !== 'object') return false;
        let restored = false;
        const setSel = (sel, v) => {
            if (v && [...sel.options].some(o => o.value === v)) { sel.value = v; return true; }
            return false;
        };
        const m = remix.master;
        if (m && typeof m === 'object') {
            if (typeof m.enabled === 'boolean') masterEnabled.checked = m.enabled;
            setSel(masterTarget, m.target);
            setSel(masterIntensity, m.intensity);
            setSel(masterTilt, m.tilt);
            updateMasterUI();
        }
        if (typeof remix.cleanup === 'string' && remix.cleanup) {
            // Preset options load async; Auto/Off always exist. If the
            // saved preset isn't in the list yet, retry after they load.
            if (!setSel(cleanupSel, remix.cleanup)) setTimeout(() => setSel(cleanupSel, remix.cleanup), 1500);
        }
        if (typeof remix.format === 'string') setSel(formatSel, remix.format);
        if (typeof remix.tier === 'string' && setSel(tierSel, remix.tier)) restored = true;
        if (remix.strips && typeof remix.strips === 'object') {
            for (const [key, saved] of Object.entries(remix.strips)) {
                if (!saved || typeof saved !== 'object') continue;
                const st = stripFor(key);
                if (typeof saved.mute === 'boolean') st.mute = saved.mute;
                if (typeof saved.solo === 'boolean') st.solo = saved.solo;
                if (Number.isFinite(saved.gain_db)) st.gain_db = saved.gain_db;
                if (Number.isFinite(saved.pan)) st.pan = Math.max(-1, Math.min(1, saved.pan));
                for (const e of EFFECTS) {
                    const sfx = saved.fx && saved.fx[e.key];
                    if (!sfx) continue;
                    st.fx[e.key].enabled = !!sfx.enabled;
                    for (const p of e.params) {
                        if (Number.isFinite(sfx[p.key])) st.fx[e.key][p.key] = sfx[p.key];
                    }
                }
                restored = true;
            }
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
        masterOptions.style.pointerEvents = masterEnabled.checked ? '' : 'none';
        syncInspectorStates();
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
    // Capped like the Master tab's match: a muted or soloed-down remix can
    // read 100 dB quieter than the original, and matching that would turn
    // the Original monitor off ("I can't play the original").
    const MATCH_MAX_DB = 6;
    function applyAbMatch() {
        let volO = 1, volR = 1;
        let note = '';
        const usable = Number.isFinite(state.lufsOriginal) &&
            Number.isFinite(state.lufsRemix) &&
            state.lufsOriginal > -60 && state.lufsRemix > -60;
        if (abMatch.checked && usable) {
            const raw = state.lufsRemix - state.lufsOriginal;
            const delta = Math.max(-MATCH_MAX_DB, Math.min(MATCH_MAX_DB, raw));
            if (delta > 0) volR = Math.pow(10, -delta / 20);
            else volO = Math.pow(10, delta / 20);
            if (Math.abs(delta) >= 0.1) {
                note = `${delta > 0 ? 'Remix' : 'Original'} −${Math.abs(delta).toFixed(1)} dB`;
                if (Math.abs(raw) > MATCH_MAX_DB + 1e-6) note += ' (capped)';
            }
        } else if (abMatch.checked && !usable && state.lufsRemix != null) {
            note = 'remix silent · no match';
        }
        origEl.volume = Math.min(1, Math.max(0, volO));
        remixEl.volume = Math.min(1, Math.max(0, volR));
        if (abNote) {
            abNote.textContent = note;
            abNote.title = note ? 'Monitoring gain only — the louder side is turned down so ' +
                'you compare sound, not level. Never applied to your export.' : '';
        }
    }
    abMatch.addEventListener('change', applyAbMatch);

    // ── The mixer ────────────────────────────────────────────────────
    const rows = new Map();      // key -> {row, canvas, base, refresh, fxPanel, fxBtn}
    let monitorBtns = null;      // {original, remix} pills in the ruler corner
    let rulerCanvas = null;
    let mixCanvas = null;
    let waveRaf = 0;
    let peakScale = 1;           // the loudest column across lanes → full height

    const heightFor = (key) => key === '__mix' ? 56 : key === 'residual' ? 48 : 60;
    // A gentle curve so a lane at 15 % of full scale still reads; applied
    // to every lane alike, so louder still draws taller.
    const shape = (v) => Math.pow(Math.max(0, v) / (peakScale || 1), 0.6);

    function clearMixer() {
        for (const r of rows.values()) r.row.remove();
        rows.clear();
        mixerHost.querySelectorAll('.rm-row, .rm-fx').forEach(n => n.remove());
        rulerCanvas = null;
        monitorBtns = null;
        mixCanvas = null;
        mixerEmpty.hidden = false;
        quickBar.hidden = true;
        sepPill.hidden = true;
        mixerGloss.textContent = 'one lane per stem · the residual is what the separator dropped';
    }

    function buildMixer(info) {
        clearMixer();
        mixerEmpty.hidden = true;
        state.lanes = (info.stems || []).map(s => ({ ...s }));
        const allPeaks = [...(info.mix_peaks || []), ...state.lanes.flatMap(l => l.peaks || [])];
        peakScale = Math.max(0.05, ...allPeaks);

        // Time ruler; its head corner carries the monitor switch, so the
        // A/B is right above the lanes as well as in the bridge.
        const ruler = el('div', 'rm-row rm-ruler');
        const corner = el('div', 'rm-head rm-corner');
        const monO = el('button', 'rm-mon', '');
        monO.type = 'button';
        monO.append(el('b', null, '1'), document.createTextNode(' Original'));
        monO.title = 'Listen to the untouched upload (key 1)';
        const monR = el('button', 'rm-mon', '');
        monR.type = 'button';
        monR.append(el('b', null, '2'), document.createTextNode(' Remix'));
        monR.title = 'Listen to the remix: every lane with its fader, pan and effects (key 2)';
        monO.addEventListener('click', () => listenTo('original'));
        monR.addEventListener('click', () => listenTo('remix'));
        corner.append(monO, monR);
        monitorBtns = { original: monO, remix: monR };
        ruler.append(corner);
        const rl = el('div', 'rm-lane');
        rulerCanvas = el('canvas', 'rm-canvas');
        rl.appendChild(rulerCanvas);
        ruler.appendChild(rl);
        mixerHost.appendChild(ruler);
        bindSeek(rulerCanvas);

        // Original on top: the reference the monitor's key 1 plays.
        const mixRow = makeRow({ key: '__mix', label: 'Original', sub: 'the upload as it is · key 1',
                                 peaks: info.mix_peaks || [], controls: false });
        mixCanvas = mixRow.canvas;

        for (const lane of state.lanes) {
            stripFor(lane.key);
            makeRow({ ...lane, sub: LANE_SUB[lane.key] || '', controls: true });
        }
        quickBar.hidden = false;
        renderSepPill(info);
        syncListening();
        requestAnimationFrame(() => { redrawAll(true); });
    }

    function renderSepPill(info) {
        const count = `${state.lanes.filter(l => l.key !== 'residual').length} stems`;
        const bits = [count];
        if (info.label && info.label !== count) bits.push(info.label);
        if (info.cached) bits.push('cached');
        else if (Number.isFinite(info.elapsed_s) && info.elapsed_s > 0) {
            bits.push(`${info.device === 'cuda' ? 'GPU' : 'CPU'} · ${Math.round(info.elapsed_s)} s`);
        }
        sepPill.textContent = bits.join(' · ');
        sepPill.title = `${info.model || ''}${info.format === 'int16' ? ' · older 16-bit cache; separate again for float stems' : ''}`;
        sepPill.hidden = false;
        if (Number.isFinite(info.null_db)) {
            mixerGloss.innerHTML = `Residual <b>${info.null_db.toFixed(1)} dB</b> · what the separator dropped, kept as its own lane so the lanes add back up to the original`;
            mixerGloss.title = 'Level of (mix − stems) relative to the mix. Lower means a cleaner split; whatever is left lives in the Residual lane, so nothing is lost.';
        }
    }

    function makeRow(spec) {
        const key = spec.key;
        const color = key === '__mix' ? '#aab3bf' : laneColor(key);
        const row = el('div', 'rm-row' + (key === '__mix' ? ' rm-mix' : key === 'residual' ? ' rm-residual' : ''));
        row.dataset.stem = key;
        row.style.setProperty('--lane', color);
        row.style.setProperty('--lane-h', `${heightFor(key)}px`);

        const head = el('div', 'rm-head');
        const title = el('div', 'rm-title');
        title.append(el('span', 'rm-dot'), el('span', 'rm-name', spec.label));
        if (spec.sub) {
            const sub = el('span', 'rm-sub', spec.sub);
            sub.title = spec.sub;
            title.appendChild(sub);
        }
        if (Number.isFinite(spec.share)) {
            const share = el('span', 'rm-share', fmtPct(spec.share));
            share.title = `${fmtPct(spec.share)} of the mix's energy · RMS ${spec.rms_db.toFixed(1)} dBFS · peak ${spec.peak_db.toFixed(1)} dBFS`;
            title.appendChild(share);
        }
        head.appendChild(title);

        const entry = { row, canvas: null, base: null, baseW: 0, refresh: null, fxPanel: null, fxBtn: null };

        if (key === '__mix') {
            // The reference lane's one control: listen to it. It plays the
            // untouched upload inside the loop; the remix is key 2.
            const ctl = el('div', 'rm-ctl');
            const listen = el('button', 'rm-listen', '▶ Listen');
            listen.type = 'button';
            listen.title = 'Play the untouched upload in the loop (key 1). Press 2 to switch to the remix.';
            listen.addEventListener('click', () => {
                if (state.active === 'original' && state.playing) pause();
                else listenTo('original');
            });
            ctl.append(listen, el('span', 'rm-listen-hint', 'key 1 · the remix is key 2'));
            head.appendChild(ctl);
            entry.listenBtn = listen;
        }

        if (spec.controls) {
            const st = stripFor(key);
            const ctl = el('div', 'rm-ctl');
            const muteBtn = el('button', 'remix-ms-btn', 'M');
            muteBtn.type = 'button';
            muteBtn.title = 'Mute this lane';
            const soloBtn = el('button', 'remix-ms-btn solo', 'S');
            soloBtn.type = 'button';
            soloBtn.title = 'Solo this lane (Ctrl+click to solo several together)';
            const gain = el('input', 'rm-gain');
            gain.type = 'range';
            gain.min = '-24'; gain.max = '12'; gain.step = '0.5';
            gain.value = String(st.gain_db);
            gain.title = 'Lane level · double-click for 0 dB';
            const gainVal = el('span', 'rm-gain-val', fmtDb(st.gain_db));
            const pan = el('input', 'rm-pan');
            pan.type = 'range';
            pan.min = '-1'; pan.max = '1'; pan.step = '0.05';
            pan.value = String(st.pan || 0);
            pan.title = 'Pan (balance) · double-click for centre';
            const fmtPan = (v) => Math.abs(v) < 0.025 ? 'C'
                : `${v < 0 ? 'L' : 'R'}${Math.round(Math.abs(v) * 100)}`;
            const panVal = el('span', 'rm-pan-val', fmtPan(st.pan || 0));
            ctl.append(muteBtn, soloBtn, gain, gainVal, pan, panVal);

            let fxBtn = null, fxPanel = null;
            if (key !== 'residual') {
                fxBtn = el('button', 'rm-fx-btn', 'FX');
                fxBtn.type = 'button';
                fxBtn.title = 'Effects rack: formant, saturation, doubler, reverb';
                title.insertBefore(fxBtn, title.querySelector('.rm-share'));
                fxPanel = buildFxPanel(key, () => refresh());
                fxPanel.hidden = true;
                fxBtn.addEventListener('click', () => {
                    fxPanel.hidden = !fxPanel.hidden;
                    fxBtn.classList.toggle('open', !fxPanel.hidden);
                });
            }
            head.appendChild(ctl);
            pan.addEventListener('input', () => {
                st.pan = parseFloat(pan.value);
                panVal.textContent = fmtPan(st.pan);
                onEdit();
            });
            pan.addEventListener('dblclick', () => { st.pan = 0; onEdit(); });

            const meter = el('div', 'rm-meter');
            const fill = el('i');
            const pk = el('b');
            meter.append(fill, pk);
            const rms = Number.isFinite(spec.rms_db) ? spec.rms_db : -60;
            const peak = Number.isFinite(spec.peak_db) ? spec.peak_db : -60;
            fill.style.width = `${Math.max(0, Math.min(100, (rms + 60) / 60 * 100))}%`;
            pk.style.left = `${Math.max(0, Math.min(100, (peak + 60) / 60 * 100))}%`;
            meter.title = `RMS ${rms.toFixed(1)} dBFS · peak ${peak.toFixed(1)} dBFS (whole file)`;
            head.appendChild(meter);

            const refresh = () => {
                muteBtn.classList.toggle('on', st.mute);
                soloBtn.classList.toggle('on', st.solo);
                gain.value = String(st.gain_db);
                gainVal.textContent = fmtDb(st.gain_db);
                pan.value = String(st.pan || 0);
                panVal.textContent = fmtPan(st.pan || 0);
                const silent = effectiveMute(key);
                row.classList.toggle('silent', silent);
                if (fxBtn) {
                    const n = EFFECTS.filter(e => st.fx[e.key].enabled).length;
                    fxBtn.textContent = n ? `FX ${n}` : 'FX';
                    fxBtn.classList.toggle('lit', n > 0);
                }
                entry.base = null;   // mute state changes the waveform's alpha
                drawLane(entry, key);
            };
            entry.refresh = refresh;
            entry.fxPanel = fxPanel;
            entry.fxBtn = fxBtn;

            muteBtn.addEventListener('click', () => { st.mute = !st.mute; onEdit(); });
            soloBtn.addEventListener('click', (e) => {
                if (e.ctrlKey || e.metaKey || e.shiftKey) {
                    st.solo = !st.solo;                 // additive, DAW-style
                } else if (st.solo) {
                    st.solo = false;                    // clicking the lit S un-solos
                } else {
                    for (const l of state.lanes) stripFor(l.key).solo = false;
                    st.solo = true;                     // exclusive
                }
                onEdit();
            });
            gain.addEventListener('input', () => { st.gain_db = parseFloat(gain.value); onEdit(); });
            gain.addEventListener('dblclick', () => { st.gain_db = 0; onEdit(); });
        }

        const lane = el('div', 'rm-lane');
        const canvas = el('canvas', 'rm-canvas');
        canvas.title = 'Click to seek · the shaded band is the loop window';
        lane.appendChild(canvas);
        bindSeek(canvas);
        // Clicking a lane's name listens to that side: the Original row
        // plays the upload, any stem row plays the remix. Controls keep
        // their own clicks.
        head.title = key === '__mix' ? 'Click to listen to the original (key 1)'
                                     : 'Click to listen to the remix (key 2)';
        head.addEventListener('click', (e) => {
            if (e.target.closest('button, input, label')) return;
            listenTo(key === '__mix' ? 'original' : 'remix');
        });
        row.append(head, lane);
        entry.canvas = canvas;
        entry.peaks = spec.peaks || [];
        entry.color = color;
        mixerHost.appendChild(row);
        if (entry.fxPanel) mixerHost.appendChild(entry.fxPanel);
        rows.set(key, entry);
        if (entry.refresh) entry.refresh();
        return entry;
    }

    // The effects rack under a lane: four chips, and each enabled effect's
    // sliders inline beside them.
    function buildFxPanel(key, onChange) {
        const st = stripFor(key);
        const panel = el('div', 'rm-fx');
        panel.dataset.for = key;
        panel.style.setProperty('--lane', laneColor(key));
        const chips = el('div', 'rm-fx-chips');
        const params = el('div', 'rm-fx-params');
        for (const e of EFFECTS) {
            const fx = st.fx[e.key];
            const chip = el('button', 'rm-fx-chip');
            chip.type = 'button';
            chip.title = e.help || '';
            chip.append(el('b', null, e.label), el('small', null, e.desc));
            const group = el('div', 'rm-fx-group');
            group.append(el('div', 'rm-fx-group-title', e.label));
            for (const p of e.params) {
                const rowEl = el('label', 'rm-fx-param');
                rowEl.title = p.help || '';
                const lbl = el('span', 'rm-fx-label', p.label);
                if (p.hint) lbl.appendChild(el('em', 'rm-fx-hint', p.hint));
                const range = el('input');
                range.type = 'range';
                range.min = String(p.min); range.max = String(p.max); range.step = String(p.step);
                range.value = String(fx[p.key]);
                const val = el('span', 'rm-fx-val', String(fx[p.key]));
                range.addEventListener('input', () => {
                    fx[p.key] = parseFloat(range.value);
                    val.textContent = String(fx[p.key]);
                    onEdit();
                });
                range.addEventListener('dblclick', () => {
                    fx[p.key] = p.def; range.value = String(p.def); val.textContent = String(p.def); onEdit();
                });
                rowEl.append(lbl, range, val);
                group.appendChild(rowEl);
            }
            const sync = () => {
                chip.classList.toggle('on', fx.enabled);
                group.hidden = !fx.enabled;
                for (const p of e.params) {
                    const r = group.querySelectorAll('input')[e.params.indexOf(p)];
                    if (r) r.value = String(fx[p.key]);
                }
            };
            chip.addEventListener('click', () => { fx.enabled = !fx.enabled; sync(); onChange(); onEdit(); });
            sync();
            chip._sync = sync;
            chips.appendChild(chip);
            params.appendChild(group);
        }
        panel.append(chips, params);
        panel._sync = () => chips.querySelectorAll('.rm-fx-chip').forEach(c => c._sync && c._sync());
        return panel;
    }

    function refreshRows() {
        for (const [key, r] of rows) {
            if (r.refresh) r.refresh();
            if (r.fxPanel && r.fxPanel._sync) r.fxPanel._sync();
            if (key === '__mix') drawLane(r, key);
        }
    }

    function syncListening() {
        for (const [key, r] of rows) {
            const listening = key === '__mix' ? state.active === 'original' : state.active === 'remix';
            r.row.classList.toggle('listening', listening);
            if (r.listenBtn) {
                const on = state.active === 'original';
                r.listenBtn.textContent = on && state.playing ? '⏸ Listening' : '▶ Listen';
                r.listenBtn.classList.toggle('on', on);
            }
        }
        if (monitorBtns) {
            monitorBtns.original.classList.toggle('on', state.active === 'original');
            monitorBtns.remix.classList.toggle('on', state.active === 'remix');
            monitorBtns.remix.disabled = tabRemix.disabled;
        }
    }

    // Switch the monitor to one side and make sure it is audible: inside
    // the loop, and playing. This is what every "listen" control calls.
    function listenTo(which) {
        if (which === 'remix' && tabRemix.disabled) return;
        setTrack(which);
        if (which === 'original' &&
            (origEl.currentTime < state.loopStart || origEl.currentTime >= state.loopEnd)) {
            origEl.currentTime = state.loopStart;
        }
        if (!state.playing) play();
        else syncListening();
    }

    // ── Lane drawing ─────────────────────────────────────────────────
    function laneBase(entry, key, W, H, dpr) {
        if (entry.base && entry.baseW === W && entry.baseH === H) return entry.base;
        const off = document.createElement('canvas');
        off.width = Math.round(W * dpr);
        off.height = Math.round(H * dpr);
        const c = off.getContext('2d');
        c.setTransform(dpr, 0, 0, dpr, 0, 0);
        const peaks = entry.peaks || [];
        const silent = key !== '__mix' && effectiveMute(key);
        c.fillStyle = entry.color;
        c.globalAlpha = key === '__mix' ? 0.7 : silent ? 0.22 : 0.85;
        const mid = H / 2;
        const colW = W / Math.max(1, peaks.length);
        for (let i = 0; i < peaks.length; i++) {
            const h = Math.max(1, shape(peaks[i]) * (H - 6));
            c.fillRect(i * colW, mid - h / 2, Math.max(1, colW - 0.3), h);
        }
        c.globalAlpha = 1;
        entry.base = off;
        entry.baseW = W;
        entry.baseH = H;
        return off;
    }

    function drawLane(entry, key) {
        const canvas = entry.canvas;
        if (!canvas) return;
        const rect = canvas.getBoundingClientRect();
        if (rect.width < 10 || rect.height < 4) return;
        const dpr = window.devicePixelRatio || 1;
        const W = rect.width, H = rect.height;
        if (canvas.width !== Math.round(W * dpr) || canvas.height !== Math.round(H * dpr)) {
            canvas.width = Math.round(W * dpr);
            canvas.height = Math.round(H * dpr);
        }
        const ctx = canvas.getContext('2d');
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.clearRect(0, 0, W, H);
        ctx.drawImage(laneBase(entry, key, W, H, dpr), 0, 0, W, H);
        drawOverlays(ctx, W, H, false);
    }

    function drawOverlays(ctx, W, H, ruler) {
        if (!(state.durationS > 0)) return;
        const d = state.durationS;
        const x0 = (state.loopStart / d) * W;
        const x1 = (state.loopEnd / d) * W;
        ctx.fillStyle = ruler ? 'rgba(245, 165, 36, 0.35)' : 'rgba(167, 139, 250, 0.14)';
        ctx.fillRect(x0, 0, Math.max(2, x1 - x0), H);
        if (!ruler) {
            ctx.fillStyle = 'rgba(167, 139, 250, 0.55)';
            ctx.fillRect(x0, 0, 1, H);
            ctx.fillRect(x1 - 1, 0, 1, H);
        }
        const x = (positionInTrack() / d) * W;
        ctx.fillStyle = '#f5a524';
        ctx.fillRect(x - 1, 0, 2, H);
    }

    function drawRuler() {
        if (!rulerCanvas) return;
        const rect = rulerCanvas.getBoundingClientRect();
        if (rect.width < 10) return;
        const dpr = window.devicePixelRatio || 1;
        const W = rect.width, H = rect.height;
        if (rulerCanvas.width !== Math.round(W * dpr) || rulerCanvas.height !== Math.round(H * dpr)) {
            rulerCanvas.width = Math.round(W * dpr);
            rulerCanvas.height = Math.round(H * dpr);
        }
        const ctx = rulerCanvas.getContext('2d');
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.clearRect(0, 0, W, H);
        const d = state.durationS || 0;
        if (d > 0) {
            // Ticks every 5/10/15/30/60 s so labels never crowd.
            const stepS = [5, 10, 15, 30, 60, 120].find(s => (W / (d / s)) >= 58) || 120;
            ctx.font = '10px "JetBrains Mono", Consolas, monospace';
            ctx.textBaseline = 'top';
            for (let t = 0; t <= d; t += stepS) {
                const x = (t / d) * W;
                ctx.fillStyle = 'rgba(255,255,255,0.18)';
                ctx.fillRect(x, H - 5, 1, 5);
                ctx.fillStyle = '#7d8894';
                if (x + 30 < W) ctx.fillText(fmtTime(t), x + 3, 1);
            }
        }
        drawOverlays(ctx, W, H, true);
    }

    function redrawAll(force = false) {
        if (force) for (const r of rows.values()) r.base = null;
        for (const [key, r] of rows) drawLane(r, key);
        drawRuler();
    }

    function waveAnimate() {
        redrawAll();
        waveRaf = state.playing ? requestAnimationFrame(waveAnimate) : 0;
    }

    function bindSeek(canvas) {
        canvas.addEventListener('click', (e) => {
            if (!state.durationS) return;
            const rect = canvas.getBoundingClientRect();
            seekTo(((e.clientX - rect.left) / rect.width) * state.durationS);
        });
    }

    window.addEventListener('resize', () => { if (rows.size) redrawAll(true); });

    // ── Quick mixes ──────────────────────────────────────────────────
    function quickMix(kind) {
        if (!state.stemsReady) return;
        const has = (k) => state.lanes.some(l => l.key === k);
        if (kind === 'instrumental' && has('vocals')) {
            for (const l of state.lanes) stripFor(l.key).solo = false;
            stripFor('vocals').mute = true;
        } else if (kind === 'acapella' && has('vocals')) {
            for (const l of state.lanes) stripFor(l.key).solo = false;
            stripFor('vocals').mute = false;
            stripFor('vocals').solo = true;
        } else if (kind === 'vocal-up' && has('vocals')) {
            for (const l of state.lanes) {
                const st = stripFor(l.key);
                st.gain_db = l.key === 'vocals' ? 2 : l.key === 'residual' ? st.gain_db : -1;
            }
        } else {
            return;
        }
        refreshRows();
        onEdit();
    }
    quickBar.querySelectorAll('[data-quick]').forEach(btn =>
        btn.addEventListener('click', () => quickMix(btn.dataset.quick)));
    resetBtn.addEventListener('click', () => {
        resetStrips();
        refreshRows();
        saveProject();
        scheduleRender(0);
    });

    // ── Seeking + transport ──────────────────────────────────────────
    // Seek anywhere in the track. Outside the loop, the loop window moves
    // there first, for BOTH tracks.
    function seekTo(t) {
        if (!state.durationS) return;
        t = Math.max(0, Math.min(state.durationS, t));
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
        redrawAll();
        updateTime();
    }
    if (startBtn) startBtn.addEventListener('click', () => seekTo(0));
    if (backBtn) backBtn.addEventListener('click', () => seekTo(positionInTrack() - SKIP_S));
    if (fwdBtn) fwdBtn.addEventListener('click', () => seekTo(positionInTrack() + SKIP_S));

    // The scrubber in the bridge: click or drag to seek.
    if (seekEl) {
        const fracAt = (ev) => {
            const r = seekEl.getBoundingClientRect();
            return r.width > 0 ? Math.max(0, Math.min(1, (ev.clientX - r.left) / r.width)) : 0;
        };
        let dragging = false;
        seekEl.addEventListener('pointerdown', (ev) => {
            if (!state.durationS) return;
            dragging = true;
            seekEl.setPointerCapture(ev.pointerId);
            seekTo(fracAt(ev) * state.durationS);
        });
        seekEl.addEventListener('pointermove', (ev) => {
            if (dragging) seekTo(fracAt(ev) * state.durationS);
        });
        const stop = (ev) => {
            if (!dragging) return;
            dragging = false;
            try { seekEl.releasePointerCapture(ev.pointerId); } catch (_) {}
        };
        seekEl.addEventListener('pointerup', stop);
        seekEl.addEventListener('pointercancel', stop);
        seekEl.addEventListener('keydown', (ev) => {
            if (ev.key === 'ArrowLeft' || ev.key === 'ArrowRight') {
                ev.preventDefault();
                seekTo(positionInTrack() + (ev.key === 'ArrowLeft' ? -SKIP_S : SKIP_S));
            }
        });
    }

    // Keyboard, Remix tab only: Space play, 1/2 switch track, arrows skip.
    document.addEventListener('keydown', (ev) => {
        const tag = (ev.target && ev.target.tagName || '').toLowerCase();
        if (['input', 'select', 'textarea', 'button'].includes(tag)) return;
        const panel = document.getElementById('tab-remix');
        if (!panel || !panel.classList.contains('active')) return;
        if (ev.code === 'Space') { ev.preventDefault(); playBtn.click(); }
        else if (ev.key === '1') setTrack('original');
        else if (ev.key === '2') { if (!tabRemix.disabled) setTrack('remix'); }
        else if (ev.key === 'ArrowLeft' || ev.key === 'ArrowRight') {
            ev.preventDefault();
            seekTo(positionInTrack() + (ev.key === 'ArrowLeft' ? -SKIP_S : SKIP_S));
        }
    });

    // ── Loop player ──────────────────────────────────────────────────
    function clampLoop() {
        const win = parseFloat(windowSel.value) || 10;
        const start = Math.max(0, Math.min(state.loopStart,
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
        const t = positionInTrack();
        const d = state.durationS || 0;
        timeLabel.textContent = `${fmtTime(t)} / ${fmtTime(d)}`;
        if (tpCur) tpCur.textContent = fmtTime(t);
        if (tpTotal) tpTotal.textContent = fmtTime(d);
        if (!seekEl) return;
        const frac = d > 0 ? Math.max(0, Math.min(1, t / d)) : 0;
        seekFill.style.width = `${frac * 100}%`;
        seekThumb.style.left = `${frac * 100}%`;
        seekEl.setAttribute('aria-valuenow', String(Math.round(frac * 100)));
        seekEl.setAttribute('aria-valuetext', `${fmtTime(t)} of ${fmtTime(d)}`);
        if (d > 0 && state.loopEnd > state.loopStart) {
            seekLoop.hidden = false;
            seekLoop.style.left = `${(state.loopStart / d) * 100}%`;
            seekLoop.style.width = `${Math.max(0.5, ((state.loopEnd - state.loopStart) / d) * 100)}%`;
        } else {
            seekLoop.hidden = true;
        }
    }

    origEl.addEventListener('timeupdate', () => {
        if (state.active === 'original' && state.playing &&
            origEl.currentTime >= state.loopEnd) {
            origEl.currentTime = state.loopStart;
        }
        updateTime();
        if (!waveRaf) redrawAll();
    });
    remixEl.addEventListener('timeupdate', () => {
        updateTime();
        if (!waveRaf) redrawAll();
    });
    remixEl.loop = true;

    function activeEl() {
        return state.active === 'remix' ? remixEl : origEl;
    }

    async function play() {
        try { await activeEl().play(); state.playing = true; } catch (_) {}
        playBtn.textContent = state.playing ? '⏸' : '▶';
        if (state.playing && !waveRaf) waveAnimate();
        syncListening();
    }
    function pause() {
        origEl.pause(); remixEl.pause();
        state.playing = false;
        playBtn.textContent = '▶';
        if (waveRaf) { cancelAnimationFrame(waveRaf); waveRaf = 0; }
        redrawAll();
        syncListening();
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
        syncListening();
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
        setStatus(`Rendering ${fmtTime(state.loopStart)}–${fmtTime(state.loopEnd)}…`, 'busy');
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
            redrawAll();
            tabRemix.disabled = false;
            tabRemix.title = 'Hear the remix: every lane with its effects, summed (key: 2)';
            syncListening();   // the corner's Remix pill follows the monitor tab
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
        refreshRows();
        if (state.active === 'original' && !tabRemix.disabled) {
            setTrack('remix');
        }
        saveProject();
        scheduleRender();
    }

    // ── File adoption + upload ───────────────────────────────────────
    function showWorking() {
        if (state.loaded) return;
        state.loaded = true;
        dzSlot.appendChild(dropzone);
        dropzone.classList.add('dropzone-compact');
        emptyEl.hidden = true;
        workEl.hidden = false;
    }

    function adoptFile(file) {
        state.file = file;
        state.stemsReady = false;
        state.separating = false;
        state.pending = false;
        state.digest = null;
        state.cachedTiers = [];
        state.info = null;
        state.lanes = [];
        state.strips = {};
        state.lastRender = null;
        state.durationS = 0;
        state.loopMoved = false;
        state.loopStart = 0;
        pause();
        tabRemix.disabled = true;
        tabRemix.title = 'Separate the track first (key: 2)';
        setTrack('original');
        clearMixer();
        resultCard.hidden = true;
        metricsEl.hidden = true;
        if (stateStems) { stateStems.textContent = ''; delete stateStems.dataset.sticky; }
        if (state.sessionId) { dropSession(state.sessionId); state.sessionId = null; }
        if (state.origBlobUrl) URL.revokeObjectURL(state.origBlobUrl);
        state.origBlobUrl = URL.createObjectURL(file);
        origEl.src = state.origBlobUrl;
        origEl.addEventListener('loadedmetadata', () => {
            if (!state.durationS) {
                state.durationS = origEl.duration || 0;
                clampLoop();
                updateTime();
            }
        }, {once: true});
        selectedFile.hidden = false;
        selectedFile.textContent = `${file.name}  (${(file.size / 1048576).toFixed(1)} MB)`;
        selectedFile.title = selectedFile.textContent;
        dropzone.classList.add('has-file');
        pickBtn.textContent = 'Change…';
        showWorking();
        setStep(0);
        setStatus('Uploading…', 'busy');
        mixerFoot.textContent = 'Uploading the track…';
        if (chooseCards) chooseCards.innerHTML = '';
        syncDock();
        state.uploading = upload(file);
    }

    async function upload(file) {
        try {
            const r = await uploadFile(file);
            if (state.file !== file) return;      // superseded by a newer drop
            state.sessionId = r.session_id;
            state.durationS = r.duration_s || state.durationS;
            state.digest = r.digest || null;
            state.cachedTiers = Array.isArray(r.stems_tiers) ? r.stems_tiers : [];
            clampLoop();
            updateTime();
            document.dispatchEvent(new CustomEvent('shimmer:uploaded', { detail: {
                name: file.name, size: file.size, digest: state.digest,
                stems_tiers: state.cachedTiers,
            } }));
            let restored = false;
            state.projectTier = null;
            if (r.project && r.project.remix) {
                restored = restoreProject(r.project.remix);
                if (typeof r.project.remix.tier === 'string') state.projectTier = r.project.remix.tier;
            }
            fillTierSelect();
            // Stage 2 is the user's call: the cards say which splits are
            // cached (instant) and which download first; nothing runs
            // until one is clicked.
            setStep(1);
            buildChooser();
            syncDock();
            const cachedNote = state.cachedTiers.length
                ? ` · ${state.cachedTiers.map(k => (tierByKey()[k] || {}).label || k).join(' and ')} cached, instant`
                : '';
            setStatus((restored ? 'Previous mix restored · ' : 'Ready · ') + 'pick how many stems' + cachedNote);
            mixerFoot.textContent = `${fmtTime(state.durationS)} track` + cachedNote +
                (restored ? ' · your previous mix comes back with the stems' : '');
        } catch (e) {
            if (state.file !== file) return;
            setStatus(`Upload failed: ${e.message}`, 'error');
            mixerFoot.textContent = `Upload failed: ${e.message}`;
        } finally {
            state.uploading = null;
        }
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
    // The whole window is a drop target while the Remix tab is up
    // (dropzone drops stop propagation above).
    window.addEventListener('drop', (e) => {
        const panel = document.getElementById('tab-remix');
        if (!panel || !panel.classList.contains('active')) return;
        e.preventDefault();
        if (e.dataTransfer && e.dataTransfer.files[0]) adoptFile(e.dataTransfer.files[0]);
    });

    // ── Separation ───────────────────────────────────────────────────
    async function separate() {
        if (!state.file || state.separating) return;
        if (state.uploading) { try { await state.uploading; } catch (_) {} }
        if (!state.sessionId) return;
        const tier = tierByKey()[tierSel.value] || { key: tierSel.value, label: tierSel.value, stems: 4 };
        const cached = state.cachedTiers.includes(tier.key);
        state.separating = true;
        pause();
        setStep(1);
        syncDock();
        // Engine setup only runs on a first-ever separation; the Best
        // model's own download shows inside Separate.
        const planned = new Set(['separate', 'load', 'null']);
        if (state.engine && (!state.engine.installed || state.engine.ready === false)) planned.add('setup');
        processModal.open({
            title: cached ? 'Loading cached stems' : `Separating stems · ${tier.label}`,
            phases: SEP_PHASES,
            planned,
            stage: cached ? 'Reading the cached stems…' : 'Starting the separation engine…',
            detail: tier.stems === 6 ? 'vocals · drums · bass · guitar · piano · other' : 'vocals · drums · bass · other',
            outLabel: `${tier.stems} stems`,
        });
        let modalOpen = true;
        try {
            const jobId = await postJob('/api/stems/separate', { session_id: state.sessionId, tier: tier.key });
            await followJob(jobId, { onMessage: (msg) => { if (msg.message) setStatus(msg.message, 'busy'); } });
            const res = await fetch(`/api/stems/info/${state.sessionId}`);
            if (!res.ok) throw new Error(await res.text() || 'Could not read the stems');
            const info = await res.json();
            processModal.finish();
            processModal.closeSoon(900);
            modalOpen = false;
            state.info = info;
            state.stemsReady = true;
            state.separating = false;
            if (!state.cachedTiers.includes(tier.key)) state.cachedTiers.push(tier.key);
            if (state.engine) {
                const t = (state.engine.tiers || []).find(x => x.key === tier.key);
                if (t) t.downloaded = true;
            }
            buildMixer(info);
            // Park the loop on the busiest section (every stem playing) the
            // first time; later separations keep the user's loop.
            if (Number.isFinite(info.suggested_loop_s) && !state.loopMoved) {
                state.loopStart = info.suggested_loop_s;
                state.loopMoved = true;
                clampLoop();
                origEl.currentTime = state.loopStart;
                updateTime();
            }
            setStep(2);
            syncDock();
            setStatus(`Stems ready · loop parked on the busiest section (${fmtTime(state.loopStart)}–${fmtTime(state.loopEnd)})`, 'live');
            document.dispatchEvent(new CustomEvent('shimmer:stems-ready', { detail: {
                digest: state.digest, tier: tier.key,
            } }));
            doRender();
        } catch (e) {
            state.separating = false;
            setStatus(`Separation failed: ${e.message}`, 'error');
            setStep(state.stemsReady ? 2 : 0);
            syncDock();
            if (modalOpen) processModal.fail(e.message);
        }
    }
    sepBtn.addEventListener('click', separate);

    // Mastering changes are audible in the loop — treat them like any
    // other edit (auto-switch to the Remix track, save, re-render).
    masterEnabled.addEventListener('change', () => {
        updateMasterUI();
        onEdit();
    });
    for (const sel of [masterTarget, masterIntensity, masterTilt]) {
        sel.addEventListener('change', () => { onEdit(); syncInspectorStates(); });
    }
    // Cleanup and format only matter at export — persist, no re-render.
    cleanupSel.addEventListener('change', () => { saveProject(); syncInspectorStates(); });
    formatSel.addEventListener('change', () => { saveProject(); syncInspectorStates(); });

    // ── Full render + download ───────────────────────────────────────
    function chip(text, cls = '') {
        const span = document.createElement('span');
        span.className = 'metric-chip' + (cls ? ` ${cls}` : '');
        span.textContent = text;
        return span;
    }

    function metricRow(label, chips) {
        const row = el('div', 'metric-row');
        row.appendChild(el('span', 'metric-row-label', label));
        row.append(...chips);
        return row;
    }

    function renderReport(m, format) {
        doneChips.innerHTML = '';
        metricsEl.innerHTML = '';
        const banner = [];
        const loud = [], clean = [], job = [];
        const c = (m && m.cleaning) || {};
        if (c.enabled && c.label) {
            const conf = Number.isFinite(c.detected_confidence)
                ? ` (${Math.round(c.detected_confidence * 100)}%)` : '';
            const str = Number.isFinite(c.detected_strength)
                && Math.abs(c.detected_strength - 1) > 1e-6
                ? ` @ ${Math.round(c.detected_strength * 100)}%` : '';
            banner.push(`Cleaned · ${c.label}`);
            clean.push(chip(`${c.label}${conf}${str}`));
            if (Number.isFinite(c.repair_notches) && c.repair_notches > 0) {
                clean.push(chip(`${c.repair_notches} fixed tones notched`));
            }
        } else if (m) {
            clean.push(chip('No cleanup'));
        }
        const mast = (m && m.mastering) || {};
        if (mast.enabled) {
            const b = mast.before || {}, a = mast.after || {};
            if (Number.isFinite(b.lufs_i) && Number.isFinite(a.lufs_i)) {
                banner.push(`${a.lufs_i.toFixed(1)} LUFS`);
                loud.push(chip(`${b.lufs_i.toFixed(1)} → ${a.lufs_i.toFixed(1)} LUFS` +
                    (Number.isFinite(mast.target_lufs) ? ` (target ${mast.target_lufs.toFixed(0)})` : '')));
            }
            if (Number.isFinite(a.true_peak_dbtp)) loud.push(chip(`True peak ${a.true_peak_dbtp.toFixed(1)} dBTP`));
            const gr = (mast.limiter || {}).max_gain_reduction_db;
            if (Number.isFinite(gr)) {
                loud.push(chip(Math.abs(gr) < 0.05 ? 'Limiter: no gain reduction' : `Limiter ${Math.abs(gr).toFixed(1)} dB max GR`));
            }
        } else {
            banner.push('Not mastered');
            const lufs = ((m && m.loudness) || {}).output_lufs_i;
            if (Number.isFinite(lufs)) loud.push(chip(`${lufs.toFixed(1)} LUFS`));
        }
        const lanes = state.lanes.filter(l => !effectiveMute(l.key)).length;
        job.push(chip(`${lanes} of ${state.lanes.length} lanes`));
        if (m && Number.isFinite(m.duration_s)) job.push(chip(fmtTime(m.duration_s)));
        job.push(chip(format.toUpperCase()));
        banner.push(format.toUpperCase());
        for (const t of banner) doneChips.appendChild(Object.assign(el('span', 'done-chip'), { textContent: t }));
        if (loud.length) metricsEl.appendChild(metricRow('Loudness', loud));
        if (clean.length) metricsEl.appendChild(metricRow('Cleaning', clean));
        if (job.length) metricsEl.appendChild(metricRow('Job', job));
        metricsEl.hidden = false;
    }

    function showResult(jobId, format) {
        downloadLink.href = resultUrl(jobId, 'processed');
        downloadLink.textContent = `Download ${format.toUpperCase()}`;
        resultCard.hidden = false;
        doneBanner.classList.remove('flash');
        void doneBanner.offsetWidth;
        doneBanner.classList.add('flash');
        resultCard.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }

    downloadLink.addEventListener('click', async (e) => {
        const href = downloadLink.getAttribute('href');
        if (!href) return;
        e.preventDefault();
        try { await downloadResult(href); }
        catch (err) { metricsEl.hidden = false; metricsEl.prepend(el('div', 'metric-row', err.message)); }
    });

    renderBtn.addEventListener('click', async () => {
        if (!state.stemsReady) return;
        renderBtn.disabled = true;
        const mp = masteringPayload();
        const cleaning = cleanupSel.value;
        const format = formatSel.value;
        const planned = new Set(['mix', 'export', 'report']);
        if (cleaning !== 'off') planned.add('fixes');
        if (mp.enabled) { planned.add('tone'); planned.add('master'); }
        if (format === 'wav16') planned.add('rate');
        processModal.open({
            title: mp.enabled ? 'Rendering & mastering the remix' : 'Rendering the remix',
            phases: renderPhases(await loadRules()),
            planned,
            stage: 'Preparing…',
            detail: 'summing the lanes with their effects',
        });
        try {
            const jobId = await postJob('/api/remix/render', {
                session_id: state.sessionId,
                stems: stemsPayload(),
                output_format: format,
                mastering: mp,
                cleaning: {preset: cleaning},
            });
            await followJob(jobId);
            processModal.finish();
            processModal.closeSoon(900);
            state.lastRender = { jobId, format };
            let metrics = null;
            try { metrics = await fetchMetrics(jobId); } catch (_) {}
            // /api/metrics answers {status, metrics}; the report wants the inner object.
            renderReport(metrics && metrics.metrics ? metrics.metrics : metrics, format);
            showResult(jobId, format);
            try { await downloadResult(resultUrl(jobId, 'processed')); }
            catch (err) { metricsEl.hidden = false; metricsEl.prepend(el('div', 'metric-row', err.message)); }
        } catch (e) {
            processModal.fail(e.message);
            setStatus(`Render failed: ${e.message}`, 'error');
        } finally {
            renderBtn.disabled = !state.stemsReady;
        }
    });

    // ── Stems export (ZIP) ───────────────────────────────────────────
    async function exportStems(processed) {
        if (!state.stemsReady) return;
        exportDryBtn.disabled = exportMixedBtn.disabled = true;
        processModal.open({
            title: processed ? 'Exporting the stems with this mix' : 'Exporting the stems',
            phases: EXPORT_PHASES,
            planned: new Set(['mix', 'export']),
            stage: 'Preparing…',
            detail: '24-bit WAV · one file per lane',
            outLabel: 'ZIP',
        });
        try {
            const jobId = await postJob('/api/stems/export', {
                session_id: state.sessionId,
                processed,
                stems: stemsPayload(),
            });
            await followJob(jobId);
            processModal.finish();
            processModal.closeSoon(700);
            let n = state.lanes.length;
            try {
                const m = await fetchMetrics(jobId);
                if (m && m.metrics && Array.isArray(m.metrics.stems)) n = m.metrics.stems.length;
            } catch (_) {}
            if (stateStems) {
                stateStems.textContent = `${n} files · ${processed ? 'with this mix' : 'as separated'}`;
                stateStems.dataset.sticky = '1';
            }
            await downloadResult(resultUrl(jobId, 'processed'));
        } catch (e) {
            processModal.fail(e.message);
            if (stateStems) { stateStems.textContent = 'export failed'; stateStems.dataset.sticky = '1'; }
            setStatus(`Stems export failed: ${e.message}`, 'error');
        } finally {
            exportDryBtn.disabled = exportMixedBtn.disabled = !state.stemsReady;
        }
    }
    exportDryBtn.addEventListener('click', () => exportStems(false));
    exportMixedBtn.addEventListener('click', () => exportStems(true));

    window.addEventListener('beforeunload', () => {
        if (state.sessionId) dropSession(state.sessionId);
    });

    syncDock();
    loadEngine();
}
