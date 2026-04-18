// single.js — Orchestrates the Single-File tab.

import { renderControls } from './controls.js';
import { installSyncedGroup, setAudioSource } from './players.js';
import { initPresetSelect, presetToSliderValues, runAutoDetect } from './preset.js';
import {
    submitProcess, openSSE, fetchMetrics, resultUrl,
} from './api.js';
import { makeSettingsSaver, loadSettings } from './settings.js';
import { openHelp } from './help.js';


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

    const audioOrig = $('audio-original');
    const audioProc = $('audio-processed');
    const audioDiff = $('audio-diff');
    const metricsBox = $('metrics-box');
    const downloadLink = $('download-link');

    const syncGroup = installSyncedGroup([audioOrig, audioProc, audioDiff]);

    const saveSettings = makeSettingsSaver();

    const {byName, defaultName} = await initPresetSelect(presetSelect, {
        descEl: presetDesc,
        onChange: (preset) => {
            controls.setValues(presetToSliderValues(preset));
            pushSettings();
        },
    });

    const controls = renderControls(
        slidersHost,
        () => pushSettings(),
        (specKey) => openHelp('controls', specKey),
    );

    // Wire initial slider values from the default preset.
    controls.setValues(presetToSliderValues(byName.get(defaultName)));

    // Restore saved settings on top of the default.
    const saved = await loadSettings();
    if (saved && saved.preset && byName.has(saved.preset)) {
        presetSelect.value = saved.preset;
        presetSelect.dispatchEvent(new Event('change'));
    }
    if (saved && saved.sliders) controls.setValues(saved.sliders);
    if (saved && typeof saved.preserve_volume === 'boolean') {
        preserveVol.checked = saved.preserve_volume;
    }
    if (saved && saved.output_format) outputFormat.value = saved.output_format;

    // ── File selection ────────────────────────────────────────────────
    let currentFile = null;

    function adoptFile(file) {
        currentFile = file;
        selectedFile.hidden = false;
        selectedFile.textContent = `${file.name}  (${(file.size/1048576).toFixed(1)} MB)`;
        processBtn.disabled = false;
        audioOrig.src = URL.createObjectURL(file);
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
    autoBtn.addEventListener('click', async () => {
        if (!currentFile) {
            metricsBox.textContent = 'Select a file first.';
            return;
        }
        const originalLabel = autoBtn.textContent;
        autoBtn.textContent = 'Analysing…';
        autoBtn.disabled = true;
        try {
            const r = await runAutoDetect(currentFile);
            if (r.preset && byName.has(r.preset)) {
                presetSelect.value = r.preset;
                presetSelect.dispatchEvent(new Event('change'));
            }
            const ranked = Object.entries(r.scores || {})
                .sort(([,a], [,b]) => b - a)
                .slice(0, 3)
                .map(([n,s]) => `${n} ${s.toFixed(3)}`)
                .join('   ');
            metricsBox.textContent =
                `Suggested: ${r.preset}\n` +
                `Top candidates: ${ranked}\n` +
                `Checkerboard score: ${(r.checkerboard_score||0).toFixed(3)}`;
        } catch (e) {
            metricsBox.textContent = `Auto-detect failed: ${e.message}`;
        } finally {
            autoBtn.textContent = originalLabel;
            autoBtn.disabled = false;
        }
    });

    // ── Persistence wiring ────────────────────────────────────────────
    function pushSettings() {
        saveSettings({
            preset: presetSelect.value,
            sliders: controls.getValues(),
            preserve_volume: preserveVol.checked,
            output_format: outputFormat.value,
        });
    }
    preserveVol.addEventListener('change', pushSettings);
    outputFormat.addEventListener('change', pushSettings);

    // ── Process ───────────────────────────────────────────────────────
    processBtn.addEventListener('click', async () => {
        if (!currentFile) return;
        processBtn.disabled = true;
        const originalLabel = processBtn.textContent;
        processBtn.textContent = 'Processing…';
        progressEl.hidden = false;
        progressEl.value = 0;
        metricsBox.textContent = 'Uploading…';

        try {
            const overrides = controls.getValues();
            const job = await submitProcess(
                currentFile,
                { preset: presetSelect.value, overrides },
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
                metricsBox.textContent =
                    `Input:    peak ${mm.input.peak_dbfs.toFixed(1)} dBFS   rms ${mm.input.rms_dbfs.toFixed(1)} dBFS\n` +
                    `Output:   peak ${mm.output.peak_dbfs.toFixed(1)} dBFS   rms ${mm.output.rms_dbfs.toFixed(1)} dBFS\n` +
                    `Duration: ${mm.duration_s.toFixed(1)}s   ${mm.sample_rate} Hz   ${mm.channels}ch`;
            }
        } catch (e) {
            metricsBox.textContent = `Error: ${e.message}`;
        } finally {
            processBtn.disabled = false;
            processBtn.textContent = originalLabel;
            progressEl.hidden = true;
        }
    });

}
