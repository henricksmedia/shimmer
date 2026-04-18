// batch.js — Orchestrates the Batch tab.

import { fetchPresets, postBatchStream } from './api.js';

export async function initBatchTab() {
    const $ = (id) => document.getElementById(id);
    const inputFolder  = $('batch-input');
    const outputFolder = $('batch-output');
    const presetSelect = $('batch-preset');
    const formatSelect = $('batch-format');
    const preserveVol  = $('batch-preserve-vol');
    const runBtn       = $('batch-btn');
    const logEl        = $('batch-log');

    const {presets, default: def} = await fetchPresets();
    presetSelect.innerHTML = '';
    for (const p of presets) {
        const opt = document.createElement('option');
        opt.value = p.name;
        opt.textContent = p.name;
        presetSelect.appendChild(opt);
    }
    presetSelect.value = def;

    function append(line, cls) {
        const span = document.createElement('span');
        if (cls) span.className = cls;
        span.textContent = line + '\n';
        logEl.appendChild(span);
        logEl.scrollTop = logEl.scrollHeight;
    }

    runBtn.addEventListener('click', () => {
        if (!inputFolder.value.trim()) {
            append('Please provide an input folder.', 'err');
            return;
        }
        logEl.innerHTML = '';
        runBtn.disabled = true;
        const originalLabel = runBtn.textContent;
        runBtn.textContent = 'Processing…';

        const payload = {
            input_folder: inputFolder.value.trim(),
            output_folder: outputFolder.value.trim(),
            preset: presetSelect.value,
            output_format: formatSelect.value,
            preserve_volume: preserveVol.checked,
        };

        postBatchStream(payload, {
            onMessage: (msg) => {
                if (msg.type === 'start') {
                    append(`Found ${msg.total} file(s).  Output → ${msg.output_folder}`, 'head');
                } else if (msg.type === 'file_start') {
                    append(`[${msg.index + 1}]  ${msg.name} …`);
                } else if (msg.type === 'file_done') {
                    append(
                        `   done  ${msg.duration_s.toFixed(1)}s   ` +
                        `peak ${msg.peak_in_db.toFixed(1)} → ${msg.peak_out_db.toFixed(1)} dBFS`,
                        'ok');
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
