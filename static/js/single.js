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
    const masteringReadout = $('mastering-readout');
    const preserveVolCard = $('preserve-vol-card');
    const abLoudnessMatch = $('ab-loudness-match');
    const stepUpload = $('step-upload');
    const stepAnalyze = $('step-analyze');
    const stepProcess = $('step-process');
    const slidersHost  = $('sliders-host');
    const preserveVol  = $('preserve-vol');
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

    let lastAnalysis = null;
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
        windowS: 10,
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

    player = createUnifiedPlayer({
        els: { original: audioOrig, processed: audioProc, removed: audioDiff },
        canvas: $('player-canvas'),
        playBtn: $('player-play'),
        timeLabel: $('player-time'),
        tabsHost: $('track-tabs'),
        modeWaveBtn: $('viz-mode-wave'),
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
        if (abMatchNote) {
            abMatchNote.textContent =
                abLoudnessMatch.checked && d == null ? '(waiting for render)' : '';
        }
        const dd = d == null ? 0 : d;
        // Attenuate whichever side is louder so the comparison is fair.
        // Removed is an audition track and stays out of the match.
        player.setLoudnessMatch(abLoudnessMatch.checked, {
            original:  dd < 0 ? dd : 0,
            processed: dd > 0 ? -dd : 0,
            removed:   0,
        });
    }

    // Wire initial slider values from the default preset.
    controls.setValues(presetToSliderValues(
        byName.get(defaultName), currentStrength()));

    // Restore saved settings on top of the default.
    const saved = await loadSettings();
    if (saved && typeof saved.preset_strength === 'number') {
        strengthEl.value = String(saved.preset_strength);
        renderStrengthBadge();
    }
    if (saved && saved.preset && byName.has(saved.preset)) {
        presetSelect.value = saved.preset;
        presetSelect.dispatchEvent(new Event('change'));
    }
    if (saved && saved.sliders) controls.setValues(saved.sliders);
    if (saved && typeof saved.preserve_volume === 'boolean') {
        preserveVol.checked = saved.preserve_volume;
    }
    if (saved && saved.output_format) outputFormat.value = saved.output_format;
    if (saved && typeof saved.ab_loudness_match === 'boolean') {
        abLoudnessMatch.checked = saved.ab_loudness_match;
    }
    if (saved && saved.mastering) {
        if (typeof saved.mastering.enabled === 'boolean') {
            masterEnabled.checked = saved.mastering.enabled;
        }
        if (saved.mastering.target) masterTarget.value = saved.mastering.target;
        if (saved.mastering.intensity) masterIntensity.value = saved.mastering.intensity;
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

    function applyDetectedPreset(presetName) {
        if (!presetName || !byName.has(presetName)) return;
        presetSelect.value = presetName;
        presetSelect.dispatchEvent(new Event('change'));
    }

    function showAutoDetectError(msg) {
        autoDetectResults.hidden = false;
        autoDetectResults.innerHTML = '';
        const err = document.createElement('div');
        err.className = 'ad-error';
        err.textContent = msg;
        autoDetectResults.appendChild(err);
    }

    // Close any open auto-detect details popover on outside click.
    document.addEventListener('click', (e) => {
        if (!autoDetectResults.contains(e.target)) {
            const pop = autoDetectResults.querySelector('.ad-pop');
            if (pop) pop.hidden = true;
        }
    });

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

        // Slim summary row: eyebrow + name + confidence + Details.
        const top = ranked[0];
        const row = document.createElement('div');
        row.className = 'ad-row';

        const eyebrow = document.createElement('div');
        eyebrow.className = 'ad-eyebrow';
        eyebrow.textContent = 'Suggested';
        const name = document.createElement('div');
        name.className = 'ad-name';
        name.textContent = top.label || labelOf(top.name);
        name.title = name.textContent;

        const confWrap = document.createElement('div');
        confWrap.className = 'ad-confidence-wrap';
        const conf = document.createElement('div');
        conf.className = 'ad-confidence';
        const fill = document.createElement('div');
        fill.className = 'ad-confidence-fill';
        const pct = Math.round((top.confidence || 0) * 100);
        fill.style.width = `${pct}%`;
        conf.appendChild(fill);
        const pctText = document.createElement('div');
        pctText.className = 'ad-confidence-pct';
        pctText.textContent = `${pct}%`;
        confWrap.appendChild(conf);
        confWrap.appendChild(pctText);

        const detailsBtn = document.createElement('button');
        detailsBtn.type = 'button';
        detailsBtn.className = 'btn btn-ghost ad-details-btn';
        detailsBtn.textContent = 'Details';

        row.appendChild(eyebrow);
        row.appendChild(name);
        row.appendChild(confWrap);
        row.appendChild(detailsBtn);
        autoDetectResults.appendChild(row);

        // Details popover: reason, timeline sparkline, alternates.
        const pop = document.createElement('div');
        pop.className = 'ad-pop';
        pop.hidden = true;

        if (top.reason) {
            const reason = document.createElement('p');
            reason.className = 'ad-reason';
            reason.textContent = top.reason;
            pop.appendChild(reason);
        }

        const tl = r.timeline && Array.isArray(r.timeline.intensity)
            ? r.timeline.intensity : [];
        const tlEl = document.createElement('div');
        tlEl.className = 'ad-timeline';
        if (tl.length === 0) {
            const empty = document.createElement('div');
            empty.className = 'ad-timeline-empty';
            empty.textContent = '(timeline unavailable)';
            tlEl.appendChild(empty);
        } else {
            for (const v of tl) {
                const bar = document.createElement('div');
                bar.className = 'ad-timeline-bar';
                if (v >= 0.4) bar.classList.add('hot');
                const h = Math.max(2, Math.round(v * 24)); // px
                bar.style.height = `${h}px`;
                bar.title = `intensity ${(v * 100).toFixed(0)}%`;
                tlEl.appendChild(bar);
            }
        }
        pop.appendChild(tlEl);

        // Alternates (rank 2 and 3)
        const alts = ranked.slice(1, 3);
        if (alts.length > 0) {
            const altsLabel = document.createElement('div');
            altsLabel.className = 'ad-alts-label';
            altsLabel.textContent = 'Also consider';
            pop.appendChild(altsLabel);

            const altsList = document.createElement('div');
            altsList.className = 'ad-alts';
            for (const a of alts) {
                const alt = document.createElement('div');
                alt.className = 'ad-alt';

                const info = document.createElement('div');
                info.className = 'ad-alt-info';
                const an = document.createElement('div');
                an.className = 'ad-alt-name';
                an.textContent = a.label || labelOf(a.name);
                const ar = document.createElement('div');
                ar.className = 'ad-alt-reason';
                ar.textContent = a.reason || '';
                ar.title = a.reason || '';
                info.appendChild(an);
                info.appendChild(ar);

                const apct = document.createElement('div');
                apct.className = 'ad-alt-pct';
                apct.textContent = `${Math.round((a.confidence || 0) * 100)}%`;

                const apply = document.createElement('button');
                apply.type = 'button';
                apply.className = 'btn btn-ghost';
                apply.textContent = 'Apply';
                apply.addEventListener('click', () => {
                    applyDetectedPreset(a.name);
                });

                alt.appendChild(info);
                alt.appendChild(apct);
                alt.appendChild(apply);
                altsList.appendChild(alt);
            }
            pop.appendChild(altsList);
        }

        autoDetectResults.appendChild(pop);
        detailsBtn.addEventListener('click', () => {
            pop.hidden = !pop.hidden;
        });
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
            applyDetectedPreset(r.preset);
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
    function pushSettings() {
        saveSettings({
            preset: presetSelect.value,
            preset_strength: currentStrength(),
            sliders: controls.getValues(),
            preserve_volume: preserveVol.checked,
            output_format: outputFormat.value,
            mastering: masteringPayload(),
            ab_loudness_match: abLoudnessMatch.checked,
        });
    }
    preserveVol.addEventListener('change', () => {
        pushSettings();
        schedulePreviewRender();
    });
    outputFormat.addEventListener('change', pushSettings);

    // ── Live preview ──────────────────────────────────────────────────
    // Original keeps the full file; only Processed and Removed loop a
    // small slice that re-renders on every slider change.

    function setPreviewStatus(text, kind = '') {
        previewStatus.textContent = text;
        previewStatus.classList.remove('live', 'error');
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

    async function ensurePreviewSession() {
        if (previewState.sessionId) return previewState.sessionId;
        if (!currentFile) return null;
        setPreviewStatus('Uploading for preview…');
        try {
            const r = await uploadFile(currentFile);
            previewState.sessionId = r.session_id;
            previewState.durationS = r.duration_s;
            if (r.analysis) {
                lastAnalysis = r.analysis;
                renderAnalysisReadout(r.analysis);
            }
            return r.session_id;
        } catch (e) {
            setPreviewStatus(`Preview upload failed: ${e.message}`, 'error');
            return null;
        }
    }

    // Install a render (fresh or cached) into the player and refresh the
    // match gains from the slice loudness in its metadata.
    function applyPreviewResult(entry, start, end, region, note) {
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
        };

        // Decoded-render cache: same window + same params = instant swap.
        const cacheKey = JSON.stringify([
            start, end, payload.preset, payload.preset_strength,
            overrides, payload.preserve_volume, payload.mastering,
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
        setPreviewStatus(`Rendering ${region}…`);

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
        if (!previewState.active) return;
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
            // Auto mode resolves to the artifact-hot region inside
            // doPreviewRender; the playhead is the fallback anchor.
            previewState.anchorS = capturePlayheadTime();
            previewState.windowS = parseFloat(previewWindow.value) || 10;
            if (!currentFile) {
                setPreviewStatus('Drop a file first.');
                return;
            }
            applyLoudnessMatch();  // switch match source to preview LUFS
            doPreviewRender();
        } else {
            player.exitPreview();
            player.setSource('processed', null);
            player.setSource('removed', null);
            applyLoudnessMatch();  // back to full-run metrics
            setPreviewStatus(currentFile
                ? 'Live preview off — playhead runs the full track.'
                : 'Drop a file to start.');
        }
    }

    previewToggle.addEventListener('change', () => {
        applyPreviewToggle(previewToggle.checked);
    });
    previewWindow.addEventListener('change', () => {
        previewState.windowS = parseFloat(previewWindow.value) || 10;
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

    // ── Process ───────────────────────────────────────────────────────
    processBtn.addEventListener('click', async () => {
        if (!currentFile) return;
        // Full-file processing replaces the slice players; turn live
        // preview off so the loop state doesn't fight the new sources.
        if (previewState.active) {
            previewToggle.checked = false;
            applyPreviewToggle(false);
        }
        processBtn.disabled = true;
        const originalLabel = processBtn.textContent;
        processBtn.textContent = 'Processing…';
        progressEl.hidden = false;
        progressEl.value = 0;
        setMetrics('Uploading…');

        try {
            const overrides = controls.getValues();
            const paramsBody = {
                preset: presetSelect.value,
                preset_strength: currentStrength(),
                overrides,
                mastering: masteringPayload(),
            };
            if (lastAnalysis) paramsBody.mastering_analysis = lastAnalysis;

            const job = await submitProcess(
                currentFile,
                paramsBody,
                outputFormat.value,
                preserveVol.checked && !masterEnabled.checked,
            );

            await new Promise((resolve, reject) => {
                openSSE(`/api/progress/${job.job_id}`, {
                    onMessage: (msg) => {
                        if (typeof msg.fraction === 'number') {
                            progressEl.value = msg.fraction;
                        }
                        if (msg.error) reject(new Error(msg.error));
                    },
                    onDone: (msg) => msg.error ? reject(new Error(msg.error)) : resolve(),
                    onError: (e) => reject(e),
                });
            });

            await player.loadFromJob(job.job_id);
            player.setTrack('processed');

            downloadLink.href = resultUrl(job.job_id, 'processed');
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

                fullMatchDb = null;
                const mast = mm.mastering;
                if (mast && mast.enabled && mast.before && mast.after) {
                    chips.push(
                        `LUFS ${mast.before.lufs_i?.toFixed(1)} → ${mast.after.lufs_i?.toFixed(1)} (target ${mast.target_lufs})`);
                    chips.push(
                        `TP ${mast.before.true_peak_dbtp?.toFixed(1)} → ${mast.after.true_peak_dbtp?.toFixed(1)} dBTP`);
                    if (mast.limiter && mast.limiter.max_gain_reduction_db != null) {
                        chips.push(
                            `Limiter ${mast.limiter.max_gain_reduction_db.toFixed(1)} dB max GR`);
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
        } catch (e) {
            setMetrics(`Error: ${e.message}`);
        } finally {
            processBtn.disabled = false;
            processBtn.textContent = originalLabel;
            progressEl.hidden = true;
        }
    });

}
