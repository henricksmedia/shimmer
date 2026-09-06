// batch.js — Orchestrates the Batch tab.

import { fetchPresets, postBatchStream, browseFolder, fetchSettings, fetchToneFamilies } from './api.js';

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
    const trimSilence  = $('batch-trim-silence');
    const applyEq      = $('batch-apply-eq');
    const autoEq       = $('batch-auto-eq');
    const toneFamily   = $('batch-tone-family');
    const writeTags    = $('batch-tags');
    (async () => {
        if (!toneFamily) return;
        const fams = await fetchToneFamilies();
        const saved = (await fetchSettings().catch(() => null)) || {};
        toneFamily.innerHTML = '';
        (fams.length ? fams : [{key: 'neutral', label: 'Neutral'}]).forEach((f) => {
            const o = document.createElement('option');
            o.value = f.key;
            o.textContent = f.label;
            if (f.blurb) o.title = f.blurb;
            toneFamily.appendChild(o);
        });
        if (saved.tone && saved.tone.family) toneFamily.value = saved.tone.family;
    })();
    const masterEnabled = $('batch-master-enabled');
    const masterTarget = $('batch-master-target');
    const masterIntensity = $('batch-master-intensity');
    const masterTilt = $('batch-master-tilt');
    const albumMode  = $('batch-album-mode');
    const albumRow   = $('batch-album-row');
    const runBtn       = $('batch-btn');

    // Album mode only means something when mastering is on.
    function syncAlbumRow() {
        const on = !!(masterEnabled && masterEnabled.checked);
        if (albumRow) albumRow.classList.toggle('is-off', !on);
        if (albumMode) albumMode.disabled = !on;
    }
    if (masterEnabled) masterEnabled.addEventListener('change', syncAlbumRow);
    syncAlbumRow();
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
    runBtn.addEventListener('click', async () => {
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

        // The Master tab persists its EQ, tags and Tone choices on every
        // edit; reuse them here.
        let eqPayload = null;
        const saved = (await fetchSettings()) || {};
        if (applyEq && applyEq.checked) {
            if (saved && saved.eq && saved.eq.enabled &&
                Array.isArray(saved.eq.bands) && saved.eq.bands.length) {
                eqPayload = saved.eq;
            } else {
                append('No EQ bands configured on the Single File tab — EQ skipped.', 'err');
            }
        }

        const payload = {
            input_folder: inputFolder.value.trim(),
            output_folder: outputFolder.value.trim(),
            preset: presetSelect.value,
            output_format: formatSelect.value,
            preserve_volume: preserveVol.checked && !(masterEnabled && masterEnabled.checked),
            trim_silence: trimSilence.checked,
            auto_detect: autoDetect,
            // Fixed-line repair scans each file and notches its lines first.
            static_repair: true,
            preset_strength: Number.isFinite(strength) ? strength : 1.0,
            mastering: {
                enabled: masterEnabled ? masterEnabled.checked : false,
                target: masterTarget ? masterTarget.value : 'streaming',
                intensity: masterIntensity ? masterIntensity.value : 'med',
                tilt: masterTilt ? masterTilt.value : 'neutral',
            },
            album_mode: !!(albumMode && albumMode.checked && masterEnabled && masterEnabled.checked),
        };
        if (eqPayload) payload.eq = eqPayload;
        payload.auto_eq = !!(autoEq && autoEq.checked);
        payload.tone_family = (toneFamily && toneFamily.value) ||
            (saved.tone && saved.tone.family) || 'neutral';
        if (writeTags && writeTags.checked) {
            const t = saved.tags || {};
            payload.tags = {
                enabled: t.enabled !== false,
                artist: t.artist || '', album_artist: t.album_artist || '',
                album: t.album || '', genre: t.genre || '', year: t.year || '',
                copyright: t.copyright || '', isrc: t.isrc || '',
                mode: t.keep === false ? 'overwrite' : 'fill',
                notes: t.notes !== false,
            };
        } else {
            payload.tags = { enabled: false };
        }

        const f1 = (v) => (v == null || !Number.isFinite(v)) ? 'n/a' : v.toFixed(1);
        const signed = (v) => (v > 0 ? '+' : '') + v.toFixed(1);
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
                    if (eqPayload) {
                        append(`EQ: ${eqPayload.bands.length} band(s) from Single File tab`);
                    }
                    if (msg.album_mode) {
                        append('Album mode: one gain for the whole record; the loudest track lands on the target and the others keep their distance.');
                    }
                } else if (msg.type === 'phase') {
                    append(msg.message || `Pass: ${msg.phase}`, 'head');
                } else if (msg.type === 'album') {
                    if (msg.loudest_lufs == null) {
                        append('Album: no track could be measured.', 'err');
                    } else {
                        append(`Album: loudest is ${msg.loudest} at ${f1(msg.loudest_lufs)} LUFS → ` +
                               `one gain of ${signed(msg.gain_db)} dB brings it to ${f1(msg.target_lufs)} LUFS` +
                               `   album loudness ${f1(msg.album_lufs)} LUFS` +
                               (msg.spread_lu != null ? `   ${f1(msg.spread_lu)} LU from loudest to quietest` : ''), 'head');
                    }
                } else if (msg.type === 'file_start') {
                    append(`[${msg.index + 1}]  ${msg.name} …`);
                } else if (msg.type === 'file_done' && msg.phase === 'clean') {
                    let line = `   cleaned  ${msg.duration_s.toFixed(1)}s   ` +
                        `${f1(msg.lufs_clean)} LUFS · TP ${f1(msg.true_peak_clean)} dBTP`;
                    if (msg.detected_preset) {
                        const pct = msg.detected_confidence != null
                            ? ` (${Math.round(msg.detected_confidence * 100)}%)`
                            : '';
                        line += `   preset: ${msg.detected_label || msg.detected_preset}${pct}`;
                        if (Number.isFinite(msg.effective_strength)) {
                            line += ` @ ${Math.round(msg.effective_strength * 100)}%`;
                        }
                    }
                    if (msg.tone_moves != null) {
                        line += `   EQ: ${msg.tone_moves} move${msg.tone_moves === 1 ? '' : 's'}`;
                    }
                    append(line, 'ok');
                } else if (msg.type === 'file_done') {
                    let line =
                        `   done  ${msg.duration_s.toFixed(1)}s   ` +
                        `peak ${msg.peak_in_db.toFixed(1)} → ${msg.peak_out_db.toFixed(1)} dBFS`;
                    if (msg.lufs_out != null) {
                        line += `   ${f1(msg.lufs_out)} LUFS · TP ${f1(msg.true_peak_out)} dBTP`;
                        if (Number.isFinite(msg.limiter_gr_db) && msg.limiter_gr_db < -0.05) {
                            line += ` · limiter ${f1(msg.limiter_gr_db)} dB`;
                        }
                    }
                    if (msg.release && msg.release.status) {
                        const r = msg.release;
                        line += r.status === 'pass' ? '   release ✓'
                            : `   release ${r.status === 'fail' ? '✕' : '⚠'} ${(r.flags || []).join(', ')}`;
                    }

                    if (msg.detected_preset) {
                        const pct = msg.detected_confidence != null
                            ? ` (${Math.round(msg.detected_confidence * 100)}%)`
                            : '';
                        line += `   preset: ${msg.detected_label || msg.detected_preset}${pct}`;
                        if (Number.isFinite(msg.effective_strength)) {
                            line += ` @ ${Math.round(msg.effective_strength * 100)}%`;
                        }
                    }

                    if (msg.trim && msg.trim.enabled) {
                        const cut = (msg.trim.cut_head_s || 0) + (msg.trim.cut_tail_s || 0);
                        if (cut > 0.05) line += `   trimmed ${cut.toFixed(1)}s`;
                    }
                    if (msg.tone_moves != null) {
                        line += `   EQ: ${msg.tone_moves} move${msg.tone_moves === 1 ? '' : 's'}`;
                    }
                    if (msg.tags_written) line += '   tags written';

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
