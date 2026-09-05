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
import { initReport } from './report.js';


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
    // Renders the stat readout. Accepts a string, an array of strings (one
    // unlabeled row), or an array of {label, chips} groups (one labeled
    // row each; empty groups are skipped). Empty input hides the box.
    function setMetrics(items) {
        metricsBox.innerHTML = '';
        const list = items == null ? [] : (Array.isArray(items) ? items : [String(items)]);
        const isGrouped = list.length > 0 &&
            list.every(g => g && typeof g === 'object' && Array.isArray(g.chips));
        const groups = isGrouped ? list : [{ label: '', chips: list }];
        let count = 0;
        for (const g of groups) {
            const chips = g.chips.map(s => String(s).trim()).filter(s => s.length > 0);
            if (!chips.length) continue;
            const row = document.createElement('div');
            row.className = 'metric-row';
            if (g.label) {
                const lab = document.createElement('span');
                lab.className = 'metric-row-label';
                lab.textContent = g.label;
                row.appendChild(lab);
            }
            for (const text of chips) {
                const chip = document.createElement('span');
                chip.className = 'metric-chip';
                if (/^Error\b/i.test(text)) chip.classList.add('err');
                chip.textContent = text;
                chip.title = text;
                row.appendChild(chip);
            }
            metricsBox.appendChild(row);
            count += chips.length;
        }
        metricsBox.hidden = count === 0;
    }
    const autoDetectResults = $('auto-detect-results');
    // Step 2 in the dock: runs Analyze and jumps to the Analysis card,
    // then shows the verdict as a green status. Same for the card header.
    const analyzeDockBtn = $('analyze-dock-btn');
    const analysisCard = $('analysis-card');
    const analysisStatus = $('analysis-status');
    function setAnalyzeDock(state, text = '') {
        if (!analyzeDockBtn) return;
        analyzeDockBtn.classList.toggle('busy', state === 'busy');
        analyzeDockBtn.classList.toggle('done', state === 'done');
        const label = analyzeDockBtn.querySelector('.adb-text');
        const step = analyzeDockBtn.querySelector('.adb-step');
        if (label) label.textContent = state === 'busy' ? 'Analyzing…'
            : state === 'done' ? 'View analysis' : 'Analyze';
        if (step) step.textContent = state === 'done' ? '✓' : '2';
        analyzeDockBtn.title = state === 'done'
            ? 'Analysis is done. Opens the results in the workspace.'
            : 'Listens to your track and picks the best cleanup preset. Jumps to the Analysis card.';
        if (analysisStatus) {
            analysisStatus.hidden = state !== 'done';
            analysisStatus.textContent = state === 'done' ? `Ready · ${text}` : '';
        }
        if (analysisExpandBtn) analysisExpandBtn.hidden = state !== 'done';
        syncSheetStatus();
    }
    // What stage 3 will do, from the live controls (never a stale copy):
    // preset, strength, and master target or cleaning only.
    const dockStatus = $('dock-status');
    function syncDockStatus() {
        if (!dockStatus) return;
        if (!currentFile) { dockStatus.hidden = true; return; }
        const preset = labelOf(presetSelect.value) || presetSelect.value || '';
        const pct = Math.round(currentStrength() * 100);
        let tail = 'cleaning only';
        if (masterEnabled.checked) {
            const opt = masterTarget.options[masterTarget.selectedIndex];
            const t = opt ? opt.text : '';
            const short = t.includes(')') ? t.slice(0, t.indexOf(')') + 1) : t;
            tail = `master to ${short}`;
        }
        dockStatus.textContent = `${preset} · ${pct}% · ${tail}`;
        dockStatus.hidden = false;
    }

    function jumpToAnalysis() {
        if (!analysisCard) return;
        analysisCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
        analysisCard.classList.remove('flash');
        void analysisCard.offsetWidth;   // restart the animation
        analysisCard.classList.add('flash');
    }
    if (analyzeDockBtn) {
        analyzeDockBtn.addEventListener('click', () => {
            if (analyzeDockBtn.classList.contains('done')) {
                openAnalysisSheet();
                return;
            }
            jumpToAnalysis();
            if (!analyzeDockBtn.classList.contains('busy')) autoBtn.click();
        });
    }

    // ── Analysis workspace: the results slide up over the page ───────
    // The result nodes are moved into the sheet while it is open and
    // moved back into the card on close, so there is one copy and a
    // re-run of Analyze while the sheet is open renders into the sheet.
    const analysisSheet = $('analysis-sheet');
    const analysisSheetBody = $('analysis-sheet-body');
    const analysisSheetStatus = $('analysis-sheet-status');
    const analysisSheetClose = $('analysis-sheet-close');
    const analysisSheetLoop = $('analysis-sheet-loop');
    const analysisHome = $('analysis-home');
    const analysisExpandBtn = $('analysis-expand-btn');
    const repairListHost = $('repair-list');
    let sheetCloseTimer = null;

    function placeAnalysisSheet() {
        if (!analysisSheet) return;
        const bridge = document.querySelector('.bridge');
        const rail = document.querySelector('.rail');
        const bottom = bridge ? bridge.getBoundingClientRect().height : 0;
        const left = rail ? rail.getBoundingClientRect().width : 0;
        analysisSheet.style.bottom = `${bottom}px`;
        analysisSheet.style.left = `${left}px`;
        analysisSheet.style.maxHeight = `calc(100dvh - ${bottom + 52}px)`;
    }
    function syncSheetStatus() {
        if (!analysisSheetStatus || !analysisStatus) return;
        analysisSheetStatus.hidden = analysisStatus.hidden;
        analysisSheetStatus.textContent = analysisStatus.textContent;
    }
    function openAnalysisSheet() {
        if (!analysisSheet || !analysisSheetBody) return;
        if (sheetCloseTimer) { clearTimeout(sheetCloseTimer); sheetCloseTimer = null; }
        placeAnalysisSheet();
        analysisSheetBody.append(autoDetectResults, repairListHost);
        syncSheetStatus();
        analysisSheet.hidden = false;
        requestAnimationFrame(() => analysisSheet.classList.add('open'));
        if (analysisSheetClose) analysisSheetClose.focus();
    }
    function closeAnalysisSheet(immediate = false) {
        if (!analysisSheet || analysisSheet.hidden) return;
        analysisSheet.classList.remove('open');
        const finish = () => {
            sheetCloseTimer = null;
            analysisSheet.hidden = true;
            if (analysisHome) analysisHome.after(autoDetectResults, repairListHost);
        };
        if (immediate) finish();
        else sheetCloseTimer = setTimeout(finish, 240);
    }
    if (analysisSheetClose) analysisSheetClose.addEventListener('click', () => closeAnalysisSheet());
    if (analysisExpandBtn) analysisExpandBtn.addEventListener('click', openAnalysisSheet);
    if (analysisSheetLoop) {
        analysisSheetLoop.addEventListener('click', () => {
            // Same as the auto anchor: Live on, loop parked on the worst
            // stretch the analysis found.
            previewState.anchorMode = 'auto';
            if (!previewState.active) {
                previewToggle.checked = true;
                applyPreviewToggle(true);
            } else {
                doPreviewRender();
            }
        });
    }
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && analysisSheet && !analysisSheet.hidden) closeAnalysisSheet();
    });
    window.addEventListener('resize', () => {
        if (analysisSheet && !analysisSheet.hidden) placeAnalysisSheet();
    });
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
    // Report stage: the "What changed" spectrum card (report.js draws,
    // shimmer/report.py measures).
    const report = initReport({
        card: $('spectrum-card'),
        canvas: $('spectrum-compare'),
        headline: $('spectrum-headline'),
        readout: $('spectrum-readout'),
    });

    // Transport scrubber (bridge): follows the playhead and shows the Live
    // loop window; click or drag to seek. Declared before the player so
    // its first time update can reach these elements.
    const seekEl = $('player-seek');
    const seekTrack = seekEl ? seekEl.querySelector('.tp-seek-track') : null;
    const seekFill = $('player-seek-fill');
    const seekThumb = $('player-seek-thumb');
    const seekLoop = $('player-seek-loop');
    const tpCur = $('tp-cur');
    const tpTotal = $('tp-total');
    function updateSeek(t, d, loop) {
        if (tpCur) tpCur.textContent = fmtTime(t);
        if (tpTotal) tpTotal.textContent = fmtTime(d);
        if (!seekEl) return;
        const frac = d > 0 ? Math.max(0, Math.min(1, t / d)) : 0;
        seekFill.style.width = `${frac * 100}%`;
        seekThumb.style.left = `${frac * 100}%`;
        seekEl.setAttribute('aria-valuenow', String(Math.round(frac * 100)));
        seekEl.setAttribute('aria-valuetext', `${fmtTime(t)} of ${fmtTime(d)}`);
        if (loop && d > 0) {
            seekLoop.hidden = false;
            seekLoop.style.left = `${(loop.start / d) * 100}%`;
            seekLoop.style.width = `${Math.max(0.5, ((loop.end - loop.start) / d) * 100)}%`;
        } else {
            seekLoop.hidden = true;
        }
    }

    player = createUnifiedPlayer({
        onTimeUpdate: updateSeek,
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

    // Transport buttons and scrubber.
    const SKIP_S = 5;
    const btnStart = $('player-start'), btnBack = $('player-back'), btnFwd = $('player-fwd');
    if (btnStart) btnStart.addEventListener('click', () => player.toStart());
    if (btnBack) btnBack.addEventListener('click', () => player.skip(-SKIP_S));
    if (btnFwd) btnFwd.addEventListener('click', () => player.skip(SKIP_S));
    if (seekEl && seekTrack) {
        let seeking = false;
        const seekAt = (clientX) => {
            const rect = seekTrack.getBoundingClientRect();
            if (rect.width <= 0) return;
            const frac = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
            const d = player.duration;
            if (d > 0) player.seek(frac * d);
        };
        seekEl.addEventListener('pointerdown', (e) => {
            seeking = true;
            try { seekEl.setPointerCapture(e.pointerId); } catch (_) {}
            seekAt(e.clientX);
            e.preventDefault();
        });
        seekEl.addEventListener('pointermove', (e) => { if (seeking) seekAt(e.clientX); });
        const stop = (e) => { if (seeking) { seeking = false; if (e && e.clientX != null) seekAt(e.clientX); } };
        seekEl.addEventListener('pointerup', stop);
        seekEl.addEventListener('pointercancel', () => { seeking = false; });
    }

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

    // Stage 3 is named by what it will do: "Clean & Master" with
    // mastering on, "Clean" with it off. Button and stepper together.
    function processLabel() {
        return masterEnabled.checked ? 'Clean & Master' : 'Clean';
    }
    function syncProcessLabel() {
        if (processBtn.textContent !== 'Processing…') processBtn.textContent = processLabel();
        const step = stepProcess && stepProcess.querySelector('.step-label');
        if (step) step.textContent = processLabel();
    }

    function updateMasteringUI() {
        const on = masterEnabled.checked;
        $('mastering-options').style.opacity = on ? '1' : '0.5';
        syncProcessLabel();
        // Preserve volume only matters with mastering off. Keep the row in
        // view but greyed while mastering is on, so it can be found when a
        // tip mentions it; the loudness target sets the level meanwhile.
        preserveVolCard.classList.toggle('is-off', on);
        preserveVol.disabled = on;
        if (on) preserveVol.checked = false;
        const note = preserveVolCard.querySelector('.pv-note');
        if (note) {
            note.textContent = on
                ? 'not used while mastering is on; the loudness target sets the level'
                : 'keeps the level the same on a cleaning-only pass';
        }
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
        if (analyzeDockBtn) analyzeDockBtn.disabled = false;
        closeAnalysisSheet(true);
        setAnalyzeDock('idle');
        syncDockStatus();
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
        report.clear();
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

    // Three-way dialog for the master-once reminder. Resolves to 'off'
    // (turn mastering off for this pass), 'master' (master anyway) or
    // 'cancel' (run nothing). A browser confirm() only has two buttons,
    // and "Cancel = master anyway" surprised people.
    const secondPassModal = $('second-pass-modal');
    function askSecondPass(label) {
        return new Promise((resolve) => {
            if (!secondPassModal) { resolve('master'); return; }
            const presetEl = $('second-pass-preset');
            if (presetEl) presetEl.textContent = label;
            const btnOff = $('second-pass-off');
            const btnMaster = $('second-pass-master');
            const btnCancel = $('second-pass-cancel');
            const finish = (choice) => {
                secondPassModal.hidden = true;
                btnOff.removeEventListener('click', onOff);
                btnMaster.removeEventListener('click', onMaster);
                btnCancel.removeEventListener('click', onCancel);
                document.removeEventListener('keydown', onKey);
                resolve(choice);
            };
            const onOff = () => finish('off');
            const onMaster = () => finish('master');
            const onCancel = () => finish('cancel');
            const onKey = (e) => { if (e.key === 'Escape') finish('cancel'); };
            btnOff.addEventListener('click', onOff);
            btnMaster.addEventListener('click', onMaster);
            btnCancel.addEventListener('click', onCancel);
            document.addEventListener('keydown', onKey);
            secondPassModal.hidden = false;
            btnOff.focus();
        });
    }

    // Plain-language advice shown whenever Analyze suggests a second pass
    // and mastering is on. Mastering limits the sound and sets its
    // loudness; cleaning a mastered file and mastering it again hurts it.

    function showAutoDetectError(msg) {
        autoDetectResults.hidden = false;
        autoDetectResults.innerHTML = '';
        const err = document.createElement('div');
        err.className = 'ad-error';
        err.textContent = msg;
        autoDetectResults.appendChild(err);
    }

    // Verdict first. The applied match is the hero; the other matches are
    // a quiet table; the second pass is a call to action with a button;
    // notes are a Details list. Four status tiles render too, shown only
    // in the workspace sheet (CSS). Amber marks exactly two things: the
    // applied choice and the next action.
    let syncNextStep = null;   // re-checks the second-pass callout when mastering toggles
    masterEnabled.addEventListener('change', () => { if (syncNextStep) syncNextStep(); });
    preserveVol.addEventListener('change', () => { if (syncNextStep) syncNextStep(); });

    function renderAutoDetect(r) {
        autoDetectResults.hidden = false;
        autoDetectResults.innerHTML = '';
        syncNextStep = null;

        const ranked = Array.isArray(r.ranked) ? r.ranked : [];
        if (ranked.length === 0) {
            const note = document.createElement('div');
            note.className = 'ad-reason';
            note.textContent = 'No artifact detected; safe defaults will do.';
            autoDetectResults.appendChild(note);
            return;
        }

        const el = (tag, cls, text) => {
            const e = document.createElement(tag);
            if (cls) e.className = cls;
            if (text != null) e.textContent = text;
            return e;
        };
        const matches = ranked.slice(0, 6);
        const followUp = (r.follow_up && r.follow_up.name) ? r.follow_up : null;
        const notches = (r.repair_plan && Array.isArray(r.repair_plan.notches))
            ? r.repair_plan.notches.length : 0;
        const cutoffHz = Number(r.evidence && r.evidence.cutoff_hz) || 0;
        const pctOf = (v) => `${Math.round((Number.isFinite(v) ? v : 1) * 100)}%`;
        const nameOf = (m) => m.label || labelOf(m.name);

        // Status tiles (workspace only).
        const tiles = el('div', 'ad-tiles');
        const tile = (label, value, tone) => {
            const t = el('div', `ad-tile ${tone}`);
            t.append(el('div', 't-label', label), el('div', 't-value', value));
            tiles.appendChild(t);
            return t;
        };
        const appliedTile = tile('Applied', '', 'amber');
        tile('Second pass',
            followUp ? `Recommended · ${nameOf(followUp)}` : 'Not needed',
            followUp ? 'orange' : 'green');
        tile('Fixed tones',
            notches ? `${notches} notched first` : 'None found',
            notches ? 'cyan' : 'green');
        tile('Top end',
            cutoffHz > 0 ? `Stops at ${(cutoffHz / 1000).toFixed(1)} kHz` : 'Full range',
            'grey');

        // Hero + table. Re-rendered whenever Apply moves the choice, so
        // the highlight follows the state, never the position.
        const main = el('div', 'ad-main');
        const hero = el('div', 'ad-hero');
        const othersLabel = el('div', 'ad-others-label', 'Other matches');
        const table = el('div', 'ad-table');
        main.append(hero, othersLabel, table);

        let applied = 0;
        const renderMain = () => {
            const m = matches[applied];
            hero.innerHTML = '';
            const top = el('div', 'ad-hero-top');
            const strength = el('div', 'ad-hero-strength');
            strength.append(el('span', 'v', pctOf(m.strength)), el('span', 'k', 'strength'));
            top.append(el('div', 'ad-hero-name', nameOf(m)),
                       el('span', 'ad-hero-pill', 'Applied'), strength);
            const conf = el('div', 'ad-hero-conf');
            const bar = el('div', 'ad-confidence');
            const fill = el('div', 'ad-confidence-fill');
            fill.style.width = pctOf(m.confidence || 0);
            bar.appendChild(fill);
            conf.append(bar, el('span', 'ad-confidence-pct', `${pctOf(m.confidence || 0)} match`));
            hero.append(top, conf);
            if (m.reason) hero.appendChild(el('div', 'ad-hero-reason', m.reason));
            appliedTile.querySelector('.t-value').textContent =
                `${nameOf(m)} · ${pctOf(m.strength)}`;

            table.innerHTML = '';
            matches.forEach((entry, i) => {
                if (i === applied) return;
                const row = el('div', 'ad-row');
                row.title = entry.reason || '';
                const bar2 = el('div', 'ad-confidence');
                const fill2 = el('div', 'ad-confidence-fill');
                fill2.style.width = pctOf(entry.confidence || 0);
                bar2.appendChild(fill2);
                const btn = el('button', 'btn btn-ghost ad-apply-btn', 'Apply');
                btn.type = 'button';
                btn.addEventListener('click', () => {
                    applied = i;
                    applyDetectedPreset(entry.name,
                        Number.isFinite(entry.strength) ? entry.strength : 1.0);
                    renderMain();
                    setAnalyzeDock('done', `${nameOf(entry)} ${pctOf(entry.strength)}`);
                    syncDockStatus();
                });
                row.append(el('span', 'ad-row-rank', String(i + 1)),
                           el('span', 'ad-row-name', nameOf(entry)),
                           bar2, el('span', 'ad-row-strength', pctOf(entry.strength)), btn);
                table.appendChild(row);
            });
            const none = table.childElementCount === 0;
            othersLabel.hidden = none;
            table.hidden = none;
        };
        renderMain();

        // Side: next step (second pass) and details.
        const side = el('div', 'ad-side');
        if (followUp) {
            const next = el('div', 'ad-next');
            next.append(el('div', 'ad-next-kicker', 'Next step'),
                        el('div', 'ad-next-title', `Second pass with ${nameOf(followUp)}`));
            if (followUp.reason) next.append(el('div', 'ad-next-reason', followUp.reason));
            // The two settings this pass needs, as state rows rather than
            // prose, plus one button that sets them and then runs the pass.
            const checks = el('div', 'ad-next-checks');
            const mkCheck = (label) => {
                const row = el('div', 'ad-check');
                const state = el('span', 'ad-check-state');
                row.append(el('span', 'ad-check-dot'), el('span', 'ad-check-label', label), state);
                checks.appendChild(row);
                return { row, state };
            };
            const cMaster = mkCheck('Mastering off for this pass');
            const cPreserve = mkCheck('Preserve volume on');
            const why = el('div', 'ad-next-why',
                'Master only once, at the end. Cleaning a mastered file and ' +
                'mastering it again hurts the sound.');
            const btn = el('button', 'btn ad-next-btn');
            btn.type = 'button';
            const after = el('div', 'ad-next-after',
                `Then upload the result and run ${nameOf(followUp)}.`);
            const setState = (c, ok, text) => {
                c.row.classList.toggle('ok', ok);
                c.state.textContent = ok ? `✓ ${text}` : text;
            };
            const syncNext = () => {
                const masterOff = !masterEnabled.checked;
                const preserveOn = !!preserveVol.checked;
                setState(cMaster, masterOff, masterOff ? 'Off' : 'On');
                setState(cPreserve, preserveOn, preserveOn ? 'On' : 'Off');
                const ready = masterOff && preserveOn;
                btn.textContent = ready ? 'Run this pass: Clean' : 'Set up second pass';
                btn.classList.toggle('ready', ready);
                after.hidden = !ready;
            };
            btn.addEventListener('click', () => {
                if (btn.classList.contains('ready')) {
                    closeAnalysisSheet(true);
                    processBtn.click();
                    return;
                }
                masterEnabled.checked = false;
                masterEnabled.dispatchEvent(new Event('change'));
                preserveVol.checked = true;
                preserveVol.dispatchEvent(new Event('change'));
                syncNext();
            });
            syncNextStep = syncNext;
            syncNext();
            next.append(checks, why, btn, after);
            side.appendChild(next);
        }
        const notes = Array.isArray(r.notes) ? r.notes : [];
        if (notes.length) {
            const details = el('div', 'ad-details');
            details.appendChild(el('div', 'ad-details-label', 'Details'));
            notes.forEach((t) => details.appendChild(el('div', 'ad-detail', t)));
            side.appendChild(details);
        }

        autoDetectResults.append(tiles, main);
        if (side.childElementCount > 0) autoDetectResults.appendChild(side);

        const tl = r.timeline && Array.isArray(r.timeline.intensity)
            ? r.timeline.intensity : [];
        if (tl.length > 0) {
            const stepS = (r.timeline.step_s > 0) ? r.timeline.step_s : 1;
            const totalS = tl.length * stepS;
            const wrap = document.createElement('div');
            wrap.className = 'ad-timeline-wrap';

            // Caption row: title left, colour key right. Sits above the
            // strip so it never runs through the bars.
            const head = document.createElement('div');
            head.className = 'ad-timeline-head';
            const title = document.createElement('span');
            title.className = 'ad-timeline-title';
            title.textContent = 'Noise over time';
            const key = document.createElement('span');
            key.className = 'ad-timeline-key';
            const hotSw = document.createElement('i'); hotSw.className = 'sw hot';
            const coolSw = document.createElement('i'); coolSw.className = 'sw cool';
            key.append(hotSw, ' worst stretches ', coolSw,
                ' quieter · Live loop starts at the worst stretch · click to jump');
            head.append(title, key);

            const strip = document.createElement('div');
            strip.className = 'ad-timeline';
            for (let i = 0; i < tl.length; i++) {
                const v = tl[i];
                const bar = document.createElement('div');
                bar.className = 'ad-timeline-bar';
                if (v >= 0.4) bar.classList.add('hot');
                bar.style.height = `${Math.max(4, Math.round(v * 100))}%`;
                bar.title = `${fmtTime(i * stepS)} · noise ${(v * 100).toFixed(0)}%`;
                strip.appendChild(bar);
            }
            // One listener for the whole strip: the click position maps
            // to a time on the track.
            strip.addEventListener('click', (ev) => {
                const rect = strip.getBoundingClientRect();
                if (rect.width <= 0) return;
                const frac = (ev.clientX - rect.left) / rect.width;
                jumpToTime(Math.max(0, Math.min(totalS, frac * totalS)));
            });

            // Time axis: start, quarter marks, end.
            const axis = document.createElement('div');
            axis.className = 'ad-timeline-axis';
            for (let q = 0; q <= 4; q++) {
                const tick = document.createElement('span');
                tick.textContent = fmtTime(totalS * q / 4);
                axis.appendChild(tick);
            }

            wrap.append(head, strip, axis);
            autoDetectResults.appendChild(wrap);
        }
    }

    // Timeline click: with Live on, move the loop window there (manual
    // anchor, same as "Set from playhead"); otherwise seek the player.
    function jumpToTime(t) {
        if (previewState.active) {
            previewState.anchorMode = 'manual';
            previewState.anchorS = t;
            doPreviewRender();
        } else {
            player.seek(t);
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
        setAnalyzeDock('busy');
        let done = false;
        try {
            const r = await runAutoDetect(currentFile);
            lastFollowUp = (r.follow_up && r.follow_up.name) ? r.follow_up : null;
            if (r.repair_plan) setRepairPlan(r.repair_plan);
            applyDetectedPreset(r.preset, r.strength);
            renderAutoDetect(r);
            const pct = Math.round((Number(r.strength) || 1) * 100);
            setAnalyzeDock('done', `${labelOf(r.preset)} ${pct}%`);
            done = true;
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
            if (!done) setAnalyzeDock('idle');
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
        syncDockStatus();
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
    // The Trim card mirrors the export silence-trim setting, so the
    // artifact cut and the floor trim sit together. Two-way sync with
    // the checkbox in Output; one source of truth (#trim-silence).
    const trimSilenceMirror = $('trim-silence-mirror');
    if (trimSilenceMirror) {
        trimSilenceMirror.checked = trimSilence.checked;
        trimSilenceMirror.addEventListener('change', () => {
            trimSilence.checked = trimSilenceMirror.checked;
            trimSilence.dispatchEvent(new Event('change'));
        });
        trimSilence.addEventListener('change', () => {
            trimSilenceMirror.checked = trimSilence.checked;
        });
    }
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
        // master a file that still needs another cleaning pass. Three
        // real choices; Cancel means cancel.
        if (lastFollowUp && masterEnabled.checked) {
            const label = lastFollowUp.label || labelOf(lastFollowUp.name);
            const choice = await askSecondPass(label);
            if (choice === 'cancel') return;
            if (choice === 'off') {
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
                // Grouped readout: loudness first (what a release check
                // needs), then what the cleaning did, then the job facts.
                // Warnings get their own unlabeled row at the end.
                const loudness = [];
                const cleaning = [];
                const job = [];
                const warnings = [];
                const fmt = (v, digits = 2) =>
                    (v == null || Number.isNaN(v)) ? 'n/a' : v.toFixed(digits);
                const pctOf = (v) =>
                    (v == null || Number.isNaN(v)) ? 'n/a' : `${Math.round(v * 100)}%`;

                fullMatchDb = null;
                const mast = mm.mastering;
                if (mast && mast.enabled && mast.before && mast.after) {
                    loudness.push(
                        `LUFS ${mast.before.lufs_i?.toFixed(1)} → ${mast.after.lufs_i?.toFixed(1)} (target ${mast.target_lufs})`);
                    loudness.push(
                        `TP ${mast.before.true_peak_dbtp?.toFixed(1)} → ${mast.after.true_peak_dbtp?.toFixed(1)} dBTP`);
                    if (typeof mast.after.lra === 'number' && typeof mast.before.lra === 'number') {
                        loudness.push(`LRA ${mast.before.lra.toFixed(1)} → ${mast.after.lra.toFixed(1)} LU`);
                    }
                    if (mast.limiter && mast.limiter.max_gain_reduction_db != null) {
                        const gr = mast.limiter.max_gain_reduction_db;
                        loudness.push(gr > -0.05
                            ? 'Limiter: no gain reduction'
                            : `Limiter ${gr.toFixed(1)} dB max GR`);
                        // Warm tilt boosts the low end, which is what drives
                        // limiter pumping at loud targets — warn when the
                        // combination is actually working the limiter hard.
                        const warmTilt = mast.tilt === 'warm' || mast.tilt === 'warmer';
                        if (warmTilt && gr < -3) {
                            warnings.push(
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
                loudness.push(
                    `Peak ${mm.input.peak_dbfs.toFixed(1)} → ${mm.output.peak_dbfs.toFixed(1)} dBFS`,
                    `RMS ${mm.input.rms_dbfs.toFixed(1)} → ${mm.output.rms_dbfs.toFixed(1)} dBFS`);
                // Loudness match with mastering off: use the whole-file
                // LUFS pair the server now measures on every run.
                const loud = mm.loudness;
                if (fullMatchDb == null && loud &&
                    typeof loud.input_lufs_i === 'number' &&
                    typeof loud.output_lufs_i === 'number') {
                    fullMatchDb = loud.output_lufs_i - loud.input_lufs_i;
                }
                applyLoudnessMatch();
                // Release-check extras: peak-to-loudness ratio and stereo
                // correlation, in and out.
                if (loud && loud.input_plr_db != null && loud.output_plr_db != null) {
                    loudness.push(
                        `PLR ${loud.input_plr_db.toFixed(1)} → ${loud.output_plr_db.toFixed(1)} dB`);
                }
                if (loud && (loud.output_correlation != null || loud.input_correlation != null)) {
                    const fc = (v) => (v == null ? 'mono' : `${v >= 0 ? '+' : ''}${v.toFixed(2)}`);
                    loudness.push(
                        `Stereo correlation ${fc(loud.input_correlation)} → ${fc(loud.output_correlation)}`);
                }

                const diag = mm.diagnostic;
                if (diag && diag.before && diag.after) {
                    const b = diag.before;
                    const a = diag.after;
                    cleaning.push(
                        `5–8 kHz energy ${fmt(b.band_5_8k_rms_db, 1)} → ${fmt(a.band_5_8k_rms_db, 1)} dB`);
                    cleaning.push(
                        `Flicker depth ${pctOf(b.band_5_8k_am_depth)} → ${pctOf(a.band_5_8k_am_depth)}`);
                    if (Array.isArray(a.top_peaks) && a.top_peaks.length) {
                        const peaks = a.top_peaks
                            .slice(0, 3)
                            .map(pk => `${(pk.hz / 1000).toFixed(2)}k +${fmt(pk.excess_db, 1)}dB`)
                            .join(', ');
                        cleaning.push(`Narrow peaks left: ${peaks}`);
                    } else {
                        cleaning.push('Narrow peaks left: none');
                    }
                }
                if (mm.declick && mm.declick.enabled) {
                    cleaning.push(`Clicks fixed: ${mm.declick.clicks ?? 0}`);
                }
                if (mm.repair && mm.repair.enabled) {
                    const n = mm.repair.notches ?? 0;
                    cleaning.push(`Fixed tones notched: ${n}`);
                }
                if (mm.cutoff_hz > 0) {
                    cleaning.push(`Top end stops at ${(mm.cutoff_hz / 1000).toFixed(1)} kHz`);
                }

                // State the applied cut on the result, not just in the panel:
                // the user should never wonder whether the trim went through.
                if (mm.edge_trim && mm.edge_trim.applied) {
                    const et = mm.edge_trim;
                    const parts = [];
                    if (et.cut_head_s > 0) parts.push(`${(et.cut_head_s * 1000).toFixed(0)} ms head`);
                    if (et.cut_tail_s > 0) parts.push(`${(et.cut_tail_s * 1000).toFixed(0)} ms tail`);
                    job.push(`Trimmed ${parts.join(' + ')}`);
                    bannerChips.push(`Trimmed ${parts.join(' + ')}`);
                }
                if (mm.trim && mm.trim.enabled) {
                    const cut = (mm.trim.cut_head_s || 0) + (mm.trim.cut_tail_s || 0);
                    job.push(cut > 0.05
                        ? `Export trims ${cut.toFixed(1)}s silence`
                        : 'Export trim: no silence found');
                }
                if (mm.eq && mm.eq.enabled) {
                    job.push(`EQ: ${mm.eq.bands} band${mm.eq.bands === 1 ? '' : 's'}`);
                }
                const chStr = mm.channels === 1 ? 'mono' : (mm.channels === 2 ? 'stereo' : `${mm.channels} ch`);
                job.push(`${fmtTime(mm.duration_s)} · ${(mm.sample_rate / 1000).toFixed(1)} kHz · ${chStr}`);
                // What the download actually is: format, bit depth, dither.
                if (mm.export && mm.export.format) {
                    const ex = mm.export;
                    const fmt = ex.format.toUpperCase();
                    let line = ex.bit_depth ? `${ex.bit_depth}-bit ${fmt}` : fmt;
                    if (ex.bitrate) line += ` ${ex.bitrate.replace('k', ' kbps')}`;
                    if (ex.bit_depth) {
                        line += ex.dither ? ' · TPDF dither'
                            : (ex.bit_depth >= 24 ? ' · no dither needed' : ' · no dither');
                    }
                    job.push(`Export ${line}`);
                }

                setMetrics([
                    { label: 'Loudness', chips: loudness },
                    { label: 'Cleaning', chips: cleaning },
                    { label: 'Job', chips: job },
                    { label: '', chips: warnings },
                ]);
                report.show(mm.spectra);
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
            processBtn.textContent = processLabel();
            progressEl.hidden = true;
        }
    });

}
