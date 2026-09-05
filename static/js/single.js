// single.js — Orchestrates the Single-File tab.

import { renderControls } from './controls.js';
import { initPresetSelect, presetToSliderValues, runAutoDetect } from './preset.js';
import {
    submitProcess, openSSE, fetchMetrics, resultUrl,
    uploadFile, dropSession, renderPreview,
} from './api.js';
import { makeSettingsSaver, loadSettings } from './settings.js';
import { openHelp } from './help.js';
import { createUnifiedPlayer, fmtTime } from './visualizer.js';
import { initEqPanel } from './eq.js';
import { initTrim } from './trim.js';


const PREVIEW_DEBOUNCE_MS = 250;
const PREVIEW_CACHE_MAX = 20;


export async function initSingleTab() {
    const $ = (id) => document.getElementById(id);

    const dropzone     = $('dropzone');
    const fileInput    = $('file-input');
    const pickBtn      = $('pick-file-btn');
    const selectedFile = $('selected-file');
    const presetSelect = $('preset-select');
    const presetDesc   = $('preset-desc');
    const autoBtn      = $('analyze-btn');
    const masterEnabled = $('master-enabled');
    const masterTarget  = $('master-target');
    const masterIntensity = $('master-intensity');
    const masterTilt = $('master-tilt');
    const masteringReadout = $('mastering-readout');
    const preserveVolCard = $('preserve-vol-card');
    const abLoudnessMatch = $('ab-loudness-match');
    const stepUpload = $('step-upload');
    const stepAnalyze = $('step-analyze');
    const stepProcess = $('step-process');
    const slidersHost  = $('sliders-host');
    const preserveVol  = $('preserve-vol');
    const trimSilence  = $('trim-silence');
    const rememberSettings = $('remember-settings');
    const outputFormat = $('output-format');
    const processBtn   = $('process-btn');
    const progressEl   = $('progress');
    const strengthEl   = $('preset-strength');
    const strengthValEl = $('preset-strength-value');

    const audioOrig = $('audio-original');
    const audioProc = $('audio-processed');
    const audioDiff = $('audio-diff');
    const metricsBox = $('metrics-box');
    // Renders a slim strip of stat chips. Accepts a string or an array
    // of strings; empty input hides the strip.
    function setMetrics(items) {
        metricsBox.innerHTML = '';
        const arr = (items == null ? [] :
            (Array.isArray(items) ? items : [String(items)]))
            .map(s => String(s).trim())
            .filter(s => s.length > 0);
        for (const text of arr) {
            const chip = document.createElement('span');
            chip.className = 'metric-chip';
            if (/^Error\b/i.test(text)) chip.classList.add('err');
            chip.textContent = text;
            chip.title = text;
            metricsBox.appendChild(chip);
        }
        metricsBox.hidden = arr.length === 0;
    }
    const autoDetectResults = $('auto-detect-results');
    const downloadLink = $('download-link');
    const doneBanner = $('done-banner');
    const doneChips = $('done-chips');

    // ── Advanced controls drawer ─────────────────────────────────────
    const advOpenBtn  = $('advanced-open-btn');
    const advDrawer   = $('advanced-drawer');
    const advBackdrop = $('advanced-drawer-backdrop');
    const advCloseBtn = $('advanced-close');

    function openAdvancedDrawer() {
        advDrawer.hidden = false;
        advBackdrop.hidden = false;
    }
    function closeAdvancedDrawer() {
        advDrawer.hidden = true;
        advBackdrop.hidden = true;
    }
    advOpenBtn.addEventListener('click', openAdvancedDrawer);
    advCloseBtn.addEventListener('click', closeAdvancedDrawer);
    advBackdrop.addEventListener('click', closeAdvancedDrawer);
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && !advDrawer.hidden) closeAdvancedDrawer();
    });

    // ── Preset description: collapsed to 2 lines, click to expand ────
    presetDesc.addEventListener('click', () => {
        presetDesc.classList.toggle('expanded');
    });
    document.addEventListener('click', (e) => {
        if (!presetDesc.contains(e.target)) {
            presetDesc.classList.remove('expanded');
        }
    });

    const previewToggle  = $('preview-toggle');
    const previewControls = $('preview-controls');
    const previewWindow  = $('preview-window');
    const previewHereBtn = $('preview-here-btn');
    const previewStatus  = $('preview-status');
    const previewExplainer = $('preview-explainer');
    const previewToggleRow = $('preview-toggle-row');

    // One-time discoverability nudge: the first time the user edits a
    // setting with Live off, point them at the toggle. Persisted so it
    // never fires again on any later visit.
    const NUDGE_KEY = 'shimmer.previewNudgeSeen';
    let previewNudged = false;  // this session, avoid repeat pulses
    const nudgeSeen = () => {
        try { return !!localStorage.getItem(NUDGE_KEY); } catch (_) { return false; }
    };
    const markNudgeSeen = () => {
        try { localStorage.setItem(NUDGE_KEY, '1'); } catch (_) {}
    };
    const DEFAULT_EXPLAINER =
        'Turn on Live to loop the worst section and hear edits instantly.';

    // Explainer shows only while Live is off; when Live is on the status
    // pill (rendering / live / error) carries the state instead.
    function showPreviewExplainer(text, nudge) {
        if (!previewExplainer) return;
        previewExplainer.textContent = text;
        previewExplainer.classList.toggle('nudge', !!nudge);
        previewExplainer.hidden = false;
    }
    function syncPreviewExplainer() {
        if (!previewExplainer) return;
        if (previewState.active) {
            previewExplainer.hidden = true;          // status pill owns the row
        } else if (!previewExplainer.classList.contains('nudge')) {
            showPreviewExplainer(DEFAULT_EXPLAINER, false);
        } else {
            previewExplainer.hidden = false;         // keep the active nudge
        }
    }

    function maybePreviewNudge() {
        if (!currentFile || previewNudged || nudgeSeen()) return;
        previewNudged = true;
        markNudgeSeen();
        showPreviewExplainer('Hear that change instantly — turn on Live ↑', true);
        if (previewToggleRow) {
            previewToggleRow.classList.remove('nudge-pulse');
            void previewToggleRow.offsetWidth;       // restart the animation
            previewToggleRow.classList.add('nudge-pulse');
        }
    }

    let lastAnalysis = null;
    let lastFollowUp = null; // Analyze's second-pass suggestion, if any
    // Static-repair plan for the current file: the generator's fixed
    // tonal lines the server found, each with an `on` flag the user can
    // untick. Sent with every preview / process request; null = let the
    // server scan and decide.
    let lastRepair = null;
    let lastEdges = null;    // head/tail scan from the last upload
    let lastMasteringReport = null;
    // Match deltas (processed LUFS minus original LUFS). Preview uses
    // per-render slice loudness; full uses whole-file metrics. `null`
    // means "no data yet for this state".
    let fullMatchDb = null;
    let previewMatchDb = null;
    // Analyze timeline (intensity bins over the whole file), kept so the
    // preview window can auto-anchor on the artifact-hot region.
    let lastTimeline = null;
    let player = null;

    const saveSettings = makeSettingsSaver();

    // ── Preview state ────────────────────────────────────────────────
    // Held across the entire single-tab lifetime; reset on file change.
    const previewState = {
        sessionId: null,
        durationS: 0,
        active: false,
        anchorS: 0,        // start of the loop window in source time
        anchorMode: 'auto',  // 'auto' = artifact-hot region; 'manual' = playhead
        windowS: 20,
        renderInflight: null,  // AbortController for the in-flight render
        renderPending: false,
        debounceTimer: null,
        originalBlobUrl: null,
        savedTime: 0,
    };

    // Decoded render cache keyed by (window + params). Hits skip the
    // network and swap buffers instantly.
    const previewCache = new Map();  // key -> {processedBuf, removedBuf, meta}

    function currentStrength() {
        const v = parseFloat(strengthEl.value);
        return Number.isFinite(v) ? v : 1.0;
    }

    function renderStrengthBadge() {
        const v = currentStrength();
        strengthValEl.textContent = `${Math.round(v * 100)}%`;
    }
    renderStrengthBadge();

    const {byName, defaultName} = await initPresetSelect(presetSelect, {
        descEl: presetDesc,
        onChange: (preset) => {
            controls.setValues(presetToSliderValues(preset, currentStrength()));
            pushSettings();
            schedulePreviewRender();
        },
    });

    const controls = renderControls(
        slidersHost,
        () => { pushSettings(); schedulePreviewRender(); },
        (specKey) => openHelp('controls', specKey),
    );

    const eqPanel = initEqPanel($('eq-card'), {
        onChange: () => { pushSettings(); schedulePreviewRender(); },
        getSpectrum: () => (lastAnalysis && lastAnalysis.spectrum) || null,
    });

    // Top & tail. Detection is reported here, never applied on its own —
    // the trim only reaches the export because the user armed it.
    const trimPanel = initTrim({});

    player = createUnifiedPlayer({
        els: { original: audioOrig, processed: audioProc, removed: audioDiff },
        canvas: $('player-canvas'),
        playBtn: $('player-play'),
        timeLabel: $('player-time'),
        tabsHost: $('track-tabs'),
        modeWaveBtn: $('viz-mode-wave'),
        modeOverlayBtn: $('viz-mode-overlay'),
        modeSpecBtn: $('viz-mode-spec'),
        spectrumCanvas: $('spectrum-live'),
        metersHost: $('player-meters'),
        lufsFillEl: $('viz-lufs-fill'),
        lufsTargetEl: $('viz-lufs-target'),
        getShimmerBand: () => {
            const v = controls.getValues();
            return { lo: v.start_hz || 5100, hi: v.end_hz || 7200 };
        },
    });
    player.attachKeyboard();

    const abMatchNote = $('ab-match-note');

    function applyLoudnessMatch() {
        // Delta = processed LUFS minus original LUFS, from the state we
        // are actually auditioning: per-render slice loudness while the
        // preview loop is live, whole-file metrics after a full run.
        const d = previewState.active ? previewMatchDb : fullMatchDb;
        // Clamp the match attenuation. A short preview slice can report a
        // LUFS delta far larger than the whole track's — e.g. when Analyze
        // re-anchors the loop onto an atypically quiet or loud region — which
        // would drop the monitored track to a fraction of its level ("volume
        // way down after applying a match"). Loudness differences that matter
        // for A/B sit within a few dB; past ~6 dB the slice estimate is
        // unreliable and a near-silent track defeats the point of matching.
        // Cap so playback is never attenuated by more than half.
        const MATCH_MAX_DB = 6;
        const raw = d == null ? 0 : d;
        const dd = Math.max(-MATCH_MAX_DB, Math.min(MATCH_MAX_DB, raw));
        // Say what the match is doing. A silent 6 dB cut on the Processed
        // monitor reads as "processed got quieter and won't come back".
        if (abMatchNote) {
            let txt = '';
            if (abLoudnessMatch.checked) {
                if (d == null) {
                    txt = '(waiting for render)';
                } else if (Math.abs(dd) >= 0.1) {
                    const side = dd > 0 ? 'Processed' : 'Original';
                    txt = `${side} −${Math.abs(dd).toFixed(1)} dB`;
                    if (Math.abs(raw) > MATCH_MAX_DB + 1e-6) txt += ' (capped)';
                }
            }
            abMatchNote.textContent = txt;
            abMatchNote.title = txt
                ? 'Monitoring gain only — the louder side is turned down so ' +
                  'you compare sound, not level. Never applied to your export.'
                : '';
        }
        // Attenuate whichever side is louder so the comparison is fair.
        // Removed is an audition track and stays out of the match.
        player.setLoudnessMatch(abLoudnessMatch.checked, {
            original:  dd < 0 ? dd : 0,
            processed: dd > 0 ? -dd : 0,
            removed:   0,
        });
    }

    // Defaults first; restore only when the user opted in last time.
    controls.setValues(presetToSliderValues(
        byName.get(defaultName), currentStrength()));

    const saved = await loadSettings();
    const shouldRestore = !!(saved && saved.remember_settings);
    if (rememberSettings) rememberSettings.checked = shouldRestore;
    if (shouldRestore) {
        if (typeof saved.preset_strength === 'number') {
            strengthEl.value = String(saved.preset_strength);
            renderStrengthBadge();
        }
        if (saved.preset && byName.has(saved.preset)) {
            presetSelect.value = saved.preset;
            presetSelect.dispatchEvent(new Event('change'));
        }
        if (saved.sliders) controls.setValues(saved.sliders);
        if (typeof saved.preserve_volume === 'boolean') {
            preserveVol.checked = saved.preserve_volume;
        }
        if (typeof saved.trim_silence === 'boolean') {
            trimSilence.checked = saved.trim_silence;
        }
        if (saved.output_format) outputFormat.value = saved.output_format;
        if (typeof saved.ab_loudness_match === 'boolean') {
            abLoudnessMatch.checked = saved.ab_loudness_match;
        }
        if (saved.eq) eqPanel.setPayload(saved.eq);
        if (saved.mastering) {
            if (typeof saved.mastering.enabled === 'boolean') {
                masterEnabled.checked = saved.mastering.enabled;
            }
            if (saved.mastering.target) masterTarget.value = saved.mastering.target;
            if (saved.mastering.intensity) masterIntensity.value = saved.mastering.intensity;
            if (saved.mastering.tilt) masterTilt.value = saved.mastering.tilt;
        }
    }

    updateMasteringUI();
    applyLoudnessMatch();

    // Live strength re-scaling: rebuild visible slider values from the
    // current preset every time the strength slider moves so the user
    // sees the effect.  The hidden keys (ceilings, FlickerTamer depth,
    // iterations, etc.) are scaled server-side by apply_preset_strength.
    strengthEl.addEventListener('input', () => {
        renderStrengthBadge();
        const preset = byName.get(presetSelect.value);
        if (preset) {
            controls.setValues(presetToSliderValues(preset, currentStrength()));
        }
        pushSettings();
        schedulePreviewRender();
    });

    function masteringPayload() {
        return {
            enabled: masterEnabled.checked,
            target: masterTarget.value,
            intensity: masterIntensity.value,
            tilt: masterTilt.value,
        };
    }

    function updateMasteringUI() {
        const on = masterEnabled.checked;
        $('mastering-options').style.opacity = on ? '1' : '0.5';
        preserveVolCard.hidden = on;
        if (on) preserveVol.checked = false;
    }

    function setWizardStep(step) {
        [stepUpload, stepAnalyze, stepProcess].forEach((el, i) => {
            if (el) el.classList.toggle('active', i <= step);
            if (el) el.classList.toggle('done', i < step);
        });
    }

    function renderAnalysisReadout(analysis) {
        if (!analysis || !analysis.loudness) return;
        const l = analysis.loudness;
        masteringReadout.hidden = false;
        masteringReadout.textContent =
            `Input: ${l.lufs_i?.toFixed?.(1) ?? '?'} LUFS · ` +
            `TP ${l.true_peak_dbtp?.toFixed?.(1) ?? '?'} dBTP · ` +
            `LRA ${l.lra?.toFixed?.(1) ?? '?'}`;
    }

    masterEnabled.addEventListener('change', () => {
        updateMasteringUI();
        pushSettings();
        schedulePreviewRender();
    });
    masterTarget.addEventListener('change', () => {
        player.setTargetLufs(
            { streaming: -14, loud: -11, cd: -9 }[masterTarget.value] || -14);
        pushSettings();
        schedulePreviewRender();
    });
    masterIntensity.addEventListener('change', () => {
        pushSettings();
        schedulePreviewRender();
    });
    masterTilt.addEventListener('change', () => {
        pushSettings();
        schedulePreviewRender();
    });
    abLoudnessMatch.addEventListener('change', () => {
        applyLoudnessMatch();
        pushSettings();
    });
    let currentFile = null;

    function hideDoneBanner() {
        doneBanner.hidden = true;
        doneBanner.classList.remove('flash');
        processBtn.classList.remove('btn-secondary');
        processBtn.classList.add('btn-primary');
    }

    function showDoneBanner(chips) {
        doneChips.innerHTML = '';
        for (const c of chips) {
            const span = document.createElement('span');
            span.className = 'done-chip';
            span.textContent = c;
            doneChips.appendChild(span);
        }
        doneBanner.hidden = false;
        // Restart the flash animation.
        doneBanner.classList.remove('flash');
        void doneBanner.offsetWidth;
        doneBanner.classList.add('flash');
        // Shift visual priority: Download becomes the primary action.
        processBtn.classList.remove('btn-primary');
        processBtn.classList.add('btn-secondary');
    }

    function adoptFile(file) {
        currentFile = file;
        selectedFile.hidden = false;
        selectedFile.textContent = `${file.name}  (${(file.size/1048576).toFixed(1)} MB)`;
        selectedFile.title = selectedFile.textContent;
        dropzone.classList.add('has-file');
        pickBtn.textContent = 'Change…';
        processBtn.disabled = false;
        setWizardStep(0);
        lastAnalysis = null;
        lastTimeline = null;
        fullMatchDb = null;
        previewMatchDb = null;
        lastFollowUp = null;
        lastRepair = null;
        renderRepairList();
        previewState.anchorMode = 'auto';
        previewCache.clear();
        masteringReadout.hidden = true;
        setMetrics('');
        hideDoneBanner();

        // Tear down any prior preview session and reset preview UI.
        teardownPreviewSession();
        if (previewToggle.checked) previewToggle.checked = false;
        applyPreviewToggle(false);

        if (previewState.originalBlobUrl) {
            try { URL.revokeObjectURL(previewState.originalBlobUrl); } catch (_) {}
        }
        previewState.originalBlobUrl = URL.createObjectURL(file);
        player.resetTracks();
        player.setSource('original', previewState.originalBlobUrl);
        setPreviewStatus('Tick "Live preview" to loop edits around the playhead.');

        // Scan the edges now rather than when preview is first switched on.
        // A head glitch has to surface while the user is still deciding what
        // to do with the track, not after they have exported it.
        trimPanel?.reset(previewState.originalBlobUrl);
        ensurePreviewSession({quiet: true}).then((sid) => {
            if (currentFile !== file) return;      // superseded by a newer drop
            if (sid) trimPanel?.setSession(sid, previewState.durationS, lastEdges);
            else trimPanel?.setScanFailed();
        });
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

    // The whole window is a drop target once the dropzone has collapsed
    // to its compact chip. (Dropzone drops stop propagation above.)
    window.addEventListener('dragover', (e) => e.preventDefault());
    window.addEventListener('drop', (e) => {
        e.preventDefault();
        const singleActive = document.getElementById('tab-single')
            .classList.contains('active');
        if (singleActive && e.dataTransfer && e.dataTransfer.files[0]) {
            adoptFile(e.dataTransfer.files[0]);
        }
    });

    // ── Auto-detect ──────────────────────────────────────────────────
    const labelOf = (key) => {
        const p = byName.get(key);
        return (p && p.label) || key;
    };

    // Apply a detected preset together with the strength the analysis
    // verified for it.  Strength is set first so the preset's change
    // handler builds the visible sliders at that strength; the server
    // scales the hidden keys from the same `preset_strength` value.
    function applyDetectedPreset(presetName, strength) {
        if (!presetName || !byName.has(presetName)) return;
        if (Number.isFinite(strength)) {
            const s = Math.max(0, Math.min(2, strength));
            strengthEl.value = String(s);
            renderStrengthBadge();
        }
        presetSelect.value = presetName;
        presetSelect.dispatchEvent(new Event('change'));
    }

    // ── Static repair (fixed lines) ─────────────────────────────────────
    const repairListEl = $('repair-list');

    function setRepairPlan(plan) {
        const notches = Array.isArray(plan && plan.notches) ? plan.notches : [];
        // Keep the user's unticks when the same line comes back from a
        // later scan (upload, then Analyze).
        const prev = new Map((lastRepair ? lastRepair.notches : [])
            .map(n => [Math.round(n.hz), n.on]));
        lastRepair = {
            enabled: true,
            notches: notches.map(n => ({
                hz: n.hz, depth_db: n.depth_db, bw_hz: n.bw_hz, kind: n.kind || 'line',
                excess_db: n.excess_db, duty: n.duty,
                on: prev.has(Math.round(n.hz)) ? prev.get(Math.round(n.hz)) : true,
            })),
        };
        renderRepairList();
    }

    // What the server should notch: an explicit list once we have one
    // (so unticks are honoured), otherwise null = scan and decide.
    function repairPayload() {
        if (!lastRepair) return { enabled: true, notches: null };
        return {
            enabled: true,
            notches: lastRepair.notches.filter(n => n.on).map(n => ({
                hz: n.hz, depth_db: n.depth_db, bw_hz: n.bw_hz, kind: n.kind,
                excess_db: n.excess_db, duty: n.duty,
            })),
        };
    }

    function renderRepairList() {
        if (!repairListEl) return;
        repairListEl.innerHTML = '';
        if (!lastRepair) { repairListEl.hidden = true; return; }
        repairListEl.hidden = false;
        const head = document.createElement('div');
        head.className = 'ad-cards-label';
        head.textContent = lastRepair.notches.length
            ? 'Fixed tones notched first in the chain'
            : 'Fixed tones';
        repairListEl.appendChild(head);
        if (!lastRepair.notches.length) {
            const e = document.createElement('div');
            e.className = 'repair-empty';
            e.textContent = 'No fixed generator tones found in this file.';
            repairListEl.appendChild(e);
            return;
        }
        lastRepair.notches.forEach((n, i) => {
            const row = document.createElement('label');
            row.className = 'repair-row' + (n.on ? '' : ' off');
            const cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.checked = !!n.on;
            cb.title = 'Untick to keep this tone';
            cb.addEventListener('change', () => {
                lastRepair.notches[i].on = cb.checked;
                row.classList.toggle('off', !cb.checked);
                pushSettings();
                schedulePreviewRender();
            });
            const hz = document.createElement('span');
            hz.className = 'r-hz';
            hz.textContent = `${(n.hz / 1000).toFixed(2)} kHz`;
            const depth = document.createElement('span');
            depth.className = 'r-depth';
            depth.textContent = `−${Math.round(n.depth_db)} dB`;
            const kind = document.createElement('span');
            kind.className = 'r-kind';
            kind.textContent = n.kind === 'comb' ? 'comb tooth' : 'line';
            row.append(cb, hz, depth, kind);
            repairListEl.appendChild(row);
        });
    }

    // Plain-language advice shown whenever Analyze suggests a second pass
    // and mastering is on. Mastering limits the sound and sets its
    // loudness; cleaning a mastered file and mastering it again hurts it.
    function secondPassMasteringTip() {
        return 'Mastering is on. Master only once, at the end. ' +
            'Turn mastering off for this pass, keep Preserve volume on, ' +
            'then master on the last pass.';
    }

    function showAutoDetectError(msg) {
        autoDetectResults.hidden = false;
        autoDetectResults.innerHTML = '';
        const err = document.createElement('div');
        err.className = 'ad-error';
        err.textContent = msg;
        autoDetectResults.appendChild(err);
    }

    function renderAutoDetect(r) {
        autoDetectResults.hidden = false;
        autoDetectResults.innerHTML = '';

        const ranked = Array.isArray(r.ranked) ? r.ranked : [];
        if (ranked.length === 0) {
            const note = document.createElement('div');
            note.className = 'ad-reason';
            note.textContent = 'No artifact detected; safe defaults will do.';
            autoDetectResults.appendChild(note);
            return;
        }

        const heading = document.createElement('div');
        heading.className = 'ad-cards-label';
        heading.textContent = ranked.length > 1 ? 'Best matches' : 'Best match';
        autoDetectResults.appendChild(heading);

        const list = document.createElement('div');
        list.className = 'ad-cards';
        const cards = [];

        const setActive = (idx) => {
            cards.forEach((c, i) => {
                c.card.classList.toggle('active', i === idx);
                c.apply.textContent = i === idx ? 'Applied' : 'Apply';
                c.apply.disabled = i === idx;
            });
        };

        ranked.slice(0, 6).forEach((entry, i) => {
            const card = document.createElement('div');
            card.className = 'ad-card' + (i >= 3 ? ' ad-card-more' : '');

            const head = document.createElement('div');
            head.className = 'ad-card-head';

            const rank = document.createElement('span');
            rank.className = 'ad-card-rank';
            rank.textContent = `${i + 1}`;

            const name = document.createElement('div');
            name.className = 'ad-name';
            name.textContent = entry.label || labelOf(entry.name);
            name.title = name.textContent;

            const confWrap = document.createElement('div');
            confWrap.className = 'ad-confidence-wrap';
            const conf = document.createElement('div');
            conf.className = 'ad-confidence';
            const fill = document.createElement('div');
            fill.className = 'ad-confidence-fill';
            const pct = Math.round((entry.confidence || 0) * 100);
            fill.style.width = `${pct}%`;
            conf.appendChild(fill);
            const pctText = document.createElement('div');
            pctText.className = 'ad-confidence-pct';
            pctText.textContent = `${pct}%`;
            confWrap.appendChild(conf);
            confWrap.appendChild(pctText);

            const strengthVal = Number.isFinite(entry.strength) ? entry.strength : 1.0;
            const strengthChip = document.createElement('span');
            strengthChip.className = 'ad-strength'
                + (strengthVal > 1.01 ? ' boost' : strengthVal < 0.99 ? ' gentle' : '');
            strengthChip.textContent = `${Math.round(strengthVal * 100)}%`;
            strengthChip.title = 'Recommended preset strength for this match';

            const apply = document.createElement('button');
            apply.type = 'button';
            apply.className = 'btn btn-ghost ad-apply-btn';
            apply.addEventListener('click', () => {
                applyDetectedPreset(entry.name, strengthVal);
                setActive(i);
            });

            head.appendChild(rank);
            head.appendChild(name);
            head.appendChild(confWrap);
            head.appendChild(strengthChip);
            head.appendChild(apply);
            card.appendChild(head);

            if (entry.reason) {
                const reason = document.createElement('div');
                reason.className = 'ad-card-reason';
                reason.textContent = entry.reason;
                reason.title = entry.reason;
                card.appendChild(reason);
            }

            cards.push({card, apply});
            list.appendChild(card);
        });

        autoDetectResults.appendChild(list);
        setActive(0);  // top pick is auto-applied by the caller

        if (r.follow_up && r.follow_up.name) {
            const fu = document.createElement('div');
            fu.className = 'ad-followup';
            const b = document.createElement('b');
            b.textContent = `Second pass: ${r.follow_up.label || labelOf(r.follow_up.name)}. `;
            fu.appendChild(b);
            fu.appendChild(document.createTextNode(r.follow_up.reason || ''));
            if (masterEnabled.checked) {
                const tip = document.createElement('div');
                tip.className = 'ad-followup-tip';
                tip.textContent = secondPassMasteringTip();
                fu.appendChild(tip);
            }
            autoDetectResults.appendChild(fu);
        }
        (Array.isArray(r.notes) ? r.notes : []).forEach((text) => {
            const n = document.createElement('div');
            n.className = 'ad-note';
            n.textContent = text;
            autoDetectResults.appendChild(n);
        });

        const tl = r.timeline && Array.isArray(r.timeline.intensity)
            ? r.timeline.intensity : [];
        if (tl.length > 0) {
            const tlEl = document.createElement('div');
            tlEl.className = 'ad-timeline';
            for (const v of tl) {
                const bar = document.createElement('div');
                bar.className = 'ad-timeline-bar';
                if (v >= 0.4) bar.classList.add('hot');
                const h = Math.max(2, Math.round(v * 24)); // px
                bar.style.height = `${h}px`;
                bar.title = `intensity ${(v * 100).toFixed(0)}%`;
                tlEl.appendChild(bar);
            }
            autoDetectResults.appendChild(tlEl);
        }
    }

    autoBtn.addEventListener('click', async () => {
        if (!currentFile) {
            showAutoDetectError('Select a file first.');
            return;
        }
        const originalLabel = autoBtn.textContent;
        autoBtn.textContent = 'Analyzing…';
        autoBtn.disabled = true;
        try {
            const r = await runAutoDetect(currentFile);
            lastFollowUp = (r.follow_up && r.follow_up.name) ? r.follow_up : null;
            if (r.repair_plan) setRepairPlan(r.repair_plan);
            applyDetectedPreset(r.preset, r.strength);
            renderAutoDetect(r);
            if (r.timeline && Array.isArray(r.timeline.intensity) &&
                r.timeline.intensity.length > 0) {
                lastTimeline = r.timeline.intensity;
                // Re-anchor a live loop onto the newly-found hot region.
                if (previewState.active && previewState.anchorMode === 'auto') {
                    schedulePreviewRender();
                }
            }
            if (r.analysis) {
                lastAnalysis = r.analysis;
                renderAnalysisReadout(r.analysis);
                eqPanel.refreshSpectrum();
            }
            setWizardStep(1);
        } catch (e) {
            showAutoDetectError(`Analyze failed: ${e.message}`);
        } finally {
            autoBtn.textContent = originalLabel;
            autoBtn.disabled = false;
        }
    });

    // ── Persistence wiring ────────────────────────────────────────────
    // Always write the current UI (Batch reuses EQ in-session). Restore
    // on next visit only when remember_settings is true.
    // Signal Chain bridge: the chain view asks for the exact state a
    // Clean & Master click would send, so the server renders the chain
    // from real Params instead of a hand-written list.
    window.shimmerChainState = () => {
        const t = trimPanel ? trimPanel.getTrim() : null;
        return {
            preset: presetSelect.value,
            preset_strength: currentStrength(),
            overrides: controls.getValues(),
            mastering: masteringPayload(),
            eq: eqPanel.getPayload(),
            preserve_volume: preserveVol.checked && !masterEnabled.checked,
            trim_silence: trimSilence.checked,
            output_format: outputFormat.value,
            trim_armed: !!(t && (t.inS > 0 || t.outS != null)),
            repair: repairPayload(),
        };
    };

    function pushSettings() {
        // The Signal Chain view re-renders from live settings on this.
        document.dispatchEvent(new CustomEvent('shimmer:settings-changed'));
        saveSettings({
            remember_settings: !!(rememberSettings && rememberSettings.checked),
            preset: presetSelect.value,
            preset_strength: currentStrength(),
            sliders: controls.getValues(),
            preserve_volume: preserveVol.checked,
            trim_silence: trimSilence.checked,
            output_format: outputFormat.value,
            mastering: masteringPayload(),
            eq: eqPanel.getPayload(),
            ab_loudness_match: abLoudnessMatch.checked,
        });
    }
    preserveVol.addEventListener('change', () => {
        pushSettings();
        schedulePreviewRender();
    });
    trimSilence.addEventListener('change', pushSettings);
    if (rememberSettings) {
        rememberSettings.addEventListener('change', pushSettings);
    }
    outputFormat.addEventListener('change', pushSettings);

    // ── Live preview ──────────────────────────────────────────────────
    // Original keeps the full file; only Processed and Removed loop a
    // small slice that re-renders on every slider change.

    function setPreviewStatus(text, kind = '') {
        previewStatus.textContent = text;
        previewStatus.classList.remove('live', 'error', 'busy');
        if (kind) previewStatus.classList.add(kind);
    }

    async function teardownPreviewSession() {
        if (previewState.renderInflight) {
            try { previewState.renderInflight.abort(); } catch (_) {}
            previewState.renderInflight = null;
        }
        if (previewState.debounceTimer) {
            clearTimeout(previewState.debounceTimer);
            previewState.debounceTimer = null;
        }
        if (previewState.sessionId) {
            const sid = previewState.sessionId;
            previewState.sessionId = null;
            dropSession(sid);  // fire-and-forget
        }
        previewState.durationS = 0;
        previewState.renderPending = false;
    }

    function clampWindow(anchor, windowS, total) {
        if (!Number.isFinite(total) || total <= 0) {
            return {start: 0, end: Math.min(windowS, 1.0)};
        }
        let start = Math.max(0, Math.min(total, anchor));
        let end = start + windowS;
        if (end > total) {
            end = total;
            start = Math.max(0, end - windowS);
        }
        return {start, end};
    }

    // Start time of the max-intensity contiguous window in the Analyze
    // timeline, or null when no timeline exists yet.
    function hottestAnchor(winSec, totalS) {
        if (!lastTimeline || !lastTimeline.length ||
            !Number.isFinite(totalS) || totalS <= 0) return null;
        const binS = totalS / lastTimeline.length;
        const winBins = Math.max(1, Math.round(winSec / binS));
        let sum = 0, bestSum = -Infinity, bestIdx = 0;
        for (let i = 0; i < lastTimeline.length; i++) {
            sum += lastTimeline[i];
            if (i >= winBins) sum -= lastTimeline[i - winBins];
            if (i >= winBins - 1 && sum > bestSum) {
                bestSum = sum;
                bestIdx = i - winBins + 1;
            }
        }
        return bestIdx * binS;
    }

    // `quiet` suppresses the preview status line. The edge scan at file-drop
    // needs a session but is not a preview render, and "Preparing preview…"
    // is only ever cleared by a render completing — so a quiet caller must
    // not set it, or it stays on screen forever.
    async function ensurePreviewSession({quiet = false} = {}) {
        if (previewState.sessionId) return previewState.sessionId;
        if (!currentFile) return null;
        if (!quiet) setPreviewStatus('Preparing preview…', 'busy');
        try {
            const r = await uploadFile(currentFile);
            previewState.sessionId = r.session_id;
            previewState.durationS = r.duration_s;
            lastEdges = r.edges || null;
            if (r.repair && r.repair.plan) setRepairPlan(r.repair.plan);
            if (r.analysis) {
                lastAnalysis = r.analysis;
                renderAnalysisReadout(r.analysis);
                eqPanel.refreshSpectrum();
            }
            return r.session_id;
        } catch (e) {
            if (!quiet) setPreviewStatus(`Preview failed: ${e.message}`, 'error');
            return null;
        }
    }

    // Install a render (fresh or cached) into the player and refresh the
    // match gains from the slice loudness in its metadata.
    function applyPreviewResult(entry, start, end, region, note) {
        // Toggled off mid-render: don't re-enter the loop (see the abort
        // note in applyPreviewToggle). Abort rejects the fetch, but a render
        // resolving during decode can still land here after Live went off.
        if (!previewState.active) return;
        player.setPreviewBuffers({
            processedBuf: entry.processedBuf,
            removedBuf: entry.removedBuf,
            startS: start,
            endS: end,
        });
        const meta = entry.meta || {};
        previewMatchDb =
            (typeof meta.lufs_processed === 'number' &&
             typeof meta.lufs_original === 'number')
                ? meta.lufs_processed - meta.lufs_original : null;
        applyLoudnessMatch();
        setPreviewStatus(`Live · loop ${region} · ${note}`, 'live');
    }

    async function doPreviewRender() {
        if (!previewState.active) return;
        const sid = await ensurePreviewSession();
        if (!sid) return;

        // If a render is already running, mark another as pending and return;
        // the in-flight render's finally-block will pick up the latest state.
        if (previewState.renderInflight) {
            previewState.renderPending = true;
            return;
        }

        const winSec = parseFloat(previewWindow.value) || 10;
        previewState.windowS = winSec;

        // Auto mode anchors on the artifact-hot region once Analyze has
        // produced a timeline; "Set from playhead" switches to manual.
        let regionNote = '';
        if (previewState.anchorMode === 'auto') {
            const hot = hottestAnchor(winSec, previewState.durationS);
            if (hot != null) {
                previewState.anchorS = hot;
                regionNote = ' (hottest region)';
            }
        }

        const {start, end} = clampWindow(
            previewState.anchorS, winSec, previewState.durationS);
        const region = `${fmtTime(start)}–${fmtTime(end)}${regionNote}`;

        const overrides = controls.getValues();
        const payload = {
            session_id: sid,
            start_s: start,
            end_s: end,
            preset: presetSelect.value,
            preset_strength: currentStrength(),
            overrides,
            preserve_volume: preserveVol.checked && !masterEnabled.checked,
            mastering: masteringPayload(),
            eq: eqPanel.getPayload(),
            repair: repairPayload(),
        };

        // Decoded-render cache: same window + same params = instant swap.
        const cacheKey = JSON.stringify([
            start, end, payload.preset, payload.preset_strength,
            overrides, payload.preserve_volume, payload.mastering, payload.repair,
            payload.eq,
        ]);
        const hit = previewCache.get(cacheKey);
        if (hit) {
            previewCache.delete(cacheKey);
            previewCache.set(cacheKey, hit);  // LRU refresh
            applyPreviewResult(hit, start, end, region, 'cached');
            return;
        }

        const ctrl = new AbortController();
        previewState.renderInflight = ctrl;
        setPreviewStatus(`Rendering preview · ${region}…`, 'busy');

        try {
            const r = await renderPreview(payload, {signal: ctrl.signal});
            const [processedBuf, removedBuf] = await Promise.all([
                player.decodeAudio(r.processed),
                player.decodeAudio(r.removed),
            ]);
            const entry = {processedBuf, removedBuf, meta: r.meta};
            previewCache.set(cacheKey, entry);
            while (previewCache.size > PREVIEW_CACHE_MAX) {
                previewCache.delete(previewCache.keys().next().value);
            }
            applyPreviewResult(
                entry, start, end, region,
                `rendered in ${r.meta.render_ms} ms`);
        } catch (e) {
            if (e.name !== 'AbortError') {
                setPreviewStatus(`Preview failed: ${e.message}`, 'error');
            }
        } finally {
            previewState.renderInflight = null;
            if (previewState.renderPending && previewState.active) {
                previewState.renderPending = false;
                doPreviewRender();
            }
        }
    }

    function schedulePreviewRender() {
        if (!previewState.active) {
            // An edit with Live off is the teachable moment — nudge once.
            maybePreviewNudge();
            return;
        }
        if (previewState.debounceTimer) {
            clearTimeout(previewState.debounceTimer);
        }
        previewState.debounceTimer = setTimeout(() => {
            previewState.debounceTimer = null;
            doPreviewRender();
        }, PREVIEW_DEBOUNCE_MS);
    }

    function capturePlayheadTime() {
        const t = Number(player.getTime());
        return Number.isFinite(t) ? t : 0;
    }

    function applyPreviewToggle(on) {
        previewState.active = !!on;
        previewControls.hidden = !on;

        if (on) {
            // Turning Live on satisfies the nudge — retire it for good and
            // drop the actionable hint so the explainer can revert later.
            markNudgeSeen();
            if (previewExplainer) previewExplainer.classList.remove('nudge');
            if (previewToggleRow) previewToggleRow.classList.remove('nudge-pulse');
            syncPreviewExplainer();
            // Auto mode resolves to the artifact-hot region inside
            // doPreviewRender; the playhead is the fallback anchor.
            previewState.anchorS = capturePlayheadTime();
            previewState.windowS = parseFloat(previewWindow.value) || 20;
            if (!currentFile) {
                setPreviewStatus('Drop a file first.');
                return;
            }
            applyLoudnessMatch();  // switch match source to preview LUFS
            doPreviewRender();
        } else {
            // Cancel any render requested while Live was on. Without this
            // an in-flight (or debounced) render resolves *after* we exit
            // and calls setPreviewBuffers, silently re-entering the loop —
            // the "sometimes locked into loop timing" glitch. The guard in
            // applyPreviewResult covers the decode window abort can't reach.
            if (previewState.renderInflight) {
                try { previewState.renderInflight.abort(); } catch (_) {}
                previewState.renderInflight = null;
            }
            if (previewState.debounceTimer) {
                clearTimeout(previewState.debounceTimer);
                previewState.debounceTimer = null;
            }
            previewState.renderPending = false;
            player.exitPreview();
            player.setSource('processed', null);
            player.setSource('removed', null);
            applyLoudnessMatch();  // back to full-run metrics
            setPreviewStatus(currentFile
                ? 'Live preview off — playhead runs the full track.'
                : 'Drop a file to start.');
            syncPreviewExplainer();  // status pill is hidden while off → show explainer
        }
    }

    previewToggle.addEventListener('change', () => {
        applyPreviewToggle(previewToggle.checked);
    });
    previewWindow.addEventListener('change', () => {
        previewState.windowS = parseFloat(previewWindow.value) || 20;
        schedulePreviewRender();
    });
    previewHereBtn.addEventListener('click', () => {
        // Re-anchor the loop window at the shared playhead (manual
        // override of the auto hot-region anchoring).
        previewState.anchorMode = 'manual';
        previewState.anchorS = capturePlayheadTime();
        if (!previewState.active) {
            previewToggle.checked = true;
            applyPreviewToggle(true);
        } else {
            doPreviewRender();
        }
    });
    window.addEventListener('beforeunload', () => {
        if (previewState.sessionId) dropSession(previewState.sessionId);
    });

    // ── Clean & Master progress modal ─────────────────────────────────
    const processModal      = $('process-modal');
    const processModalTitle = $('process-modal-title');
    const processModalStage = $('process-modal-stage');
    const processModalFill  = $('process-modal-fill');
    const processModalPct   = $('process-modal-pct');
    const processModalError = $('process-modal-error');
    const processModalClose = $('process-modal-close');

    // Stage caption from the pipeline's known fraction boundaries
    // (tone ~0–5%, cleaning ~5–85%, master/limiter/encode ~85–100%).
    function processStageLabel(frac) {
        if (frac < 0.05) return 'Preparing…';
        if (frac < 0.85) return 'Cleaning AI artifacts…';
        return masterEnabled.checked ? 'Mastering & finalizing…' : 'Finalizing…';
    }
    function updateProcessModal(frac) {
        const pct = Math.max(0, Math.min(100, Math.round(frac * 100)));
        processModalFill.style.width = `${pct}%`;
        processModalPct.textContent = `${pct}%`;
        processModalStage.textContent = processStageLabel(frac);
    }
    function openProcessModal() {
        // The title must say what this run actually does.
        if (processModalTitle) {
            processModalTitle.textContent = masterEnabled.checked
                ? 'Cleaning & mastering' : 'Cleaning';
        }
        processModalError.hidden = true;
        processModalError.textContent = '';
        processModalClose.hidden = true;
        processModalFill.style.width = '0%';
        processModalPct.textContent = '0%';
        processModalStage.textContent = 'Preparing…';
        processModal.hidden = false;
    }
    function closeProcessModal() { processModal.hidden = true; }
    function failProcessModal(message) {
        processModalStage.textContent = 'Processing failed';
        processModalError.textContent = message;
        processModalError.hidden = false;
        processModalClose.hidden = false;
        processModalClose.focus();
    }
    processModalClose.addEventListener('click', closeProcessModal);
    document.addEventListener('keydown', (e) => {
        // Not dismissable while running (no cancel support); Esc closes only
        // once the error Close button is offered.
        if (e.key === 'Escape' && !processModal.hidden && !processModalClose.hidden) {
            closeProcessModal();
        }
    });

    // ── Process ───────────────────────────────────────────────────────
    // Never save an error message as a file. The result lives in the
    // server's memory; if the server restarted since the run, the link
    // answers with a JSON error and a plain <a download> would save that
    // JSON as the "WAV". Check first, then download for real.
    downloadLink.addEventListener('click', async (e) => {
        const href = downloadLink.getAttribute('href');
        if (!href) return;
        e.preventDefault();
        try {
            // Probe with a GET and drop the body: the route has no HEAD.
            const probe = await fetch(href);
            const ct = probe.headers.get('content-type') || '';
            if (!probe.ok || ct.startsWith('application/json')) {
                let msg = `Download failed (${probe.status}).`;
                try {
                    const body = await probe.json();
                    if (body && body.detail) msg = `Download failed: ${body.detail}.`;
                } catch (_) { /* no JSON body */ }
                if (/unknown job/i.test(msg)) {
                    msg += ' The server was restarted since this run, so the ' +
                           'result is gone. Run Clean & Master again.';
                }
                setMetrics(msg);
                return;
            }
            try { await probe.body?.cancel(); } catch (_) { /* already drained */ }
            const a = document.createElement('a');
            a.href = href;
            a.download = '';
            document.body.appendChild(a);
            a.click();
            a.remove();
        } catch (err) {
            setMetrics(`Download failed: ${err.message}`);
        }
    });

    processBtn.addEventListener('click', async () => {
        if (!currentFile) return;
        // Analyze found a second pass and mastering is on: ask before we
        // master a file that still needs another cleaning pass.
        if (lastFollowUp && masterEnabled.checked) {
            const label = lastFollowUp.label || labelOf(lastFollowUp.name);
            const turnOff = window.confirm(
                `Analyze found a second pass worth running: ${label}.\n\n` +
                'Mastering is on. If you master now, the second pass will ' +
                'clean a file that is already limited and set to its final ' +
                'loudness, and then master it again. That can hurt the sound.\n\n' +
                'Best plan: master only once, at the end.\n\n' +
                'OK = turn mastering off for this pass and keep Preserve volume on.\n' +
                'Cancel = master now anyway.');
            if (turnOff) {
                masterEnabled.checked = false;
                masterEnabled.dispatchEvent(new Event('change'));
                preserveVol.checked = true;
                preserveVol.dispatchEvent(new Event('change'));
            }
        }
        // Full-file processing replaces the slice players; turn live
        // preview off so the loop state doesn't fight the new sources.
        if (previewState.active) {
            previewToggle.checked = false;
            applyPreviewToggle(false);
        }
        processBtn.disabled = true;
        const originalLabel = processBtn.textContent;
        processBtn.textContent = 'Processing…';
        progressEl.value = 0;
        openProcessModal();
        setMetrics('Preparing…');

        try {
            const overrides = controls.getValues();
            const paramsBody = {
                preset: presetSelect.value,
                preset_strength: currentStrength(),
                overrides,
                mastering: masteringPayload(),
                eq: eqPanel.getPayload(),
                repair: repairPayload(),
            };
            if (lastAnalysis) paramsBody.mastering_analysis = lastAnalysis;

            const wantTrim = trimSilence.checked;
            const edit = trimPanel ? trimPanel.getTrim() : null;
            const job = await submitProcess(
                currentFile,
                paramsBody,
                outputFormat.value,
                preserveVol.checked && !masterEnabled.checked,
                wantTrim,
                edit,
            );

            await new Promise((resolve, reject) => {
                openSSE(`/api/progress/${job.job_id}`, {
                    onMessage: (msg) => {
                        if (typeof msg.fraction === 'number') {
                            progressEl.value = msg.fraction;
                            updateProcessModal(msg.fraction);
                        }
                        if (msg.error) reject(new Error(msg.error));
                    },
                    onDone: (msg) => msg.error ? reject(new Error(msg.error)) : resolve(),
                    onError: (e) => reject(e),
                });
            });

            await player.loadFromJob(job.job_id);
            player.setTrack('processed');

            downloadLink.href = resultUrl(
                job.job_id, wantTrim ? 'trimmed' : 'processed');
            setWizardStep(2);

            const bannerChips = [];
            const m = await fetchMetrics(job.job_id);
            if (m && m.metrics) {
                const mm = m.metrics;
                const chips = [
                    `Peak ${mm.input.peak_dbfs.toFixed(1)} → ${mm.output.peak_dbfs.toFixed(1)} dBFS`,
                    `RMS ${mm.input.rms_dbfs.toFixed(1)} → ${mm.output.rms_dbfs.toFixed(1)} dBFS`,
                    `${mm.duration_s.toFixed(1)}s · ${mm.sample_rate} Hz · ${mm.channels}ch`,
                ];

                if (mm.eq && mm.eq.enabled) {
                    chips.push(`EQ: ${mm.eq.bands} band${mm.eq.bands === 1 ? '' : 's'}`);
                }

                // State the applied cut on the result, not just in the panel:
                // the user should never wonder whether the trim went through.
                if (mm.edge_trim && mm.edge_trim.applied) {
                    const et = mm.edge_trim;
                    const parts = [];
                    if (et.cut_head_s > 0) parts.push(`${(et.cut_head_s * 1000).toFixed(0)} ms head`);
                    if (et.cut_tail_s > 0) parts.push(`${(et.cut_tail_s * 1000).toFixed(0)} ms tail`);
                    chips.push(`Trimmed ${parts.join(' + ')}`);
                    bannerChips.push(`Trimmed ${parts.join(' + ')}`);
                }

                if (mm.trim && mm.trim.enabled) {
                    const cut = (mm.trim.cut_head_s || 0) + (mm.trim.cut_tail_s || 0);
                    chips.push(cut > 0.05
                        ? `Export trims ${cut.toFixed(1)}s silence`
                        : 'Export trim: no silence found');
                }

                fullMatchDb = null;
                const mast = mm.mastering;
                if (mast && mast.enabled && mast.before && mast.after) {
                    chips.push(
                        `LUFS ${mast.before.lufs_i?.toFixed(1)} → ${mast.after.lufs_i?.toFixed(1)} (target ${mast.target_lufs})`);
                    chips.push(
                        `TP ${mast.before.true_peak_dbtp?.toFixed(1)} → ${mast.after.true_peak_dbtp?.toFixed(1)} dBTP`);
                    if (mast.limiter && mast.limiter.max_gain_reduction_db != null) {
                        const gr = mast.limiter.max_gain_reduction_db;
                        chips.push(`Limiter ${gr.toFixed(1)} dB max GR`);
                        // Warm tilt boosts the low end, which is what drives
                        // limiter pumping at loud targets — warn when the
                        // combination is actually working the limiter hard.
                        const warmTilt = mast.tilt === 'warm' || mast.tilt === 'warmer';
                        if (warmTilt && gr < -3) {
                            chips.push(
                                '⚠ Warm tilt + loud target is pushing the limiter — ' +
                                'possible pumping. Try a lower loudness target.');
                        }
                    }
                    lastMasteringReport = mast;
                    fullMatchDb = -(mast.ab_match_gain_db || 0);
                    player.setTargetLufs(mast.target_lufs);
                    bannerChips.push(
                        `${mast.before.lufs_i?.toFixed(1)} → ${mast.after.lufs_i?.toFixed(1)} LUFS`);
                    bannerChips.push(
                        `TP ${mast.after.true_peak_dbtp?.toFixed(1)} dBTP`);
                }
                // Loudness match with mastering off: use the whole-file
                // LUFS pair the server now measures on every run.
                const loud = mm.loudness;
                if (fullMatchDb == null && loud &&
                    typeof loud.input_lufs_i === 'number' &&
                    typeof loud.output_lufs_i === 'number') {
                    fullMatchDb = loud.output_lufs_i - loud.input_lufs_i;
                }
                applyLoudnessMatch();

                const diag = mm.diagnostic;
                if (diag && diag.before && diag.after) {
                    const fmt = (v, digits = 2) =>
                        (v == null || Number.isNaN(v)) ? 'n/a' : v.toFixed(digits);
                    const b = diag.before;
                    const a = diag.after;
                    chips.push(
                        `5-8k energy ${fmt(b.band_5_8k_rms_db, 1)} → ${fmt(a.band_5_8k_rms_db, 1)} dB`);
                    chips.push(
                        `5-8k AM ${fmt(b.band_5_8k_am_depth)} → ${fmt(a.band_5_8k_am_depth)}`);
                    if (Array.isArray(a.top_peaks) && a.top_peaks.length) {
                        const peaks = a.top_peaks
                            .slice(0, 3)
                            .map(pk => `${(pk.hz / 1000).toFixed(2)}k +${fmt(pk.excess_db, 1)}dB`)
                            .join(', ');
                        chips.push(`Peaks left: ${peaks}`);
                    } else {
                        chips.push('Peaks left: none');
                    }
                }

                setMetrics(chips);
            }

            if (bannerChips.length === 0) bannerChips.push('Cleaned');
            bannerChips.push(outputFormat.value.toUpperCase());
            downloadLink.textContent =
                `Download ${outputFormat.value.toUpperCase()}`;
            showDoneBanner(bannerChips);
            closeProcessModal();  // success: reveal the done banner
        } catch (e) {
            setMetrics(`Error: ${e.message}`);
            failProcessModal(e.message);  // keep modal open with a Close
        } finally {
            processBtn.disabled = false;
            processBtn.textContent = originalLabel;
            progressEl.hidden = true;
        }
    });

}
