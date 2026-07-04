// single.js — Orchestrates the Single-File tab.

import { renderControls } from './controls.js';
import {
    installSyncedGroup, setAudioSource, makePreviewModeController,
} from './players.js';
import { initPresetSelect, presetToSliderValues, runAutoDetect } from './preset.js';
import {
    submitProcess, openSSE, fetchMetrics, resultUrl,
    uploadFile, dropSession, renderPreview, previewUrl,
} from './api.js';
import { makeSettingsSaver, loadSettings } from './settings.js';
import { openHelp } from './help.js';


const PREVIEW_DEBOUNCE_MS = 250;


export async function initSingleTab() {
    const $ = (id) => document.getElementById(id);

    const dropzone     = $('dropzone');
    const fileInput    = $('file-input');
    const pickBtn      = $('pick-file-btn');
    const selectedFile = $('selected-file');
    const presetSelect = $('preset-select');
    const presetDesc   = $('preset-desc');
    const autoBtn      = $('auto-detect-btn');
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
    function setMetrics(text) {
        const t = text == null ? '' : String(text);
        metricsBox.textContent = t;
        metricsBox.hidden = t.length === 0;
    }
    const autoDetectResults = $('auto-detect-results');
    const downloadLink = $('download-link');

    const previewToggle  = $('preview-toggle');
    const previewControls = $('preview-controls');
    const previewWindow  = $('preview-window');
    const previewHereBtn = $('preview-here-btn');
    const previewStatus  = $('preview-status');

    const syncGroup = installSyncedGroup([audioOrig, audioProc, audioDiff]);
    const previewMode = makePreviewModeController(syncGroup);

    const saveSettings = makeSettingsSaver();

    // ── Preview state ────────────────────────────────────────────────
    // Held across the entire single-tab lifetime; reset on file change.
    const previewState = {
        sessionId: null,
        durationS: 0,
        active: false,
        anchorS: 0,        // start of the loop window in source time
        windowS: 10,
        renderInflight: null,  // AbortController for the in-flight render
        renderPending: false,
        debounceTimer: null,
        originalBlobUrl: null,
        savedTime: 0,
    };

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

    // ── File selection ────────────────────────────────────────────────
    let currentFile = null;

    function adoptFile(file) {
        currentFile = file;
        selectedFile.hidden = false;
        selectedFile.textContent = `${file.name}  (${(file.size/1048576).toFixed(1)} MB)`;
        processBtn.disabled = false;
        setMetrics('');
        if (downloadLink) downloadLink.hidden = true;

        // Tear down any prior preview session and reset preview UI.
        teardownPreviewSession();
        if (previewToggle.checked) previewToggle.checked = false;
        applyPreviewToggle(false);

        if (previewState.originalBlobUrl) {
            try { URL.revokeObjectURL(previewState.originalBlobUrl); } catch (_) {}
        }
        previewState.originalBlobUrl = URL.createObjectURL(file);
        audioOrig.src = previewState.originalBlobUrl;
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

        // Top pick
        const top = ranked[0];
        const topBlock = document.createElement('div');
        topBlock.className = 'ad-top';

        const topRow = document.createElement('div');
        topRow.className = 'ad-top-row';

        const lbl = document.createElement('div');
        lbl.className = 'ad-label-block';
        const eyebrow = document.createElement('div');
        eyebrow.className = 'ad-eyebrow';
        eyebrow.textContent = 'Suggested preset';
        const name = document.createElement('div');
        name.className = 'ad-name';
        name.textContent = top.label || labelOf(top.name);
        lbl.appendChild(eyebrow);
        lbl.appendChild(name);

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

        topRow.appendChild(lbl);
        topRow.appendChild(confWrap);
        topBlock.appendChild(topRow);

        if (top.reason) {
            const reason = document.createElement('p');
            reason.className = 'ad-reason';
            reason.textContent = top.reason;
            topBlock.appendChild(reason);
        }

        // Timeline sparkline
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
        topBlock.appendChild(tlEl);

        autoDetectResults.appendChild(topBlock);

        // Alternates (rank 2 and 3)
        const alts = ranked.slice(1, 3);
        if (alts.length > 0) {
            const altsLabel = document.createElement('div');
            altsLabel.className = 'ad-alts-label';
            altsLabel.textContent = 'Also consider';
            autoDetectResults.appendChild(altsLabel);

            const altsList = document.createElement('div');
            altsList.className = 'ad-alts';
            for (const a of alts) {
                const row = document.createElement('div');
                row.className = 'ad-alt';

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

                row.appendChild(info);
                row.appendChild(apct);
                row.appendChild(apply);
                altsList.appendChild(row);
            }
            autoDetectResults.appendChild(altsList);
        }
    }

    autoBtn.addEventListener('click', async () => {
        if (!currentFile) {
            showAutoDetectError('Select a file first.');
            return;
        }
        const originalLabel = autoBtn.textContent;
        autoBtn.textContent = 'Analysing…';
        autoBtn.disabled = true;
        try {
            const r = await runAutoDetect(currentFile);
            applyDetectedPreset(r.preset);
            renderAutoDetect(r);
        } catch (e) {
            showAutoDetectError(`Auto-detect failed: ${e.message}`);
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

    function fmtTime(t) {
        if (!Number.isFinite(t) || t < 0) return '0:00';
        const m = Math.floor(t / 60);
        const s = Math.floor(t % 60);
        return `${m}:${s.toString().padStart(2, '0')}`;
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

    async function ensurePreviewSession() {
        if (previewState.sessionId) return previewState.sessionId;
        if (!currentFile) return null;
        setPreviewStatus('Uploading for preview…');
        try {
            const r = await uploadFile(currentFile);
            previewState.sessionId = r.session_id;
            previewState.durationS = r.duration_s;
            return r.session_id;
        } catch (e) {
            setPreviewStatus(`Preview upload failed: ${e.message}`, 'error');
            return null;
        }
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
        const {start, end} = clampWindow(
            previewState.anchorS, winSec, previewState.durationS);

        const ctrl = new AbortController();
        previewState.renderInflight = ctrl;
        const region = `${fmtTime(start)}–${fmtTime(end)}`;
        setPreviewStatus(`Rendering ${region}…`);

        const overrides = controls.getValues();
        const payload = {
            session_id: sid,
            start_s: start,
            end_s: end,
            preset: presetSelect.value,
            preset_strength: currentStrength(),
            overrides,
            preserve_volume: preserveVol.checked,
        };

        try {
            const r = await renderPreview(payload, {signal: ctrl.signal});
            await previewMode.swapLoop({
                processed: previewUrl(sid, r.render_id, 'processed'),
                diff:      previewUrl(sid, r.render_id, 'diff'),
            }, {autoplayActive: true});
            setPreviewStatus(
                `Live · loop ${region} · rendered in ${r.render_ms} ms`,
                'live');
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

    function captureOriginalTime() {
        const t = Number(audioOrig && audioOrig.currentTime);
        return Number.isFinite(t) ? t : 0;
    }

    function applyPreviewToggle(on) {
        previewState.active = !!on;
        previewControls.hidden = !on;
        previewMode.setLooping(on);

        if (on) {
            previewState.anchorS = captureOriginalTime();
            previewState.windowS = parseFloat(previewWindow.value) || 10;
            if (!currentFile) {
                setPreviewStatus('Drop a file first.');
                return;
            }
            doPreviewRender();
        } else {
            setAudioSource(audioProc, '');
            setAudioSource(audioDiff, '');
            setPreviewStatus(currentFile
                ? 'Live preview off — Original plays the full track.'
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
        // Read from the always-full-length Original player and re-anchor.
        previewState.anchorS = captureOriginalTime();
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
            const job = await submitProcess(
                currentFile,
                {
                    preset: presetSelect.value,
                    preset_strength: currentStrength(),
                    overrides,
                },
                outputFormat.value,
                preserveVol.checked,
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

            setAudioSource(audioProc, resultUrl(job.job_id, 'processed'));
            setAudioSource(audioDiff, resultUrl(job.job_id, 'diff'));
            syncGroup.reset();
            syncGroup.setActive(audioOrig);

            downloadLink.href = resultUrl(job.job_id, 'processed');
            downloadLink.hidden = false;

            const m = await fetchMetrics(job.job_id);
            if (m && m.metrics) {
                const mm = m.metrics;
                let txt =
                    `Input:    peak ${mm.input.peak_dbfs.toFixed(1)} dBFS   rms ${mm.input.rms_dbfs.toFixed(1)} dBFS\n` +
                    `Output:   peak ${mm.output.peak_dbfs.toFixed(1)} dBFS   rms ${mm.output.rms_dbfs.toFixed(1)} dBFS\n` +
                    `Duration: ${mm.duration_s.toFixed(1)}s   ${mm.sample_rate} Hz   ${mm.channels}ch`;

                const diag = mm.diagnostic;
                if (diag && diag.before && diag.after) {
                    const fmt = (v, digits = 2) =>
                        (v == null || Number.isNaN(v)) ? 'n/a' : v.toFixed(digits);
                    const b = diag.before;
                    const a = diag.after;
                    const bRms = fmt(b.band_5_8k_rms_db, 1);
                    const aRms = fmt(a.band_5_8k_rms_db, 1);
                    const bAm = fmt(b.band_5_8k_am_depth);
                    const aAm = fmt(a.band_5_8k_am_depth);
                    txt += `\n\n5-8 kHz energy:   ${bRms} dB → ${aRms} dB`;
                    txt += `\n5-8 kHz AM depth: ${bAm} → ${aAm}`;
                    if (Array.isArray(a.top_peaks) && a.top_peaks.length) {
                        const peaks = a.top_peaks
                            .slice(0, 3)
                            .map(pk => `${(pk.hz / 1000).toFixed(2)}k +${fmt(pk.excess_db, 1)}dB`)
                            .join(', ');
                        txt += `\nTop surviving peaks: ${peaks}`;
                    } else {
                        txt += `\nTop surviving peaks: none`;
                    }
                }

                setMetrics(txt);
            }
        } catch (e) {
            setMetrics(`Error: ${e.message}`);
        } finally {
            processBtn.disabled = false;
            processBtn.textContent = originalLabel;
            progressEl.hidden = true;
        }
    });

}
