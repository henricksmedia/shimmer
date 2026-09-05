// trim.js — Top & tail: see the head/tail of a track and choose where it
// starts and ends.
//
// This exists because generators leave a short burst at the very top of a
// render — typically 15-35 ms around -50 dBFS. That is ABOVE the -60 dBFS
// silence gate (so "trim silence" keeps it) and invisible on a linear
// waveform (so a normal waveform view shows nothing). Both problems are
// solved the same way: draw the envelope in dB.
//
// Two rules the rest of this file follows:
//   * Detection is reported, never applied. Shimmer says what it found and
//     the user decides. Nothing here writes audio.
//   * The armed edit is always visible — in the card header, in the notice,
//     and on the done banner after export.

import { fetchEnvelope } from './api.js';

const FLOOR_DB = -100;      // bottom of the dB scale
const TOP_DB = 0;
const AUDITION_S = 2.5;     // how much to play from the marker
const PREROLL_S = 0.4;      // lead-in when auditioning the tail

export function initTrim({ onChange } = {}) {
    const $ = (id) => document.getElementById(id);

    const card = $('trim-card');
    const stateEl = $('trim-state');
    const toggleBtn = $('trim-toggle');
    const body = $('trim-body');
    const notice = $('edge-notice');
    const noticeTitle = $('edge-notice-title');
    const noticeDetail = $('edge-notice-detail');
    const fixBtn = $('edge-fix-btn');
    const reviewBtn = $('edge-review-btn');
    const headBtn = $('trim-edge-head');
    const tailBtn = $('trim-edge-tail');
    const zoomSel = $('trim-zoom');
    const auditionBtn = $('trim-audition');
    const clearBtn = $('trim-clear');
    const canvas = $('trim-canvas');
    const inMs = $('trim-in-ms');
    const outMs = $('trim-out-ms');

    if (!card || !canvas) return null;
    const ctx = canvas.getContext('2d');

    const state = {
        sessionId: null,
        durationS: 0,
        edges: null,
        edge: 'head',        // which end we are editing
        inS: 0,
        outS: null,          // null = end of file
        env: null,           // {start_s, end_s, db:[]}
        envKey: '',
        blobUrl: null,
        audio: null,
        pending: false,
    };

    // ── Formatting ──────────────────────────────────────────────────

    const fmtMs = (s) => `${(s * 1000).toFixed(0)} ms`;
    const fmtS = (s) => `${s.toFixed(3)} s`;

    function describe(edge, where) {
        return `${edge.artifact_ms.toFixed(0)} ms burst at ` +
               `${edge.artifact_peak_db.toFixed(0)} dBFS, ` +
               `${edge.gap_ms.toFixed(0)} ms of silence before the ` +
               (where === 'head' ? 'music starts' : 'music ends');
    }

    // ── State readout ───────────────────────────────────────────────

    function armed() {
        return state.inS > 0 || (state.outS != null && state.outS < state.durationS);
    }

    function refreshState() {
        stateEl.classList.remove('armed', 'clean');
        if (armed()) {
            const bits = [];
            if (state.inS > 0) bits.push(`in ${fmtS(state.inS)}`);
            if (state.outS != null && state.outS < state.durationS) {
                bits.push(`out ${fmtS(state.outS)}`);
            }
            stateEl.textContent = bits.join(' · ');
            stateEl.classList.add('armed');
            stateEl.title = 'This cut is applied when you Clean & Master.';
        } else if (state.edges && !state.edges.found) {
            stateEl.textContent = 'edges clean';
            stateEl.classList.add('clean');
            stateEl.title = 'Both ends were scanned and nothing was found.';
        } else {
            stateEl.textContent = 'no edit';
            stateEl.title = 'Exporting the full file.';
        }
        inMs.value = Math.round(state.inS * 1000);
        outMs.value = (state.outS == null) ? '' : Math.round(state.outS * 1000);
        if (onChange) onChange(getTrim());
    }

    // ── The notice ──────────────────────────────────────────────────
    //
    // The point of the whole feature: a detection has to be impossible to
    // walk past. A clean scan says so too, quietly, in the header chip.

    function showNotice() {
        const e = state.edges || {};
        if (!e.found) { notice.hidden = true; return; }

        const head = e.head, tail = e.tail;
        const where = head ? 'head' : 'tail';
        const found = head || tail;

        const both = head && tail;
        noticeTitle.textContent = both
            ? 'Artifacts found at both ends of this track'
            : `${where === 'head' ? 'Head' : 'Tail'} artifact found in this track`;

        const lines = [];
        if (head) lines.push(`Head — ${describe(head, 'head')}. Suggested in point ${fmtS(head.suggested_s)}.`);
        if (tail) lines.push(`Tail — ${describe(tail, 'tail')}. Suggested out point ${fmtS(tail.suggested_s)}.`);
        noticeDetail.textContent = lines.join('  ');

        state.edge = head ? 'head' : 'tail';
        notice.hidden = false;
        // Not applied — the user has to choose. Say so on the button.
        fixBtn.textContent = both ? 'Use both suggested cuts' : 'Use suggested cut';
    }

    // ── Drawing ─────────────────────────────────────────────────────

    function windowFor() {
        const span = parseFloat(zoomSel.value) || 3;
        if (state.edge === 'head') {
            return { start: 0, end: Math.min(span, state.durationS) };
        }
        return { start: Math.max(0, state.durationS - span), end: state.durationS };
    }

    const yFor = (db, h) =>
        h - ((Math.max(db, FLOOR_DB) - FLOOR_DB) / (TOP_DB - FLOOR_DB)) * h;

    function draw() {
        const dpr = window.devicePixelRatio || 1;
        const w = canvas.clientWidth, h = canvas.clientHeight;
        if (!w || !h) return;
        if (canvas.width !== w * dpr || canvas.height !== h * dpr) {
            canvas.width = w * dpr;
            canvas.height = h * dpr;
        }
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.clearRect(0, 0, w, h);

        const css = getComputedStyle(document.documentElement);
        const line = css.getPropertyValue('--line').trim() || '#252c37';
        const amber = css.getPropertyValue('--amber').trim() || '#f5a524';
        const cyan = css.getPropertyValue('--cyan').trim() || '#38bdf8';
        const fg3 = css.getPropertyValue('--fg-3').trim() || '#566171';

        const win = windowFor();
        const span = win.end - win.start;
        const xFor = (t) => ((t - win.start) / span) * w;

        // dB grid — the scale is the whole point, so label it.
        ctx.font = '9px var(--font-mono), monospace';
        for (const db of [-20, -40, -60, -80]) {
            const y = yFor(db, h);
            ctx.strokeStyle = line;
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo(0, y + 0.5);
            ctx.lineTo(w, y + 0.5);
            ctx.stroke();
            ctx.fillStyle = fg3;
            ctx.fillText(`${db}`, 3, y - 2);
        }

        // Envelope
        if (state.env && state.env.db.length) {
            const db = state.env.db;
            const e0 = state.env.start_s, e1 = state.env.end_s;
            const tOf = (i) => e0 + (i / (db.length - 1)) * (e1 - e0);
            ctx.beginPath();
            ctx.moveTo(xFor(tOf(0)), yFor(db[0], h));
            for (let i = 1; i < db.length; i++) {
                ctx.lineTo(xFor(tOf(i)), yFor(db[i], h));
            }
            ctx.strokeStyle = cyan;
            ctx.lineWidth = 1.2;
            ctx.stroke();
            ctx.lineTo(xFor(tOf(db.length - 1)), h);
            ctx.lineTo(xFor(tOf(0)), h);
            ctx.closePath();
            ctx.fillStyle = 'rgba(56,189,248,.16)';
            ctx.fill();
        } else {
            ctx.fillStyle = fg3;
            ctx.fillText('loading…', 8, h / 2);
        }

        // The detected artifact, so the user can see what Shimmer saw.
        const det = state.edges && state.edges[state.edge];
        if (det) {
            const a = xFor(det.artifact_start_s), b = xFor(det.artifact_end_s);
            ctx.fillStyle = 'rgba(240,82,107,.22)';
            ctx.fillRect(a, 0, Math.max(2, b - a), h);
            ctx.fillStyle = fg3;
            ctx.fillText('detected', Math.min(a + 3, w - 52), 11);
        }

        // Discarded region + marker
        const marker = state.edge === 'head'
            ? state.inS
            : (state.outS == null ? state.durationS : state.outS);
        const mx = xFor(marker);
        ctx.fillStyle = 'rgba(11,13,16,.72)';
        if (state.edge === 'head') ctx.fillRect(0, 0, Math.max(0, mx), h);
        else ctx.fillRect(mx, 0, Math.max(0, w - mx), h);

        ctx.strokeStyle = amber;
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.moveTo(mx + 0.5, 0);
        ctx.lineTo(mx + 0.5, h);
        ctx.stroke();
        ctx.fillStyle = amber;
        ctx.fillText(state.edge === 'head' ? 'IN' : 'OUT',
                     Math.min(mx + 4, w - 26), 11);
    }

    async function loadEnvelope() {
        if (!state.sessionId) { draw(); return; }
        const win = windowFor();
        const key = `${state.edge}:${win.start.toFixed(3)}:${win.end.toFixed(3)}`;
        if (key === state.envKey) { draw(); return; }
        state.envKey = key;
        draw();  // paint the frame immediately; envelope lands a moment later
        try {
            const env = await fetchEnvelope(state.sessionId, win.start, win.end, 700);
            if (state.envKey !== key) return;   // zoom changed mid-flight
            state.env = env;
        } catch (_) {
            state.env = null;
        }
        draw();
    }

    // ── Marker editing ──────────────────────────────────────────────

    function setMarker(t) {
        const clamped = Math.max(0, Math.min(state.durationS, t));
        if (state.edge === 'head') {
            // Never let the in point cross the out point.
            const limit = (state.outS == null ? state.durationS : state.outS) - 0.01;
            state.inS = Math.max(0, Math.min(limit, clamped));
        } else {
            state.outS = Math.max(state.inS + 0.01, clamped);
            if (state.outS >= state.durationS - 1e-4) state.outS = null;
        }
        refreshState();
        draw();
    }

    canvas.addEventListener('pointerdown', (e) => {
        canvas.setPointerCapture(e.pointerId);
        const move = (ev) => {
            const r = canvas.getBoundingClientRect();
            const win = windowFor();
            const frac = (ev.clientX - r.left) / r.width;
            setMarker(win.start + frac * (win.end - win.start));
        };
        move(e);
        const up = () => {
            canvas.removeEventListener('pointermove', move);
            canvas.removeEventListener('pointerup', up);
        };
        canvas.addEventListener('pointermove', move);
        canvas.addEventListener('pointerup', up);
        canvas.focus();
    });

    canvas.addEventListener('keydown', (e) => {
        const step = (e.shiftKey ? 0.010 : 0.001);
        const cur = state.edge === 'head'
            ? state.inS : (state.outS == null ? state.durationS : state.outS);
        if (e.key === 'ArrowLeft') { setMarker(cur - step); e.preventDefault(); }
        else if (e.key === 'ArrowRight') { setMarker(cur + step); e.preventDefault(); }
    });

    inMs.addEventListener('change', () => {
        state.edge = 'head';
        syncEdgeButtons();
        setMarker((parseFloat(inMs.value) || 0) / 1000);
        loadEnvelope();
    });
    outMs.addEventListener('change', () => {
        const v = outMs.value.trim();
        state.edge = 'tail';
        syncEdgeButtons();
        setMarker(v === '' ? state.durationS : (parseFloat(v) || 0) / 1000);
        loadEnvelope();
    });

    // ── Audition ────────────────────────────────────────────────────
    //
    // Plays the ORIGINAL file from the marker. That is exactly what the
    // export will sound like at the edit point, without rendering anything.

    function audition() {
        if (!state.blobUrl) return;
        if (!state.audio) state.audio = new Audio();
        const a = state.audio;
        if (!a.paused) { a.pause(); auditionBtn.textContent = 'Audition'; return; }

        a.src = state.blobUrl;
        const from = state.edge === 'head'
            ? state.inS
            : Math.max(0, (state.outS == null ? state.durationS : state.outS) - PREROLL_S);
        const until = from + AUDITION_S;

        const stop = () => {
            a.pause();
            a.removeEventListener('timeupdate', tick);
            auditionBtn.textContent = 'Audition';
        };
        const tick = () => { if (a.currentTime >= until) stop(); };

        a.addEventListener('timeupdate', tick);
        a.addEventListener('ended', stop, { once: true });
        const start = () => { a.currentTime = from; a.play().catch(() => {}); };
        if (a.readyState >= 1) start();
        else a.addEventListener('loadedmetadata', start, { once: true });
        auditionBtn.textContent = 'Stop';
    }

    // ── Wiring ──────────────────────────────────────────────────────

    function syncEdgeButtons() {
        headBtn.classList.toggle('active', state.edge === 'head');
        tailBtn.classList.toggle('active', state.edge === 'tail');
    }

    function setOpen(open) {
        body.hidden = !open;
        toggleBtn.textContent = open ? 'Close' : 'Open';
        toggleBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
        if (open) loadEnvelope();
    }

    toggleBtn.addEventListener('click', () => setOpen(body.hidden));
    headBtn.addEventListener('click', () => {
        state.edge = 'head'; syncEdgeButtons(); loadEnvelope();
    });
    tailBtn.addEventListener('click', () => {
        state.edge = 'tail'; syncEdgeButtons(); loadEnvelope();
    });
    zoomSel.addEventListener('change', loadEnvelope);
    auditionBtn.addEventListener('click', audition);
    clearBtn.addEventListener('click', () => {
        state.inS = 0;
        state.outS = null;
        refreshState();
        draw();
    });

    fixBtn.addEventListener('click', () => {
        const e = state.edges || {};
        if (e.head) state.inS = e.head.suggested_s;
        if (e.tail) state.outS = e.tail.suggested_s;
        refreshState();
        setOpen(true);
        notice.hidden = true;
    });
    reviewBtn.addEventListener('click', () => {
        setOpen(true);
        canvas.focus();
    });

    window.addEventListener('resize', () => { if (!body.hidden) draw(); });

    // ── Public surface ──────────────────────────────────────────────

    function getTrim() {
        return {
            inS: state.inS > 0 ? state.inS : 0,
            outS: (state.outS != null && state.outS < state.durationS)
                ? state.outS : null,
        };
    }

    return {
        getTrim,

        /** New file picked: reset everything and show "scanning". */
        reset(blobUrl) {
            state.sessionId = null;
            state.durationS = 0;
            state.edges = null;
            state.edge = 'head';
            state.inS = 0;
            state.outS = null;
            state.env = null;
            state.envKey = '';
            state.blobUrl = blobUrl || null;
            if (state.audio) { try { state.audio.pause(); } catch (_) {} }
            notice.hidden = true;
            setOpen(false);
            syncEdgeButtons();
            card.hidden = false;
            stateEl.className = 'trim-state';
            stateEl.textContent = 'scanning…';
            stateEl.title = 'Checking both ends for render artifacts.';
        },

        /** Scan finished: report what the server found. */
        setSession(sessionId, durationS, edges) {
            state.sessionId = sessionId;
            state.durationS = durationS || 0;
            state.edges = edges || { found: false, head: null, tail: null };
            showNotice();
            refreshState();
            if (state.edges.found) setOpen(true);
        },

        /** Scan could not run — say so rather than implying "clean". */
        setScanFailed() {
            state.edges = null;
            stateEl.className = 'trim-state';
            stateEl.textContent = 'edge scan unavailable';
            stateEl.title = 'Shimmer could not scan the edges of this file.';
        },

        hide() { card.hidden = true; },
    };
}
