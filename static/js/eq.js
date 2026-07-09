// eq.js — Parametric EQ panel: interactive response-curve canvas + band
// controls. Mirrors eq.py exactly: RBJ biquads designed at half gain and
// applied zero-phase (forward+backward), so the drawn curve — 2x the
// designed magnitude response — is precisely what the server applies.
//
// Interactions on the canvas:
//   drag node        move band (frequency / gain)
//   scroll on node   adjust Q (bandwidth)
//   double-click     empty space: add a bell · on a node: delete it
//   click            select a band (numeric row below edits the selection)

const FREQ_MIN = 20;
const FREQ_MAX = 20000;
const GAIN_LIMIT = 18;      // hard clamp, mirrors eq.py
const DB_RANGE = 18;        // vertical display range (±)
const Q_MIN = 0.1;
const Q_MAX = 18;
const MAX_BANDS = 12;

export const EQ_TYPES = [
    { key: 'bell',       label: 'Bell',       hasGain: true  },
    { key: 'low_shelf',  label: 'Low shelf',  hasGain: true  },
    { key: 'high_shelf', label: 'High shelf', hasGain: true  },
    { key: 'highpass',   label: 'High-pass',  hasGain: false },
    { key: 'lowpass',    label: 'Low-pass',   hasGain: false },
    { key: 'notch',      label: 'Notch',      hasGain: false },
];
const TYPE_BY_KEY = new Map(EQ_TYPES.map(t => [t.key, t]));

const BAND_COLORS = [
    '#6c5ce7', '#3fbf7f', '#d4a55a', '#d45a9e',
    '#5aa7d4', '#e07070', '#8fd45a', '#b45ad4',
];

// One-click starting points. Each replaces the current band list.
const EQ_PRESETS = [
    { key: 'air',       label: 'Air lift',       bands: [
        { type: 'high_shelf', freq_hz: 11000, gain_db: 2.0, q: 0.707 },
    ]},
    { key: 'demud',     label: 'De-mud',         bands: [
        { type: 'bell', freq_hz: 300, gain_db: -2.5, q: 1.2 },
    ]},
    { key: 'warmth',    label: 'Warmth',         bands: [
        { type: 'low_shelf',  freq_hz: 200,  gain_db: 1.5,  q: 0.707 },
        { type: 'high_shelf', freq_hz: 9000, gain_db: -1.5, q: 0.707 },
    ]},
    { key: 'presence',  label: 'Presence',       bands: [
        { type: 'bell', freq_hz: 3500, gain_db: 2.0, q: 1.4 },
    ]},
    { key: 'vocal',     label: 'Vocal clarity',  bands: [
        { type: 'bell',       freq_hz: 300,   gain_db: -1.5, q: 1.2 },
        { type: 'bell',       freq_hz: 3000,  gain_db: 1.5,  q: 1.4 },
        { type: 'high_shelf', freq_hz: 10000, gain_db: 1.0,  q: 0.707 },
    ]},
    { key: 'rumble',    label: 'Rumble cut',     bands: [
        { type: 'highpass', freq_hz: 30, gain_db: 0, q: 0.707 },
    ]},
    { key: 'telephone', label: 'Lo-fi telephone', bands: [
        { type: 'highpass', freq_hz: 400,  gain_db: 0, q: 0.707 },
        { type: 'lowpass',  freq_hz: 3200, gain_db: 0, q: 0.707 },
    ]},
];

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

function makeBand(over = {}) {
    return {
        type: 'bell', freq_hz: 1000, gain_db: 0, q: 1.0, enabled: true,
        ...over,
    };
}

// ── Biquad design + magnitude response (mirror of eq.py) ─────────────────

function rbjCoeffs(type, f0, sr, gainDb, q) {
    const A = Math.pow(10, gainDb / 40);
    const w0 = 2 * Math.PI * f0 / sr;
    const cw = Math.cos(w0), sw = Math.sin(w0);
    const alpha = sw / (2 * Math.max(Q_MIN, q));
    let b0, b1, b2, a0, a1, a2;
    if (type === 'bell') {
        b0 = 1 + alpha * A; b1 = -2 * cw; b2 = 1 - alpha * A;
        a0 = 1 + alpha / A; a1 = -2 * cw; a2 = 1 - alpha / A;
    } else if (type === 'low_shelf') {
        const s = 2 * Math.sqrt(A) * alpha;
        b0 = A * ((A + 1) - (A - 1) * cw + s);
        b1 = 2 * A * ((A - 1) - (A + 1) * cw);
        b2 = A * ((A + 1) - (A - 1) * cw - s);
        a0 = (A + 1) + (A - 1) * cw + s;
        a1 = -2 * ((A - 1) + (A + 1) * cw);
        a2 = (A + 1) + (A - 1) * cw - s;
    } else if (type === 'high_shelf') {
        const s = 2 * Math.sqrt(A) * alpha;
        b0 = A * ((A + 1) + (A - 1) * cw + s);
        b1 = -2 * A * ((A - 1) + (A + 1) * cw);
        b2 = A * ((A + 1) + (A - 1) * cw - s);
        a0 = (A + 1) - (A - 1) * cw + s;
        a1 = 2 * ((A - 1) - (A + 1) * cw);
        a2 = (A + 1) - (A - 1) * cw - s;
    } else if (type === 'highpass') {
        b0 = (1 + cw) / 2; b1 = -(1 + cw); b2 = (1 + cw) / 2;
        a0 = 1 + alpha; a1 = -2 * cw; a2 = 1 - alpha;
    } else if (type === 'lowpass') {
        b0 = (1 - cw) / 2; b1 = 1 - cw; b2 = (1 - cw) / 2;
        a0 = 1 + alpha; a1 = -2 * cw; a2 = 1 - alpha;
    } else {  // notch
        b0 = 1; b1 = -2 * cw; b2 = 1;
        a0 = 1 + alpha; a1 = -2 * cw; a2 = 1 - alpha;
    }
    return [b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0];
}

// Effective dB response of one band at frequency f: the design response
// doubled, because the server runs the cascade forward AND backward.
function bandResponseDb(band, f, sr) {
    const t = TYPE_BY_KEY.get(band.type);
    const designGain = t && t.hasGain ? band.gain_db / 2 : 0;
    const [b0, b1, b2, a1, a2] = rbjCoeffs(
        band.type, band.freq_hz, sr, designGain, band.q);
    const w = 2 * Math.PI * f / sr;
    const c1 = Math.cos(w), s1 = Math.sin(w);
    const c2 = Math.cos(2 * w), s2 = Math.sin(2 * w);
    const nr = b0 + b1 * c1 + b2 * c2, ni = -(b1 * s1 + b2 * s2);
    const dr = 1 + a1 * c1 + a2 * c2, di = -(a1 * s1 + a2 * s2);
    const mag2 = (nr * nr + ni * ni) / Math.max(1e-24, dr * dr + di * di);
    return 2 * 10 * Math.log10(Math.max(1e-24, mag2));
}

function bandIsAudible(band, sr) {
    if (!band.enabled) return false;
    if (band.freq_hz <= 0 || band.freq_hz >= 0.49 * sr) return false;
    const t = TYPE_BY_KEY.get(band.type);
    if (t && t.hasGain && Math.abs(band.gain_db) < 0.05) return false;
    return true;
}

function fmtFreq(hz) {
    return hz >= 1000
        ? `${(hz / 1000).toFixed(hz >= 10000 ? 1 : 2)} kHz`
        : `${Math.round(hz)} Hz`;
}

function fmtGain(db) {
    return `${db > 0 ? '+' : ''}${db.toFixed(1)} dB`;
}

// ── Panel ────────────────────────────────────────────────────────────────

/**
 * Build the EQ panel inside `host`. Returns:
 *   getPayload()        -> {enabled, bands: [...]} for the server
 *   setPayload(saved)   restore from persisted settings
 *   refreshSpectrum()   redraw after new analysis data arrives
 *
 * opts.onChange fires on every audible edit (debounced upstream).
 * opts.getSpectrum returns {freqs_hz, band_db} or null — drawn as a
 * silhouette behind the curve when available.
 */
export function initEqPanel(host, { onChange, getSpectrum } = {}) {
    const state = {
        enabled: false,
        bands: [],
        selected: -1,
        sr: 44100,
    };

    host.innerHTML = '';
    host.classList.add('eq-panel');

    // Header: enable toggle + preset dropdown + add button
    const header = document.createElement('div');
    header.className = 'eq-header';
    header.innerHTML = `
        <label class="checkbox-row eq-toggle">
            <input type="checkbox" id="eq-enabled">
            <span><b>Equalizer</b> — shape the cleaned audio before mastering</span>
        </label>
        <div class="eq-header-actions">
            <select class="select eq-preset-select" title="Load an EQ starting point (replaces current bands)">
                <option value="">EQ presets…</option>
                ${EQ_PRESETS.map(p => `<option value="${p.key}">${p.label}</option>`).join('')}
                <option value="__flat">Clear all bands</option>
            </select>
            <button type="button" class="btn btn-ghost eq-add-btn" title="Add a bell band (or double-click the curve)">+ Band</button>
        </div>`;
    host.appendChild(header);
    const enabledEl = header.querySelector('#eq-enabled');
    const presetSel = header.querySelector('.eq-preset-select');
    const addBtn = header.querySelector('.eq-add-btn');

    const body = document.createElement('div');
    body.className = 'eq-body';
    host.appendChild(body);

    const canvas = document.createElement('canvas');
    canvas.className = 'eq-canvas';
    canvas.title = 'Drag nodes · scroll = width (Q) · double-click = add/remove band';
    body.appendChild(canvas);

    const chips = document.createElement('div');
    chips.className = 'eq-chips';
    body.appendChild(chips);

    const editRow = document.createElement('div');
    editRow.className = 'eq-edit-row';
    editRow.innerHTML = `
        <label class="eq-field">Type
            <select class="select eq-edit-type">
                ${EQ_TYPES.map(t => `<option value="${t.key}">${t.label}</option>`).join('')}
            </select>
        </label>
        <label class="eq-field">Freq (Hz)
            <input type="number" class="input eq-edit-freq" min="20" max="20000" step="1">
        </label>
        <label class="eq-field">Gain (dB)
            <input type="number" class="input eq-edit-gain" min="-18" max="18" step="0.1">
        </label>
        <label class="eq-field">Q
            <input type="number" class="input eq-edit-q" min="0.1" max="18" step="0.1">
        </label>
        <label class="eq-field eq-field-check">On
            <input type="checkbox" class="eq-edit-on" checked>
        </label>
        <button type="button" class="btn btn-ghost eq-edit-del" title="Delete this band">✕</button>`;
    body.appendChild(editRow);
    const editType = editRow.querySelector('.eq-edit-type');
    const editFreq = editRow.querySelector('.eq-edit-freq');
    const editGain = editRow.querySelector('.eq-edit-gain');
    const editQ = editRow.querySelector('.eq-edit-q');
    const editOn = editRow.querySelector('.eq-edit-on');
    const editDel = editRow.querySelector('.eq-edit-del');

    // ── Canvas geometry ──────────────────────────────────────────────
    const ctx = canvas.getContext('2d');
    let W = 0, H = 0;          // CSS pixel size
    const PAD_L = 30, PAD_R = 8, PAD_T = 8, PAD_B = 18;

    function xOfF(f) {
        const t = Math.log(f / FREQ_MIN) / Math.log(FREQ_MAX / FREQ_MIN);
        return PAD_L + t * (W - PAD_L - PAD_R);
    }
    function fOfX(x) {
        const t = clamp((x - PAD_L) / (W - PAD_L - PAD_R), 0, 1);
        return FREQ_MIN * Math.pow(FREQ_MAX / FREQ_MIN, t);
    }
    function yOfDb(db) {
        const mid = PAD_T + (H - PAD_T - PAD_B) / 2;
        return mid - (db / DB_RANGE) * (H - PAD_T - PAD_B) / 2;
    }
    function dbOfY(y) {
        const mid = PAD_T + (H - PAD_T - PAD_B) / 2;
        return clamp(
            (mid - y) / ((H - PAD_T - PAD_B) / 2) * DB_RANGE,
            -GAIN_LIMIT, GAIN_LIMIT);
    }

    function nodePos(band) {
        const t = TYPE_BY_KEY.get(band.type);
        const db = t && t.hasGain ? band.gain_db : 0;
        return { x: xOfF(band.freq_hz), y: yOfDb(db) };
    }

    function resize() {
        const rect = canvas.getBoundingClientRect();
        if (rect.width < 10) return;
        const dpr = window.devicePixelRatio || 1;
        W = rect.width;
        H = rect.height;
        canvas.width = Math.round(W * dpr);
        canvas.height = Math.round(H * dpr);
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        draw();
    }
    if (typeof ResizeObserver !== 'undefined') {
        new ResizeObserver(resize).observe(canvas);
    }

    // ── Drawing ──────────────────────────────────────────────────────
    const GRID_FREQS = [50, 100, 200, 500, 1000, 2000, 5000, 10000];
    const GRID_DBS = [-12, -6, 0, 6, 12];

    function drawSpectrum() {
        const spec = getSpectrum ? getSpectrum() : null;
        if (!spec || !Array.isArray(spec.freqs_hz) ||
            !Array.isArray(spec.band_db) || spec.band_db.length === 0) return;
        const levels = spec.band_db;
        const top = Math.max(...levels.filter(Number.isFinite));
        if (!Number.isFinite(top)) return;
        const floor = top - 60;   // show 60 dB of headroom under the peak
        ctx.beginPath();
        ctx.moveTo(PAD_L, H - PAD_B);
        for (let i = 0; i < levels.length; i++) {
            const f = clamp(spec.freqs_hz[i], FREQ_MIN, FREQ_MAX);
            const norm = clamp((levels[i] - floor) / (top - floor), 0, 1);
            const y = (H - PAD_B) - norm * (H - PAD_T - PAD_B) * 0.85;
            ctx.lineTo(xOfF(f), y);
        }
        ctx.lineTo(W - PAD_R, H - PAD_B);
        ctx.closePath();
        ctx.fillStyle = 'rgba(136, 136, 153, 0.10)';
        ctx.fill();
    }

    function draw() {
        if (W === 0) return;
        ctx.clearRect(0, 0, W, H);
        const active = state.enabled;

        // Grid
        ctx.strokeStyle = '#252530';
        ctx.fillStyle = '#555566';
        ctx.lineWidth = 1;
        ctx.font = '10px Inter, sans-serif';
        ctx.textAlign = 'center';
        for (const f of GRID_FREQS) {
            const x = xOfF(f);
            ctx.beginPath(); ctx.moveTo(x, PAD_T); ctx.lineTo(x, H - PAD_B); ctx.stroke();
            ctx.fillText(f >= 1000 ? `${f / 1000}k` : `${f}`, x, H - 5);
        }
        ctx.textAlign = 'right';
        for (const db of GRID_DBS) {
            const y = yOfDb(db);
            ctx.strokeStyle = db === 0 ? '#353545' : '#252530';
            ctx.beginPath(); ctx.moveTo(PAD_L, y); ctx.lineTo(W - PAD_R, y); ctx.stroke();
            ctx.fillText(`${db > 0 ? '+' : ''}${db}`, PAD_L - 4, y + 3);
        }

        drawSpectrum();

        // Per-band faint curves + combined curve
        const N = 220;
        const freqs = new Array(N);
        for (let i = 0; i < N; i++) {
            freqs[i] = FREQ_MIN * Math.pow(FREQ_MAX / FREQ_MIN, i / (N - 1));
        }
        const total = new Array(N).fill(0);

        state.bands.forEach((band, bi) => {
            if (!bandIsAudible(band, state.sr)) return;
            ctx.beginPath();
            for (let i = 0; i < N; i++) {
                const db = bandResponseDb(band, freqs[i], state.sr);
                total[i] += db;
                const y = yOfDb(clamp(db, -DB_RANGE * 1.5, DB_RANGE * 1.5));
                if (i === 0) ctx.moveTo(xOfF(freqs[i]), y);
                else ctx.lineTo(xOfF(freqs[i]), y);
            }
            ctx.strokeStyle = BAND_COLORS[bi % BAND_COLORS.length] +
                (bi === state.selected ? '66' : '2e');
            ctx.lineWidth = 1.2;
            ctx.stroke();
        });

        ctx.beginPath();
        for (let i = 0; i < N; i++) {
            const y = yOfDb(clamp(total[i], -DB_RANGE * 1.5, DB_RANGE * 1.5));
            if (i === 0) ctx.moveTo(xOfF(freqs[i]), y);
            else ctx.lineTo(xOfF(freqs[i]), y);
        }
        ctx.strokeStyle = active ? '#6c5ce7' : '#555566';
        ctx.lineWidth = 2;
        ctx.stroke();

        // Nodes
        state.bands.forEach((band, bi) => {
            const { x, y } = nodePos(band);
            const color = BAND_COLORS[bi % BAND_COLORS.length];
            if (bi === state.selected) {
                ctx.beginPath();
                ctx.arc(x, y, 10, 0, Math.PI * 2);
                ctx.fillStyle = color + '38';
                ctx.fill();
            }
            ctx.beginPath();
            ctx.arc(x, y, 6, 0, Math.PI * 2);
            ctx.fillStyle = band.enabled ? color : '#353545';
            ctx.fill();
            ctx.strokeStyle = '#0e0e16';
            ctx.lineWidth = 1.5;
            ctx.stroke();
            ctx.fillStyle = band.enabled ? '#0e0e16' : '#555566';
            ctx.font = 'bold 9px Inter, sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText(String(bi + 1), x, y + 3);
        });

        // Selected-band readout in the top corner
        const sel = state.bands[state.selected];
        if (sel) {
            const t = TYPE_BY_KEY.get(sel.type);
            const bits = [t ? t.label : sel.type, fmtFreq(sel.freq_hz)];
            if (t && t.hasGain) bits.push(fmtGain(sel.gain_db));
            bits.push(`Q ${sel.q.toFixed(2)}`);
            ctx.fillStyle = '#888899';
            ctx.font = '11px Inter, sans-serif';
            ctx.textAlign = 'left';
            ctx.fillText(bits.join(' · '), PAD_L + 6, PAD_T + 12);
        }
    }

    // ── Chips + numeric edit row ─────────────────────────────────────
    function renderChips() {
        chips.innerHTML = '';
        state.bands.forEach((band, bi) => {
            const t = TYPE_BY_KEY.get(band.type);
            const chip = document.createElement('button');
            chip.type = 'button';
            chip.className = 'eq-chip';
            if (bi === state.selected) chip.classList.add('active');
            if (!band.enabled) chip.classList.add('off');
            chip.style.setProperty(
                '--chip-color', BAND_COLORS[bi % BAND_COLORS.length]);
            const gainTxt = t && t.hasGain ? ` ${fmtGain(band.gain_db)}` : '';
            chip.textContent =
                `${bi + 1} · ${t ? t.label : band.type} ${fmtFreq(band.freq_hz)}${gainTxt}`;
            chip.addEventListener('click', () => {
                selectBand(bi);
            });
            chips.appendChild(chip);
        });
        chips.hidden = state.bands.length === 0;
    }

    function renderEditRow() {
        const band = state.bands[state.selected];
        editRow.hidden = !band;
        if (!band) return;
        const t = TYPE_BY_KEY.get(band.type);
        editType.value = band.type;
        editFreq.value = String(Math.round(band.freq_hz));
        editGain.value = band.gain_db.toFixed(1);
        editGain.disabled = !(t && t.hasGain);
        editQ.value = band.q.toFixed(2);
        editOn.checked = band.enabled;
    }

    function refresh({ notify = true } = {}) {
        draw();
        renderChips();
        renderEditRow();
        if (notify && onChange) onChange();
    }

    function selectBand(i) {
        state.selected = i;
        refresh({ notify: false });
    }

    function addBand(over = {}) {
        if (state.bands.length >= MAX_BANDS) return;
        state.bands.push(makeBand(over));
        state.selected = state.bands.length - 1;
        if (!state.enabled) {
            state.enabled = true;
            enabledEl.checked = true;
        }
        refresh();
    }

    function removeBand(i) {
        if (i < 0 || i >= state.bands.length) return;
        state.bands.splice(i, 1);
        if (state.selected >= state.bands.length) {
            state.selected = state.bands.length - 1;
        }
        refresh();
    }

    // ── Canvas interactions ──────────────────────────────────────────
    function hitTest(x, y) {
        let best = -1, bestD = 14;
        state.bands.forEach((band, bi) => {
            const p = nodePos(band);
            const d = Math.hypot(p.x - x, p.y - y);
            if (d < bestD) { bestD = d; best = bi; }
        });
        return best;
    }

    let drag = null;   // {index}

    canvas.addEventListener('pointerdown', (e) => {
        const rect = canvas.getBoundingClientRect();
        const x = e.clientX - rect.left, y = e.clientY - rect.top;
        const hit = hitTest(x, y);
        if (hit >= 0) {
            drag = { index: hit };
            selectBand(hit);
            canvas.setPointerCapture(e.pointerId);
        } else {
            state.selected = -1;
            refresh({ notify: false });
        }
    });

    canvas.addEventListener('pointermove', (e) => {
        const rect = canvas.getBoundingClientRect();
        const x = e.clientX - rect.left, y = e.clientY - rect.top;
        if (!drag) {
            canvas.style.cursor = hitTest(x, y) >= 0 ? 'grab' : 'crosshair';
            return;
        }
        const band = state.bands[drag.index];
        if (!band) return;
        band.freq_hz = clamp(fOfX(x), FREQ_MIN, FREQ_MAX);
        const t = TYPE_BY_KEY.get(band.type);
        if (t && t.hasGain) band.gain_db = dbOfY(y);
        draw();
        renderChips();
        renderEditRow();
    });

    const endDrag = () => {
        if (!drag) return;
        drag = null;
        if (onChange) onChange();
    };
    canvas.addEventListener('pointerup', endDrag);
    canvas.addEventListener('pointercancel', endDrag);

    canvas.addEventListener('wheel', (e) => {
        const rect = canvas.getBoundingClientRect();
        const x = e.clientX - rect.left, y = e.clientY - rect.top;
        // Only steal the wheel when hovering a node — otherwise a page
        // scroll past the canvas would silently rewrite the band's Q.
        const hit = hitTest(x, y);
        const band = state.bands[hit];
        if (!band) return;
        e.preventDefault();
        band.q = clamp(
            band.q * Math.pow(1.12, -Math.sign(e.deltaY)), Q_MIN, Q_MAX);
        if (hit !== state.selected) selectBand(hit);
        refresh();
    }, { passive: false });

    canvas.addEventListener('dblclick', (e) => {
        const rect = canvas.getBoundingClientRect();
        const x = e.clientX - rect.left, y = e.clientY - rect.top;
        const hit = hitTest(x, y);
        if (hit >= 0) {
            removeBand(hit);
        } else {
            addBand({ freq_hz: fOfX(x), gain_db: dbOfY(y) });
        }
    });

    // ── Control wiring ───────────────────────────────────────────────
    enabledEl.addEventListener('change', () => {
        state.enabled = enabledEl.checked;
        refresh();
    });

    presetSel.addEventListener('change', () => {
        const key = presetSel.value;
        presetSel.value = '';
        if (!key) return;
        if (key === '__flat') {
            state.bands = [];
            state.selected = -1;
        } else {
            const preset = EQ_PRESETS.find(p => p.key === key);
            if (!preset) return;
            state.bands = preset.bands.map(b => makeBand({ ...b }));
            state.selected = 0;
            state.enabled = true;
            enabledEl.checked = true;
        }
        refresh();
    });

    addBtn.addEventListener('click', () => addBand());

    editType.addEventListener('change', () => {
        const band = state.bands[state.selected];
        if (!band) return;
        band.type = editType.value;
        const t = TYPE_BY_KEY.get(band.type);
        if (t && !t.hasGain) band.gain_db = 0;
        refresh();
    });
    const numericEdit = (el, key, lo, hi) => {
        el.addEventListener('change', () => {
            const band = state.bands[state.selected];
            if (!band) return;
            const v = parseFloat(el.value);
            if (Number.isFinite(v)) band[key] = clamp(v, lo, hi);
            refresh();
        });
    };
    numericEdit(editFreq, 'freq_hz', FREQ_MIN, FREQ_MAX);
    numericEdit(editGain, 'gain_db', -GAIN_LIMIT, GAIN_LIMIT);
    numericEdit(editQ, 'q', Q_MIN, Q_MAX);
    editOn.addEventListener('change', () => {
        const band = state.bands[state.selected];
        if (!band) return;
        band.enabled = editOn.checked;
        refresh();
    });
    editDel.addEventListener('click', () => removeBand(state.selected));

    // ── Public API ───────────────────────────────────────────────────
    function getPayload() {
        return {
            enabled: state.enabled,
            bands: state.bands.map(b => ({
                type: b.type,
                freq_hz: Math.round(b.freq_hz * 100) / 100,
                gain_db: Math.round(b.gain_db * 100) / 100,
                q: Math.round(b.q * 1000) / 1000,
                enabled: b.enabled,
            })),
        };
    }

    function setPayload(saved) {
        if (!saved || typeof saved !== 'object') return;
        state.enabled = !!saved.enabled;
        enabledEl.checked = state.enabled;
        state.bands = (Array.isArray(saved.bands) ? saved.bands : [])
            .slice(0, MAX_BANDS)
            .filter(b => b && TYPE_BY_KEY.has(b.type))
            .map(b => makeBand({
                type: b.type,
                freq_hz: clamp(Number(b.freq_hz) || 1000, FREQ_MIN, FREQ_MAX),
                gain_db: clamp(Number(b.gain_db) || 0, -GAIN_LIMIT, GAIN_LIMIT),
                q: clamp(Number(b.q) || 1, Q_MIN, Q_MAX),
                enabled: b.enabled !== false,
            }));
        state.selected = state.bands.length ? 0 : -1;
        refresh({ notify: false });
    }

    function refreshSpectrum() {
        draw();
    }

    // Initial paint (canvas may still be 0-wide; ResizeObserver catches up).
    requestAnimationFrame(resize);
    refresh({ notify: false });

    return { getPayload, setPayload, refreshSpectrum };
}
