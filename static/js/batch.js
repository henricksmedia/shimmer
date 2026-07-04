// batch.js — Orchestrates the Batch tab.

import { fetchPresets, postBatchStream, browseFolder } from './api.js';

export async function initBatchTab() {
    const $ = (id) => document.getElementById(id);
    const inputFolder  = $('batch-input');
    const outputFolder = $('batch-output');
    const browseInputBtn  = $('browse-input-btn');
    const browseOutputBtn = $('browse-output-btn');
    const presetSelect = $('batch-preset');
    const presetGroup  = $('batch-preset-group');
    const formatSelect = $('batch-format');
    const preserveVol  = $('batch-preserve-vol');
    const runBtn       = $('batch-btn');
    const logEl        = $('batch-log');
    const strengthEl   = $('batch-strength');
    const strengthValEl = $('batch-strength-value');

    // Preset mode radio buttons
    const modeRadios = document.querySelectorAll('input[name="batch-mode"]');

    // ── Populate presets ──────────────────────────────────────────────
    const {presets, default: def} = await fetchPresets();
    presetSelect.innerHTML = '';
    const visiblePresets = presets.filter(p => p.visible !== false);
    for (const p of visiblePresets) {
        const opt = document.createElement('option');
        opt.value = p.name;
        opt.textContent = p.label || p.name;
        presetSelect.appendChild(opt);
    }
    presetSelect.value = def;

    // ── Mode toggle ──────────────────────────────────────────────────
    function getMode() {
        for (const r of modeRadios) {
            if (r.checked) return r.value;
        }
        return 'fixed';
    }

    function applyMode() {
        const auto = getMode() === 'auto';
        presetGroup.style.display = auto ? 'none' : '';
    }

    for (const r of modeRadios) {
        r.addEventListener('change', applyMode);
    }
    applyMode();

    // ── Strength display ─────────────────────────────────────────────
    function renderStrength() {
        const v = parseFloat(strengthEl.value);
        strengthValEl.textContent = `${Math.round((Number.isFinite(v) ? v : 1) * 100)}%`;
    }
    strengthEl.addEventListener('input', renderStrength);
    renderStrength();

    // ── Browse buttons ───────────────────────────────────────────────
    async function handleBrowse(inputEl, title) {
        const btn = inputEl === inputFolder ? browseInputBtn : browseOutputBtn;
        btn.disabled = true;
        try {
            const path = await browseFolder({
                initialDir: inputEl.value.trim() || undefined,
                title,
            });
            if (path) inputEl.value = path;
        } finally {
            btn.disabled = false;
        }
    }
    browseInputBtn.addEventListener('click', () =>
        handleBrowse(inputFolder, 'Select input folder'));
    browseOutputBtn.addEventListener('click', () =>
        handleBrowse(outputFolder, 'Select output folder'));

    // ── Log helpers ──────────────────────────────────────────────────
    function append(line, cls) {
        const span = document.createElement('span');
        if (cls) span.className = cls;
        span.textContent = line + '\n';
        logEl.appendChild(span);
        logEl.scrollTop = logEl.scrollHeight;
    }

    // ── Run batch ────────────────────────────────────────────────────
    runBtn.addEventListener('click', () => {
        if (!inputFolder.value.trim()) {
            append('Please provide an input folder.', 'err');
            return;
        }
        logEl.innerHTML = '';
        runBtn.disabled = true;
        const originalLabel = runBtn.textContent;
        runBtn.textContent = 'Processing…';

        const autoDetect = getMode() === 'auto';
        const strength = parseFloat(strengthEl.value);

        const payload = {
            input_folder: inputFolder.value.trim(),
            output_folder: outputFolder.value.trim(),
            preset: presetSelect.value,
            output_format: formatSelect.value,
            preserve_volume: preserveVol.checked,
            auto_detect: autoDetect,
            preset_strength: Number.isFinite(strength) ? strength : 1.0,
        };

        postBatchStream(payload, {
            onMessage: (msg) => {
                if (msg.type === 'start') {
                    const mode = autoDetect
                        ? 'Auto-detect per file'
                        : `Preset: ${msg.preset}`;
                    append(`Found ${msg.total} file(s).  ${mode}`, 'head');
                    append(`Output → ${msg.output_folder}`);
                    if (strength !== 1.0) {
                        append(`Preset strength: ${Math.round(strength * 100)}%`);
                    }
                } else if (msg.type === 'file_start') {
                    append(`[${msg.index + 1}]  ${msg.name} …`);
                } else if (msg.type === 'file_done') {
                    let line =
                        `   done  ${msg.duration_s.toFixed(1)}s   ` +
                        `peak ${msg.peak_in_db.toFixed(1)} → ${msg.peak_out_db.toFixed(1)} dBFS`;

                    if (msg.detected_preset) {
                        const pct = msg.detected_confidence != null
                            ? ` (${Math.round(msg.detected_confidence * 100)}%)`
                            : '';
                        line += `   preset: ${msg.detected_label || msg.detected_preset}${pct}`;
                    }

                    append(line, 'ok');
                } else if (msg.type === 'file_error') {
                    append(`   FAILED: ${msg.error}`, 'err');
                } else if (msg.type === 'end') {
                    append(msg.message || 'Batch complete.', 'head');
                }
            },
            onError: (e) => {
                append(`Stream error: ${e.message || e}`, 'err');
                runBtn.disabled = false;
                runBtn.textContent = originalLabel;
            },
            onDone: () => {
                runBtn.disabled = false;
                runBtn.textContent = originalLabel;
            },
        });
    });
}
