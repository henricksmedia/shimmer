// report.js — the report stage after Clean & Master: the "What changed"
// card. Draws the whole-file spectrum before and after the pass, the
// removed signal, and a level-matched "after minus before" strip, with a
// one-line verdict on top and hover numbers. Drawing only: the numbers
// come from the server (shimmer/report.py) in job metrics under `spectra`.

// Same display tilt as the live analyzer, so a mix reads roughly flat and
// the top end, where the cleaning happens, is not crushed into a corner.
const TILT_DB_PER_OCT = 4.5;
const PLOT_DB_RANGE = 60;      // main plot: top = loudest band + 3 dB
const DELTA_DB_RANGE = 12;     // delta strip: ±12 dB
const GRID_STEP_DB = 12;
const DELTA_STEP_DB = 6;
const CUT_MIN_DB = 1.5;        // matches report.py

const COLOR = {
    before: 'rgba(233, 237, 243, 0.62)',
    after: '#f5a524',
    removed: '#f472b6',
    cutFill: 'rgba(56, 189, 248, 0.30)',
    addFill: 'rgba(245, 165, 36, 0.30)',
    deltaLine: 'rgba(255, 255, 255, 0.55)',
    grid: 'rgba(255, 255, 255, 0.07)',
    zero: 'rgba(255, 255, 255, 0.22)',
    label: 'rgba(255, 255, 255, 0.42)',
    hover: 'rgba(255, 255, 255, 0.35)',
};

function fmtHz(hz) {
    if (hz >= 10000) return `${(hz / 1000).toFixed(0)} kHz`;
    if (hz >= 1000) return `${(hz / 1000).toFixed(1)} kHz`;
    return `${Math.round(hz)} Hz`;
}

function fmtDb(v, digits = 1) {
    return (v == null || !Number.isFinite(v)) ? 'n/a' : v.toFixed(digits);
}

export function initReport({ card, canvas, headline, readout }) {
    let data = null;
    let hoverIdx = null;

    // ── Verdict line ────────────────────────────────────────────────
    function renderHeadline(s) {
        headline.innerHTML = '';
        const add = (text, bold = false) => {
            const el = document.createElement(bold ? 'b' : 'span');
            el.textContent = text;
            headline.appendChild(el);
        };
        if (s.cut) {
            const lo = fmtHz(s.cut.lo_hz), hi = fmtHz(s.cut.hi_hz), at = fmtHz(s.cut.at_hz);
            add('Cut up to ');
            add(`${fmtDb(s.cut.max_cut_db)} dB`, true);
            if (lo === hi) {
                add(` at ${at}. `);
            } else {
                add(` between ${lo} and ${hi}, most at ${at}. `);
            }
        } else {
            add(`No band cut by more than ${CUT_MIN_DB} dB. `);
        }
        add(`Below 2 kHz the change stays within ±${fmtDb(s.low_max_abs_db)} dB. `);
        if (s.added_max_db != null && s.added_max_db >= CUT_MIN_DB) {
            add(`Up to +${fmtDb(s.added_max_db)} dB was added somewhere. `);
        }
        if (s.gain_db != null && Math.abs(s.gain_db) >= 0.3) {
            add(`Level ${s.gain_db > 0 ? '+' : ''}${fmtDb(s.gain_db)} dB, measured in the low mids.`);
        }
    }

    // ── Drawing ─────────────────────────────────────────────────────
    function sizeCanvas() {
        const dpr = window.devicePixelRatio || 1;
        const rect = canvas.getBoundingClientRect();
        const w = Math.max(50, Math.round(rect.width * dpr));
        const h = Math.max(50, Math.round(rect.height * dpr));
        if (canvas.width !== w || canvas.height !== h) {
            canvas.width = w;
            canvas.height = h;
        }
        return { dpr, w, h };
    }

    function draw() {
        if (!data) return;
        const { dpr, w, h } = sizeCanvas();
        const ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, w, h);

        const centers = data.centers_hz;
        const n = centers.length;
        if (n < 2) return;
        const tilt = (v, hz) => v + TILT_DB_PER_OCT * Math.log2(hz / 1000);
        const before = data.before_db.map((v, i) => tilt(v, centers[i]));
        const after = data.after_db.map((v, i) => tilt(v, centers[i]));
        const removed = data.removed_db ? data.removed_db.map((v, i) => tilt(v, centers[i])) : null;
        const delta = data.delta_db;

        // Layout: main plot, gap, delta strip, frequency labels; right gutter for dB.
        const gutterR = 30 * dpr;
        const labelH = 13 * dpr;
        const gap = 8 * dpr;
        const deltaH = 60 * dpr;
        const plotW = w - gutterR;
        const mainTop = 4 * dpr;
        const mainH = h - labelH - gap - deltaH - mainTop;
        const deltaTop = mainTop + mainH + gap;

        const fMin = centers[0], fMax = centers[n - 1];
        const xOf = (hz) => (Math.log(hz / fMin) / Math.log(fMax / fMin)) * plotW;
        const top = Math.max(...before, ...after) + 3;
        const bottom = top - PLOT_DB_RANGE;
        const yMain = (v) => mainTop + ((top - v) / (top - bottom)) * mainH;
        const yDelta = (v) => deltaTop + ((DELTA_DB_RANGE - Math.max(-DELTA_DB_RANGE, Math.min(DELTA_DB_RANGE, v))) / (2 * DELTA_DB_RANGE)) * deltaH;

        ctx.font = `500 ${9 * dpr}px system-ui, sans-serif`;
        ctx.textBaseline = 'middle';
        ctx.lineWidth = 1;

        // dB grid on the main plot, labels in the right gutter.
        const firstGrid = Math.floor(top / GRID_STEP_DB) * GRID_STEP_DB;
        for (let v = firstGrid; v > bottom; v -= GRID_STEP_DB) {
            const y = yMain(v);
            ctx.strokeStyle = COLOR.grid;
            ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(plotW, y); ctx.stroke();
            ctx.fillStyle = COLOR.label;
            ctx.textAlign = 'left';
            ctx.fillText(String(Math.round(v)), plotW + 4 * dpr, y);
        }
        // Delta grid: zero line and ±6.
        for (let v = -DELTA_DB_RANGE + DELTA_STEP_DB; v < DELTA_DB_RANGE; v += DELTA_STEP_DB) {
            const y = yDelta(v);
            ctx.strokeStyle = v === 0 ? COLOR.zero : COLOR.grid;
            ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(plotW, y); ctx.stroke();
            ctx.fillStyle = COLOR.label;
            ctx.textAlign = 'left';
            ctx.fillText(v > 0 ? `+${v}` : String(v), plotW + 4 * dpr, y);
        }
        // Frequency grid + labels along the bottom.
        const ticks = [100, 500, 1000, 2000, 5000, 10000, 20000];
        ctx.textBaseline = 'bottom';
        for (const f of ticks) {
            if (f < fMin || f > fMax) continue;
            const x = xOf(f);
            ctx.strokeStyle = COLOR.grid;
            ctx.beginPath(); ctx.moveTo(x, mainTop); ctx.lineTo(x, deltaTop + deltaH); ctx.stroke();
            ctx.fillStyle = COLOR.label;
            const last = f >= fMax * 0.98;
            ctx.textAlign = last ? 'right' : 'left';
            ctx.fillText(f >= 1000 ? `${f / 1000}k` : String(f), last ? x - 3 * dpr : x + 3 * dpr, h - 2 * dpr);
        }

        // Delta fill: under zero = cut (cyan), over zero = added (amber).
        const y0 = yDelta(0);
        for (let i = 0; i < n - 1; i++) {
            const x1 = xOf(centers[i]), x2 = xOf(centers[i + 1]);
            const v1 = delta[i], v2 = delta[i + 1];
            ctx.fillStyle = (v1 + v2) / 2 < 0 ? COLOR.cutFill : COLOR.addFill;
            ctx.beginPath();
            ctx.moveTo(x1, y0); ctx.lineTo(x1, yDelta(v1)); ctx.lineTo(x2, yDelta(v2)); ctx.lineTo(x2, y0);
            ctx.closePath(); ctx.fill();
        }
        const line = (vals, yf, color, width, dash = []) => {
            ctx.beginPath();
            for (let i = 0; i < n; i++) {
                const x = xOf(centers[i]), y = yf(vals[i]);
                if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
            }
            ctx.setLineDash(dash.map(d => d * dpr));
            ctx.strokeStyle = color;
            ctx.lineWidth = width * dpr;
            ctx.stroke();
            ctx.setLineDash([]);
        };
        line(delta, yDelta, COLOR.deltaLine, 1);
        if (removed) line(removed, yMain, COLOR.removed, 1.25, [4, 3]);
        line(before, yMain, COLOR.before, 1.5);
        line(after, yMain, COLOR.after, 2);

        // Hover crosshair.
        if (hoverIdx != null) {
            const x = xOf(centers[hoverIdx]);
            ctx.strokeStyle = COLOR.hover;
            ctx.lineWidth = 1;
            ctx.setLineDash([3 * dpr, 3 * dpr]);
            ctx.beginPath(); ctx.moveTo(x, mainTop); ctx.lineTo(x, deltaTop + deltaH); ctx.stroke();
            ctx.setLineDash([]);
            for (const [vals, color] of [[after, COLOR.after], [before, COLOR.before]]) {
                ctx.fillStyle = color;
                ctx.beginPath(); ctx.arc(x, yMain(vals[hoverIdx]), 3 * dpr, 0, Math.PI * 2); ctx.fill();
            }
        }
    }

    function updateReadout() {
        if (!data || hoverIdx == null) {
            readout.textContent = 'Hover for the numbers at any frequency.';
            return;
        }
        const i = hoverIdx;
        const rem = data.removed_db ? ` · removed ${fmtDb(data.removed_db[i])}` : '';
        readout.textContent =
            `${fmtHz(data.centers_hz[i])} · before ${fmtDb(data.before_db[i])}` +
            ` · after ${fmtDb(data.after_db[i])}${rem} dB · change ${data.delta_db[i] > 0 ? '+' : ''}${fmtDb(data.delta_db[i])} dB`;
    }

    canvas.addEventListener('mousemove', (ev) => {
        if (!data) return;
        const rect = canvas.getBoundingClientRect();
        const gutter = 30;   // CSS px, matches gutterR / dpr
        const plotW = rect.width - gutter;
        const frac = Math.max(0, Math.min(1, (ev.clientX - rect.left) / plotW));
        const c = data.centers_hz;
        const hz = c[0] * Math.pow(c[c.length - 1] / c[0], frac);
        let best = 0, bestD = Infinity;
        for (let i = 0; i < c.length; i++) {
            const d = Math.abs(Math.log(c[i] / hz));
            if (d < bestD) { bestD = d; best = i; }
        }
        if (best !== hoverIdx) { hoverIdx = best; draw(); updateReadout(); }
    });
    canvas.addEventListener('mouseleave', () => {
        hoverIdx = null; draw(); updateReadout();
    });
    const ro = new ResizeObserver(() => { if (data && !card.hidden) draw(); });
    ro.observe(canvas);

    return {
        show(spectra) {
            const ok = spectra && Array.isArray(spectra.centers_hz) &&
                Array.isArray(spectra.before_db) && Array.isArray(spectra.after_db);
            if (!ok) { this.clear(); return; }
            data = spectra;
            hoverIdx = null;
            card.hidden = false;
            renderHeadline(spectra);
            updateReadout();
            // Draw now, not on the next animation frame: a hidden or
            // throttled tab may never get one, and the card was just
            // un-hidden so layout is already settled.
            draw();
        },
        clear() {
            data = null;
            hoverIdx = null;
            card.hidden = true;
        },
    };
}
