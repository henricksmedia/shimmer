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
//
// Fades live here too, one per end: Head shows Fade in, Tail shows Fade
// out. A fade ends at the cut (or starts at it, for a fade in), so moving
// the cut moves the fade. The server puts them on after mastering
// (core/analyze/edges.py apply_fades); the curves below match its.
//
// Above the zoomed view sits the whole song, for ending a song early: drag
// OUT to where it should stop, drag the round knob to set the fade. Pins
// mark level dips the server measured (core/analyze/dips.py): snap points,
// not advice. The zoomed view follows the handle you moved.

import { fetchEnvelope } from './api.js';

const FLOOR_DB = -100;      // bottom of the dB scale
const TOP_DB = 0;
const AUDITION_S = 2.5;     // how much to play from the marker
const PREROLL_S = 0.4;      // lead-in when auditioning the tail
const FADE_LEAD_S = 1.5;    // music before a fade out, when auditioning it
const FADE_OUT_RANGE_DB = 40;   // edges.py FADE_OUT_RANGE_DB
const FADE_CLOSE = 0.1;         // edges.py FADE_CLOSE
const FADE_MAX_S = 30;          // edges.py FADE_MAX_S
const OV_FLOOR_DB = -48;        // the whole-song strip shows the music, not the floor
const OV_POINTS = 1000;
const SNAP_PX = 9;              // handles snap to a pin this close
const GRAB_PX = 10;             // how close a press must be to grab a handle

// Presets per end. Fade-ins are shorter: they smooth a hard start, while
// a fade out closes the song.
const FADE_PRESETS = {
    head: [0, 0.5, 1, 2],
    tail: [0, 2, 4, 8, 'custom'],
};

// Gain at fraction t (0..1) through the fade. Same curves as the server.
function fadeOutGain(t) {
    const close = Math.max(0, Math.min(1, (1 - t) / FADE_CLOSE));
    return 10 ** (-FADE_OUT_RANGE_DB * t / 20) * close;
}
function fadeInGain(t) {
    return Math.sin(0.5 * Math.PI * Math.max(0, Math.min(1, t)));
}

// m:ss.000, the way a DAW shows a position.
export function fmtClock(s) {
    const v = Math.max(0, s);
    const m = Math.floor(v / 60);
    const sec = v - m * 60;
    return `${m}:${sec.toFixed(3).padStart(6, '0')}`;
}

// "1:58.4", "118.4" or "1:58" → seconds. null when it cannot be read.
export function parseClock(text) {
    const t = String(text || '').trim();
    if (!t) return null;
    const m = /^(?:(\d+):)?(\d+(?:\.\d*)?|\.\d+)$/.exec(t);
    if (!m) return null;
    const v = (m[1] ? parseInt(m[1], 10) * 60 : 0) + parseFloat(m[2]);
    return Number.isFinite(v) ? v : null;
}

export function initTrim({ onChange, getPlayhead } = {}) {
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
    const fadeLabel = $('trim-fade-label');
    const fadePresets = $('trim-fade-presets');
    const fadeCustom = $('trim-fade-custom');
    const fadeInput = $('trim-fade-s');
    const fadeNote = $('trim-fade-note');
    const overview = $('trim-overview');
    const pinsRow = $('trim-pins');
    const pinList = $('trim-pin-list');
    const inHereBtn = $('trim-in-here');
    const outHereBtn = $('trim-out-here');

    if (!card || !canvas) return null;
    const ctx = canvas.getContext('2d');
    const octx = overview ? overview.getContext('2d') : null;

    const state = {
        sessionId: null,
        durationS: 0,
        edges: null,
        edge: 'head',        // which end we are editing
        inS: 0,
        outS: null,          // null = end of file
        fadeInS: 0,          // 0 = no fade
        fadeOutS: 0,
        customFade: false,   // Custom picked for the fade out
        env: null,           // {start_s, end_s, db:[]}
        envKey: '',
        win: null,           // the zoomed window, kept while the marker is inside it
        holdWin: false,      // true while dragging in the zoomed view
        ovEnv: null,         // whole-song envelope
        dips: [],             // level dips [{at_s, level_db, dip_db, rise_db}] from the server
        playheadS: null,
        blobUrl: null,
        audio: null,
        pending: false,
    };

    // ── Formatting ──────────────────────────────────────────────────

    const fmtMs = (s) => `${(s * 1000).toFixed(0)} ms`;
    const fmtS = (s) => `${s.toFixed(3)} s`;
    const fmtFade = (s) => `${+s.toFixed(1)} s`;

    function describe(edge, where) {
        return `${edge.artifact_ms.toFixed(0)} ms burst at ` +
               `${edge.artifact_peak_db.toFixed(0)} dBFS, ` +
               `${edge.gap_ms.toFixed(0)} ms of silence before the ` +
               (where === 'head' ? 'music starts' : 'music ends');
    }

    // ── State readout ───────────────────────────────────────────────

    function armed() {
        return state.inS > 0 || (state.outS != null && state.outS < state.durationS)
            || state.fadeInS > 0 || state.fadeOutS > 0;
    }

    // Where the kept song starts and ends, so a fade can follow the cut.
    const keptStart = () => state.inS;
    const keptEnd = () => (state.outS == null ? state.durationS : state.outS);

    // The fades as the server will apply them: each held to half the kept
    // song, so they never overlap.
    function fadeLen(which) {
        const half = Math.max(0, (keptEnd() - keptStart()) / 2);
        const s = which === 'in' ? state.fadeInS : state.fadeOutS;
        return Math.min(s, FADE_MAX_S, half);
    }

    function refreshState() {
        stateEl.classList.remove('armed', 'clean');
        if (armed()) {
            const bits = [];
            if (state.inS > 0) bits.push(`in ${fmtClock(state.inS)}`);
            if (state.outS != null && state.outS < state.durationS) {
                bits.push(`out ${fmtClock(state.outS)}`);
            }
            if (fadeLen('in') > 0) bits.push(`${fmtFade(fadeLen('in'))} fade in`);
            if (fadeLen('out') > 0) bits.push(`${fmtFade(fadeLen('out'))} fade out`);
            stateEl.textContent = bits.join(' · ');
            stateEl.classList.add('armed');
            stateEl.title = 'Applied when you Clean & Master.';
        } else if (state.edges && !state.edges.found) {
            stateEl.textContent = 'edges clean';
            stateEl.classList.add('clean');
            stateEl.title = 'Both ends were scanned and nothing was found.';
        } else {
            stateEl.textContent = 'no edit';
            stateEl.title = 'Exporting the full file.';
        }
        if (document.activeElement !== inMs) inMs.value = fmtClock(state.inS);
        if (document.activeElement !== outMs) {
            outMs.value = (state.outS == null) ? '' : fmtClock(state.outS);
        }
        renderFade();
        renderPins();
        if (onChange) onChange(getTrim());
    }

    // ── Fades ───────────────────────────────────────────────────────
    //
    // The row under the waveform shows the fade for the end in view.

    function renderFade() {
        const head = state.edge === 'head';
        const cur = head ? state.fadeInS : state.fadeOutS;
        fadeLabel.textContent = head ? 'Fade in' : 'Fade out';
        fadePresets.textContent = '';
        const presets = FADE_PRESETS[head ? 'head' : 'tail'];
        const custom = !head && (state.customFade || (cur > 0 && !presets.includes(cur)));
        for (const p of presets) {
            const b = document.createElement('button');
            b.type = 'button';
            b.className = 'viz-mode-btn';
            b.textContent = p === 'custom' ? 'Custom' : (p === 0 ? 'Off' : `${p} s`);
            const on = p === 'custom' ? custom : (!custom && cur === p);
            b.classList.toggle('active', on);
            b.setAttribute('aria-pressed', on ? 'true' : 'false');
            b.addEventListener('click', () => pickFade(p));
            fadePresets.appendChild(b);
        }
        fadeCustom.hidden = !custom;
        if (custom && document.activeElement !== fadeInput) {
            fadeInput.value = cur > 0 ? +cur.toFixed(1) : '';
        }
        const len = fadeLen(head ? 'in' : 'out');
        if (cur <= 0) {
            fadeNote.textContent = head ? 'The song starts at full level.'
                                        : 'The song stops at the cut.';
        } else {
            const held = len < cur - 1e-6 ? ` Held to ${fmtFade(len)}: half the song.` : '';
            fadeNote.textContent = (head ? 'Starts at the in point.' : 'Ends at the cut.')
                + ' Audition plays it.' + held;
        }
    }

    function pickFade(p) {
        const head = state.edge === 'head';
        if (p === 'custom') {
            state.customFade = true;
            if (!(state.fadeOutS > 0)) state.fadeOutS = 6;
        } else {
            if (!head) state.customFade = false;
            if (head) state.fadeInS = p; else state.fadeOutS = p;
        }
        fitZoom();
        refreshState();
        loadEnvelope();
        if (p === 'custom') fadeInput.focus();
    }

    // Widen the view so the whole fade fits, with a little room before it.
    function fitZoom() {
        const len = state.edge === 'head' ? state.fadeInS : state.fadeOutS;
        if (!(len > 0)) return;
        const need = len + 0.5;
        if ((parseFloat(zoomSel.value) || 3) >= need) return;
        const opt = [...zoomSel.options].find((o) => parseFloat(o.value) >= need)
            || zoomSel.options[zoomSel.options.length - 1];
        zoomSel.value = opt.value;
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
        syncEdgeButtons();
        notice.hidden = false;
        // Not applied — the user has to choose. Say so on the button.
        fixBtn.textContent = both ? 'Use both suggested cuts' : 'Use suggested cut';
    }

    // ── Drawing ─────────────────────────────────────────────────────

    // The zoomed window: around the marker for the end in view. It stays put
    // while the marker is well inside it, so nudging and dragging do not
    // scroll it; it moves when the marker leaves (a handle dragged on the
    // whole song, a typed time, a pin).
    function windowFor() {
        const span = Math.min(parseFloat(zoomSel.value) || 3, state.durationS || 3);
        const dur = state.durationS;
        const t = state.edge === 'head' ? keptStart() : keptEnd();
        const w = state.win;
        if (w && w.edge === state.edge && Math.abs((w.end - w.start) - span) < 1e-6) {
            const margin = 0.1 * span;
            const okLeft = t >= w.start + margin || w.start <= 0;
            const okRight = t <= w.end - margin || w.end >= dur;
            if (state.holdWin || (okLeft && okRight && t >= w.start && t <= w.end)) {
                return { start: w.start, end: w.end };
            }
        }
        // Head: most of the window after the in point. Tail: most before
        // the out point. At the file's ends this matches the old views.
        let start = state.edge === 'head' ? t - 0.3 * span : t - 0.7 * span;
        start = Math.max(0, Math.min(Math.max(0, dur - span), start));
        state.win = { edge: state.edge, start, end: start + span };
        return { start, end: start + span };
    }

    // Where the fade for the end in view starts and ends, or null.
    function fadeSpan() {
        if (state.edge === 'head') {
            const len = fadeLen('in');
            return len > 0 ? { a: keptStart(), b: keptStart() + len, out: false } : null;
        }
        const len = fadeLen('out');
        return len > 0 ? { a: keptEnd() - len, b: keptEnd(), out: true } : null;
    }

    const yFor = (db, h) =>
        h - ((Math.max(db, FLOOR_DB) - FLOOR_DB) / (TOP_DB - FLOOR_DB)) * h;

    function draw() {
        drawDetail();
        drawOverview();
    }

    function sizeCanvas(cv, cx) {
        const dpr = window.devicePixelRatio || 1;
        const w = cv.clientWidth, h = cv.clientHeight;
        if (!w || !h) return null;
        if (cv.width !== w * dpr || cv.height !== h * dpr) {
            cv.width = w * dpr;
            cv.height = h * dpr;
        }
        cx.setTransform(dpr, 0, 0, dpr, 0, 0);
        cx.clearRect(0, 0, w, h);
        return { w, h };
    }

    // ── The whole song ──────────────────────────────────────────────

    const ovX = (t, w) => (state.durationS > 0 ? (t / state.durationS) * w : 0);
    const ovY = (db, h) =>
        h - ((Math.max(db, OV_FLOOR_DB) - OV_FLOOR_DB) / (TOP_DB - OV_FLOOR_DB)) * h;

    // Where each handle sits on the strip, for drawing and for grabbing.
    function ovHandles(w) {
        const fin = fadeLen('in'), fout = fadeLen('out');
        return {
            in: ovX(keptStart(), w),
            out: ovX(keptEnd(), w),
            fadeIn: ovX(keptStart() + fin, w),
            fadeOut: ovX(keptEnd() - fout, w),
        };
    }

    function drawOverview() {
        if (!overview || !octx || body.hidden) return;
        const size = sizeCanvas(overview, octx);
        if (!size) return;
        const { w, h } = size;
        const cx = octx;
        const css = getComputedStyle(document.documentElement);
        const line = css.getPropertyValue('--line').trim() || '#252c37';
        const amber = css.getPropertyValue('--amber').trim() || '#f5a524';
        const cyan = css.getPropertyValue('--cyan').trim() || '#38bdf8';
        const fg2 = css.getPropertyValue('--fg-2').trim() || '#9aa5b4';
        const fg3 = css.getPropertyValue('--fg-3').trim() || '#566171';
        cx.font = '9px var(--font-mono), monospace';

        // Minute grid with labels, so a time you heard is easy to find.
        const dur = state.durationS;
        const step = dur > 360 ? 60 : dur > 120 ? 30 : 15;
        cx.strokeStyle = line;
        cx.lineWidth = 1;
        for (let t = step; t < dur; t += step) {
            const x = Math.round(ovX(t, w)) + 0.5;
            cx.beginPath(); cx.moveTo(x, 0); cx.lineTo(x, h); cx.stroke();
            cx.fillStyle = fg3;
            cx.fillText(fmtClock(t).replace(/\.\d+$/, ''), x + 3, h - 3);
        }

        // Level, mirrored like a waveform so the shape of the song reads.
        const env = state.ovEnv;
        if (env && env.db.length) {
            const db = env.db, n = db.length, mid = h / 2;
            cx.beginPath();
            for (let i = 0; i < n; i++) {
                const x = (i / (n - 1)) * w;
                const a = (h - ovY(db[i], h)) / 2;
                if (i === 0) cx.moveTo(x, mid - a); else cx.lineTo(x, mid - a);
            }
            for (let i = n - 1; i >= 0; i--) {
                const x = (i / (n - 1)) * w;
                cx.lineTo(x, mid + (h - ovY(db[i], h)) / 2);
            }
            cx.closePath();
            cx.fillStyle = 'rgba(56,189,248,.34)';
            cx.fill();
            cx.strokeStyle = cyan;
            cx.lineWidth = 0.8;
            cx.stroke();
        } else {
            cx.fillStyle = fg3;
            cx.fillText('loading…', 8, h / 2);
        }

        const hd = ovHandles(w);

        // Fades: darken the song by how much the fade turns it down.
        const shade = (a, b, gainAt) => {
            const steps = Math.max(2, Math.round(b - a));
            for (let i = 0; i < steps; i++) {
                const u = (i + 0.5) / steps;
                cx.fillStyle = `rgba(11,13,16,${(0.72 * (1 - gainAt(u))).toFixed(3)})`;
                cx.fillRect(a + (i / steps) * (b - a), 0, (b - a) / steps + 0.5, h);
            }
        };
        if (fadeLen('in') > 0) shade(hd.in, hd.fadeIn, (u) => fadeInGain(u));
        if (fadeLen('out') > 0) shade(hd.fadeOut, hd.out, (u) => fadeOutGain(u));

        // What gets cut.
        cx.fillStyle = 'rgba(11,13,16,.72)';
        cx.fillRect(0, 0, Math.max(0, hd.in), h);
        cx.fillRect(hd.out, 0, Math.max(0, w - hd.out), h);

        // Pins: level dips (snap points).
        for (const p of state.dips) {
            const x = Math.round(ovX(p.at_s, w)) + 0.5;
            cx.strokeStyle = fg2;
            cx.setLineDash([2, 3]);
            cx.lineWidth = 1;
            cx.beginPath(); cx.moveTo(x, 10); cx.lineTo(x, h); cx.stroke();
            cx.setLineDash([]);
            cx.fillStyle = fg2;
            cx.beginPath();
            cx.moveTo(x - 4, 0); cx.lineTo(x + 4, 0); cx.lineTo(x, 7);
            cx.closePath(); cx.fill();
        }

        // Playhead.
        if (state.playheadS != null && dur > 0) {
            const x = Math.round(ovX(state.playheadS, w)) + 0.5;
            cx.strokeStyle = 'rgba(255,255,255,.55)';
            cx.lineWidth = 1;
            cx.beginPath(); cx.moveTo(x, 0); cx.lineTo(x, h); cx.stroke();
        }

        // Handles.
        cx.strokeStyle = amber;
        cx.fillStyle = amber;
        cx.lineWidth = 2;
        for (const [x, label, right] of [[hd.in, 'IN', true], [hd.out, 'OUT', false]]) {
            cx.beginPath(); cx.moveTo(x, 0); cx.lineTo(x, h); cx.stroke();
            const tw = label === 'IN' ? 18 : 26;
            const bx = right ? x : x - tw;
            cx.fillRect(Math.max(0, Math.min(w - tw, bx)), 0, tw, 13);
            cx.fillStyle = '#0b0d10';
            cx.fillText(label, Math.max(0, Math.min(w - tw, bx)) + 4, 10);
            cx.fillStyle = amber;
        }
        // Fade knobs sit at full level (the top) where each fade begins.
        for (const x of [hd.fadeIn, hd.fadeOut]) {
            cx.beginPath();
            cx.arc(Math.max(5, Math.min(w - 5, x)), 20, 4.5, 0, Math.PI * 2);
            cx.fill();
        }
    }

    // Drag on the whole song. A press grabs the nearest handle or knob;
    // a press on open ground moves the nearer of IN and OUT there.
    function ovTime(clientX) {
        const r = overview.getBoundingClientRect();
        return Math.max(0, Math.min(1, (clientX - r.left) / r.width)) * state.durationS;
    }

    function snapToPin(t, w, free) {
        if (free || !state.dips.length) return t;
        let best = t, bestPx = SNAP_PX + 1;
        for (const p of state.dips) {
            const d = Math.abs(ovX(p.at_s, w) - ovX(t, w));
            if (d < bestPx) { best = p.at_s; bestPx = d; }
        }
        return bestPx <= SNAP_PX ? best : t;
    }

    function setFade(which, len) {
        const v = Math.max(0, Math.min(FADE_MAX_S, Math.round(len * 10) / 10));
        if (which === 'in') {
            state.fadeInS = v;
        } else {
            state.fadeOutS = v;
            state.customFade = v > 0 && !FADE_PRESETS.tail.includes(v);
        }
    }

    if (overview) {
        overview.addEventListener('pointerdown', (e) => {
            if (!(state.durationS > 0)) return;
            overview.setPointerCapture(e.pointerId);
            const r = overview.getBoundingClientRect();
            const w = r.width, px = e.clientX - r.left;
            const hd = ovHandles(w);
            const near = (x) => Math.abs(px - x) <= GRAB_PX;
            // The knob row (just under the IN / OUT tabs) grabs a fade knob,
            // even when the fade is off and the knob sits on its handle.
            const py = e.clientY - r.top;
            const knobRow = py >= 13 && py <= 30;
            let grab;
            if (knobRow && near(hd.fadeOut)) grab = 'fadeOut';
            else if (knobRow && near(hd.fadeIn)) grab = 'fadeIn';
            if (!grab) {
                if (near(hd.out) && (!near(hd.in) || px > hd.in)) grab = 'out';
                else if (near(hd.in)) grab = 'in';
                else grab = Math.abs(px - hd.in) < Math.abs(px - hd.out) ? 'in' : 'out';
            }
            if (grab === 'in' || grab === 'fadeIn') state.edge = 'head';
            else state.edge = 'tail';
            syncEdgeButtons();

            const move = (ev) => {
                const t = ovTime(ev.clientX);
                if (grab === 'fadeOut') setFade('out', keptEnd() - t);
                else if (grab === 'fadeIn') setFade('in', t - keptStart());
                else setMarker(snapToPin(t, w, ev.altKey));
                fitZoom();
                refreshState();
                draw();
            };
            move(e);
            const up = () => {
                overview.removeEventListener('pointermove', move);
                overview.removeEventListener('pointerup', up);
                loadEnvelope();
            };
            overview.addEventListener('pointermove', move);
            overview.addEventListener('pointerup', up);
        });
    }

    function renderPins() {
        if (!pinsRow || !pinList) return;
        pinsRow.hidden = !state.dips.length;
        pinList.textContent = '';
        // In song order, like the pins on the strip.
        for (const p of [...state.dips].sort((a, b) => a.at_s - b.at_s)) {
            const b = document.createElement('button');
            b.type = 'button';
            b.className = 'btn btn-ghost btn-sm';
            b.textContent = fmtClock(p.at_s).replace(/(\.\d)\d\d$/, '$1');
            b.title = `Set OUT here. The level drops ${p.dip_db} dB under the song, `
                + `then rises ${p.rise_db} dB.`;
            const on = state.outS != null && Math.abs(state.outS - p.at_s) < 0.005;
            b.classList.toggle('active', on);
            b.setAttribute('aria-pressed', on ? 'true' : 'false');
            b.addEventListener('click', () => {
                state.edge = 'tail';
                syncEdgeButtons();
                setMarker(p.at_s);
                loadEnvelope();
            });
            pinList.appendChild(b);
        }
    }

    // Set a point where the player is. The out point snaps back to a pin
    // just before the playhead: people press a moment after they hear it.
    function markAtPlayhead(which) {
        const t = getPlayhead ? getPlayhead() : null;
        if (t == null || !Number.isFinite(t) || !(state.durationS > 0)) return;
        // A point that would leave almost nothing of the song is a stray
        // press (the player still at 0:00), not an edit.
        if (which === 'out' && t < keptStart() + 1) return;
        if (which === 'in' && t > keptEnd() - 1) return;
        let at = t;
        if (which === 'out') {
            const pin = state.dips
                .filter((p) => p.at_s <= t + 0.5 && p.at_s >= t - 1.5)
                .sort((a, b) => Math.abs(a.at_s - t) - Math.abs(b.at_s - t))[0];
            if (pin) at = pin.at_s;
        }
        state.edge = which === 'in' ? 'head' : 'tail';
        syncEdgeButtons();
        if (body.hidden) setOpen(true);
        setMarker(at);
        loadEnvelope();
    }
    if (inHereBtn) inHereBtn.addEventListener('click', () => markAtPlayhead('in'));
    if (outHereBtn) outHereBtn.addEventListener('click', () => markAtPlayhead('out'));

    // Follow the player while the card is open, a few times a second.
    setInterval(() => {
        if (body.hidden || !getPlayhead) return;
        const t = getPlayhead();
        const v = Number.isFinite(t) ? t : null;
        if (v === state.playheadS) return;
        state.playheadS = v;
        drawOverview();
    }, 200);

    async function loadOverview() {
        if (!state.sessionId || !(state.durationS > 0)) return;
        const sid = state.sessionId;
        try {
            const env = await fetchEnvelope(sid, 0, state.durationS, OV_POINTS, 'rms');
            if (state.sessionId !== sid) return;
            state.ovEnv = env;
        } catch (_) {
            state.ovEnv = null;
        }
        drawOverview();
    }

    // ── The zoomed view ─────────────────────────────────────────────

    function drawDetail() {
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

        // The fade, drawn on the same dB scale as the level: the gain it
        // puts on the song, from full level (0 dB) to silence at the cut.
        const f = fadeSpan();
        if (f) {
            const fx = xFor(f.out ? f.a : f.b);
            ctx.setLineDash([3, 3]);
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo(fx + 0.5, 0);
            ctx.lineTo(fx + 0.5, h);
            ctx.stroke();
            ctx.setLineDash([]);
            ctx.lineWidth = 2;
            ctx.beginPath();
            const steps = 120;
            for (let i = 0; i <= steps; i++) {
                const u = i / steps;
                const g = f.out ? fadeOutGain(u) : fadeInGain(u);
                const db = g > 0 ? 20 * Math.log10(g) : FLOOR_DB;
                const px = xFor(f.a + u * (f.b - f.a)), py = yFor(db, h);
                if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
            }
            ctx.stroke();
            const label = f.out ? 'fade starts' : 'full level';
            ctx.fillText(label, Math.max(2, Math.min(fx + 4, w - 64)), 23);
        }
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
        const win = windowFor();
        state.holdWin = true;   // the view stays still under the pointer
        const move = (ev) => {
            const r = canvas.getBoundingClientRect();
            const frac = Math.max(0, Math.min(1, (ev.clientX - r.left) / r.width));
            setMarker(win.start + frac * (win.end - win.start));
        };
        move(e);
        const up = () => {
            canvas.removeEventListener('pointermove', move);
            canvas.removeEventListener('pointerup', up);
            state.holdWin = false;
            loadEnvelope();
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
        else return;
        loadEnvelope();
    });

    // Times are typed as m:ss.000 (or plain seconds). A time that cannot
    // be read puts the box back to the current point.
    inMs.addEventListener('change', () => {
        const v = parseClock(inMs.value);
        state.edge = 'head';
        syncEdgeButtons();
        if (v == null) { refreshState(); return; }
        setMarker(v);
        loadEnvelope();
    });
    outMs.addEventListener('change', () => {
        const text = outMs.value.trim();
        const v = text === '' ? state.durationS : parseClock(text);
        state.edge = 'tail';
        syncEdgeButtons();
        if (v == null) { refreshState(); return; }
        setMarker(v);
        loadEnvelope();
    });
    for (const el of [inMs, outMs]) {
        el.addEventListener('keydown', (e) => { if (e.key === 'Enter') el.blur(); });
    }

    // ── Audition ────────────────────────────────────────────────────
    //
    // Plays the ORIGINAL file from the marker. That is exactly what the
    // export will sound like at the edit point, without rendering anything.
    // With a fade set, it plays the whole fade, with the fade's gain.

    function audition() {
        if (!state.blobUrl) return;
        if (!state.audio) state.audio = new Audio();
        const a = state.audio;
        if (!a.paused) { a.pause(); return; }

        a.src = state.blobUrl;
        const f = fadeSpan();
        let from, until;
        if (state.edge === 'head') {
            from = keptStart();
            until = from + Math.max(AUDITION_S, f ? (f.b - f.a) + 1.5 : 0);
        } else if (f) {
            from = Math.max(keptStart(), f.a - FADE_LEAD_S);
            until = keptEnd();
        } else {
            from = Math.max(0, keptEnd() - PREROLL_S);
            until = from + AUDITION_S;
        }

        let raf = 0;
        const gainAt = (t) => {
            if (!f || t < f.a) return f && !f.out ? 0 : 1;
            if (t >= f.b) return f.out ? 0 : 1;
            const u = (t - f.a) / (f.b - f.a);
            return f.out ? fadeOutGain(u) : fadeInGain(u);
        };
        const stop = () => {
            cancelAnimationFrame(raf);
            a.pause();
            a.volume = 1;
            a.removeEventListener('pause', stop);
            auditionBtn.textContent = 'Audition';
        };
        // Frame by frame: the volume follows the fade, and play stops at
        // the cut.
        const frame = () => {
            if (a.paused) return;
            if (a.currentTime >= until) { stop(); return; }
            a.volume = Math.max(0, Math.min(1, gainAt(a.currentTime)));
            raf = requestAnimationFrame(frame);
        };

        a.addEventListener('pause', stop);
        a.addEventListener('ended', stop, { once: true });
        const start = () => {
            a.currentTime = from;
            a.volume = Math.max(0, Math.min(1, gainAt(from)));
            a.play().then(() => { raf = requestAnimationFrame(frame); }).catch(() => {});
        };
        if (a.readyState >= 1) start();
        else a.addEventListener('loadedmetadata', start, { once: true });
        auditionBtn.textContent = 'Stop';
    }

    // ── Wiring ──────────────────────────────────────────────────────

    function syncEdgeButtons() {
        headBtn.classList.toggle('active', state.edge === 'head');
        tailBtn.classList.toggle('active', state.edge === 'tail');
        renderFade();
    }

    function setOpen(open) {
        body.hidden = !open;
        toggleBtn.textContent = open ? 'Close' : 'Open';
        toggleBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
        if (open) {
            if (!state.ovEnv) loadOverview();
            loadEnvelope();
            drawOverview();
        }
    }

    toggleBtn.addEventListener('click', () => setOpen(body.hidden));
    headBtn.addEventListener('click', () => {
        state.edge = 'head'; syncEdgeButtons(); fitZoom(); loadEnvelope();
    });
    tailBtn.addEventListener('click', () => {
        state.edge = 'tail'; syncEdgeButtons(); fitZoom(); loadEnvelope();
    });
    zoomSel.addEventListener('change', loadEnvelope);
    auditionBtn.addEventListener('click', audition);
    clearBtn.addEventListener('click', () => {
        state.inS = 0;
        state.outS = null;
        state.fadeInS = 0;
        state.fadeOutS = 0;
        state.customFade = false;
        refreshState();
        draw();
    });
    fadeInput.addEventListener('change', () => {
        const v = parseFloat(fadeInput.value);
        state.fadeOutS = Number.isFinite(v) && v > 0
            ? Math.min(FADE_MAX_S, Math.round(v * 10) / 10) : 0;
        if (!(state.fadeOutS > 0)) state.customFade = false;
        fitZoom();
        refreshState();
        loadEnvelope();
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
            fadeInS: state.fadeInS > 0 ? state.fadeInS : 0,
            fadeOutS: state.fadeOutS > 0 ? state.fadeOutS : 0,
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
            state.fadeInS = 0;
            state.fadeOutS = 0;
            state.customFade = false;
            state.env = null;
            state.envKey = '';
            state.win = null;
            state.ovEnv = null;
            state.dips = [];
            state.playheadS = null;
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
        setSession(sessionId, durationS, edges, dips) {
            state.sessionId = sessionId;
            state.durationS = durationS || 0;
            state.edges = edges || { found: false, head: null, tail: null };
            state.dips = Array.isArray(dips) ? dips : [];
            showNotice();
            refreshState();
            if (state.edges.found) setOpen(true);
            else if (!body.hidden) { loadOverview(); loadEnvelope(); }
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
