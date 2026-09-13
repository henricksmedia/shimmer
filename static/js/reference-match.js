// reference-match.js — Tone target in the Master tab's Mastering section:
// Shimmer's built-in target, or a reference track the user picks. From the
// approved mockup, static/tmp/shimmer-reference-match-mockup.html.
//
// The reference is loaded into the song's session (POST /api/reference).
// What the match will do comes from the engine (POST /api/reference/view):
// the same EQ curve the render applies, both tone shapes, where the top is
// not matched, and whether the drums differ a lot. This file draws it.

const TILT_KEYS = ['warmer', 'warm', 'neutral', 'bright', 'brightest'];

const minus = (s) => String(s).replace('-', '−');
const fmtF = (f) => (f >= 1000 ? `${f / 1000} kHz` : `${f} Hz`);
const fmtDb = (d) => (d > 0 ? '+' : d < 0 ? '−' : '') + Math.abs(d).toFixed(1) + ' dB';
function mmss(s) {
    const t = Math.max(0, Math.round(s || 0));
    return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, '0')}`;
}
function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
}

// The biggest move in the low end, the mids and the top, in plain words.
function verdictHtml(freqs, delta, limit) {
    const zones = [['low end', (f) => f < 250], ['mids', (f) => f >= 250 && f < 5000],
                   ['top end', (f) => f >= 5000]];
    const out = [];
    zones.forEach(([name, inZone]) => {
        const idx = freqs.map((f, i) => i).filter((i) => inZone(freqs[i]));
        let best = idx[0];
        idx.forEach((i) => { if (Math.abs(delta[i]) > Math.abs(delta[best])) best = i; });
        const d = delta[best];
        if (Math.abs(d) < 0.3) return;
        // Several bands at the same level: name the middle one.
        const ties = idx.filter((i) => Math.sign(delta[i]) === Math.sign(d)
            && Math.abs(Math.abs(delta[i]) - Math.abs(d)) < 0.05);
        const i = ties[Math.floor((ties.length - 1) / 2)];
        let note = '';
        if (Math.abs(d) >= limit - 0.05) note = ` <i>· at the ±${limit} dB limit</i>`;
        else if (d >= 1.95 && freqs[i] >= 5000 && freqs[i] <= 12000) note = ' <i>· at the +2 dB cap</i>';
        out.push(`<span>${d > 0 ? 'More' : 'Less'} ${name}: up to <b>${fmtDb(d)}</b> at ${fmtF(freqs[i])}${note}</span>`);
    });
    return out.length ? out.join('') : '<span>Almost no change at this Amount.</span>';
}

// Chart geometry, in viewBox units (280 wide = the real pixel width).
const X0 = 26, X1 = 274, F_LO = 31.5, SPAN = Math.log(20000 / F_LO);
const fx = (f) => X0 + Math.log(f / F_LO) / SPAN * (X1 - X0);
const T0 = 16, T1 = 90, TMAX = 10, TMIN = -25;            // tone panel
const ty = (db) => T0 + (TMAX - db) / (TMAX - TMIN) * (T1 - T0);
const E0 = 112, E1 = 152, EC = 132;                        // EQ panel, ±3 dB
const ey = (db, limit) => EC - db / limit * 20;

function drawChart(svg, v) {
    const F = v.freqs_hz, limit = v.limit_db || 3;
    const cut = v.matched_up_to_hz;
    let s = `<defs><pattern id="rm-hatch" width="4" height="4" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
    <rect width="4" height="4" fill="rgba(125,136,148,.06)"/><line x1="0" y1="0" x2="0" y2="4" stroke="rgba(125,136,148,.4)" stroke-width="1"/></pattern>
    <clipPath id="rm-clip"><rect x="${X0}" y="${T0}" width="${X1 - X0}" height="${T1 - T0}"/></clipPath></defs>`;
    s += `<text class="ttl" x="${X0}" y="11">Tone, level-matched</text>`;
    s += `<text class="ttl" x="${X0}" y="107">EQ Shimmer applies</text>`;
    [[50, '50'], [100, '100'], [200, '200'], [500, '500'], [1000, '1k'], [2000, '2k'],
     [5000, '5k'], [10000, '10k'], [20000, '20k']].forEach(([f, l], n, all) => {
        const x = fx(f).toFixed(1);
        s += `<line class="grid" opacity=".5" x1="${x}" x2="${x}" y1="${T0}" y2="${T1}"/>`;
        s += `<line class="grid" opacity=".5" x1="${x}" x2="${x}" y1="${E0}" y2="${E1}"/>`;
        s += `<text x="${x}" y="167" text-anchor="${n === all.length - 1 ? 'end' : 'middle'}">${l}</text>`;
    });
    [0, -10, -20].forEach((db) => {
        const y = ty(db);
        s += `<line class="${db === 0 ? 'zero' : 'grid'}" x1="${X0}" x2="${X1}" y1="${y.toFixed(1)}" y2="${y.toFixed(1)}"/>`;
        s += `<text x="${X0 - 4}" y="${(y + 3).toFixed(1)}" text-anchor="end">${minus(db)}</text>`;
    });
    [limit, 0, -limit].forEach((db) => {
        const y = ey(db, limit);
        s += `<line class="${db === 0 ? 'zero' : 'lim'}" x1="${X0}" x2="${X1}" y1="${y}" y2="${y}"/>`;
        s += `<text x="${X0 - 4}" y="${y + 3}" text-anchor="end">${db > 0 ? '+' + db : minus(db)}</text>`;
    });
    if (cut) {
        const xa = fx(cut);
        s += `<rect x="${xa.toFixed(1)}" y="${T0}" width="${(X1 - xa).toFixed(1)}" height="${T1 - T0}" fill="url(#rm-hatch)"/>`;
        s += `<rect x="${xa.toFixed(1)}" y="${E0}" width="${(X1 - xa).toFixed(1)}" height="${E1 - E0}" fill="url(#rm-hatch)"/>`;
        s += `<text class="nm" x="${(xa - 3).toFixed(1)}" y="${T0 + 9}" text-anchor="end">not matched above ${minus((cut / 1000).toFixed(1))} kHz</text>`;
    }
    const path = (arr) => arr.map((d, i) => `${i ? 'L' : 'M'}${fx(F[i]).toFixed(1)} ${ty(d).toFixed(1)}`).join('');
    s += `<g clip-path="url(#rm-clip)"><path class="song" d="${path(v.song_db)}"/><path class="ref" d="${path(v.reference_db)}"/></g>`;
    v.curve_db.forEach((d, i) => {
        if (Math.abs(d) < 0.05) return;
        const y0 = ey(0, limit), y1 = ey(d, limit);
        s += `<rect class="bar" x="${(fx(F[i]) - 2.5).toFixed(1)}" y="${Math.min(y0, y1).toFixed(1)}" width="5" height="${Math.abs(y1 - y0).toFixed(1)}" rx="1"/>`;
    });
    svg.innerHTML = s;
}

function message(kind, title, body, action) {
    const m = el('div', `rm-msg ${kind}`);
    const i = el('span', 'ms', kind === 'warn' ? 'warning' : 'info');
    i.setAttribute('aria-hidden', 'true');
    const txt = el('div');
    txt.append(el('b', null, title), body);
    if (action) { txt.append(document.createElement('br'), action); }
    m.append(i, txt);
    return m;
}

/**
 * Wire the Tone target cards and the reference box.
 *   getSessionId()  the song's session, or null
 *   basePayload()   the preview's body (session and settings), for the view
 *   onChange()      settings changed: save them and render the preview
 * Returns { payload(), isOn(), refresh(), reset(), setAmount(pct) }.
 */
export function initReferenceMatch({ getSessionId, basePayload, onChange }) {
    const $ = (id) => document.getElementById(id);
    const els = {
        builtin: $('tt-builtin'), reference: $('tt-reference'), input: $('ref-file-input'),
        box: $('ref-box'), name: $('ref-name'), meta: $('ref-meta'), remove: $('ref-remove'),
        msgs: $('ref-msgs'), verdict: $('ref-verdict'), chart: $('ref-chart'),
        matchField: $('tone-match-field'), amountField: $('ref-amount-field'),
        amount: $('ref-amount'), amountVal: $('ref-amount-val'), hint: $('ref-amount-hint'),
        limits: $('ref-limits'),
    };
    const api = { payload: () => ({}), isOn: () => false, refresh() {}, reset() {}, setAmount() {} };
    if (!els.builtin || !els.reference) return api;
    const st = { on: false, info: null, view: null, timer: null, seq: 0, note: '' };

    const amount = () => Math.max(0, Math.min(100, Number(els.amount.value) || 0));

    function sync() {
        const on = st.on && !!st.info;
        [[els.builtin, !on], [els.reference, on]].forEach(([b, sel]) => {
            b.classList.toggle('on', sel);
            b.setAttribute('aria-checked', sel ? 'true' : 'false');
        });
        els.box.hidden = !(on || st.note);
        els.matchField.hidden = on;
        els.amountField.hidden = !on;
        els.limits.hidden = !on;
        els.amountVal.textContent = `${amount()}%`;
        els.hint.classList.toggle('over', amount() > 50);
        if (st.note && !on) {
            // "Load your song first" and the like, before a reference is loaded.
            els.name.textContent = '';
            els.meta.textContent = '';
            els.remove.hidden = true;
            els.msgs.textContent = '';
            els.msgs.append(message('info', st.note, ''));
            els.verdict.textContent = '';
            els.chart.innerHTML = '';
            return;
        }
        els.remove.hidden = false;
        if (!on) return;
        const i = st.info;
        els.name.textContent = i.name;
        const rate = i.cutoff_hz ? `stops at ${Math.round(i.cutoff_hz / 1000)} kHz`
            : `${(i.sample_rate / 1000).toFixed(1).replace(/\.0$/, '')} kHz`;
        els.meta.textContent = `${mmss(i.duration_s)} · ${i.format} · ${rate}`;
    }

    function drawView() {
        const v = st.view;
        els.msgs.textContent = '';
        if (!v) { els.verdict.textContent = ''; els.chart.innerHTML = ''; return; }
        const p = v.percussive || {};
        if (p.differs) {
            const set = el('button', 'linklike', 'Set Amount to 25%');
            set.type = 'button';
            set.addEventListener('click', () => api.setAmount(25));
            els.msgs.append(message('warn',
                `The reference is much ${p.differs} percussive than your song.`,
                ' Matches like this tend to push the bass and top too far. Try a lower Amount, or a reference closer in style.',
                set));
        }
        if (v.matched_up_to_hz) {
            const k = (v.matched_up_to_hz / 1000).toFixed(1);
            const stop = Math.round((v.reference_cutoff_hz || v.matched_up_to_hz / 0.9) / 1000);
            els.msgs.append(message('info', `Top not matched above ${k} kHz.`,
                ` This ${(st.info && st.info.format) || 'file'} stops at ${stop} kHz, so it has nothing up there to compare. Your song's own top is kept.`));
        }
        els.verdict.innerHTML = verdictHtml(v.freqs_hz, v.curve_db, v.limit_db || 3);
        drawChart(els.chart, v);
    }

    async function fetchView() {
        if (!(st.on && st.info) || !getSessionId()) return;
        const seq = ++st.seq;
        try {
            const r = await fetch('/api/reference/view', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(basePayload()),
            });
            if (!r.ok) throw new Error(`view ${r.status}`);
            const v = await r.json();
            if (seq !== st.seq) return;          // a newer request is on its way
            st.view = v;
        } catch (_) {
            if (seq !== st.seq) return;
            st.view = null;
        }
        drawView();
    }
    function refresh(delay = 250) {
        clearTimeout(st.timer);
        st.timer = setTimeout(fetchView, delay);
    }

    async function upload(file) {
        const sid = getSessionId();
        if (!sid) { st.note = 'Load your song first, then pick a reference.'; sync(); return; }
        st.note = '';
        const form = new FormData();
        form.append('session_id', sid);
        form.append('file', file);
        els.box.hidden = false;
        els.name.textContent = file.name;
        els.meta.textContent = 'Measuring…';
        try {
            const r = await fetch('/api/reference', { method: 'POST', body: form });
            if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `upload ${r.status}`);
            st.info = (await r.json()).reference;
            st.on = true;
        } catch (e) {
            st.info = null;
            st.on = false;
            st.note = `Could not load that file: ${e.message}`;
        }
        sync();
        if (st.on) { refresh(0); onChange(); }
    }

    els.builtin.addEventListener('click', () => {
        if (!st.on && !st.note) return;
        st.on = false;
        st.note = '';
        sync();
        onChange();
    });
    els.reference.addEventListener('click', () => {
        if (st.info) {
            st.on = true;
            sync();
            refresh(0);
            onChange();
            return;
        }
        els.input.value = '';
        els.input.click();
    });
    els.input.addEventListener('change', () => {
        const f = els.input.files && els.input.files[0];
        if (f) upload(f);
    });
    els.remove.addEventListener('click', async () => {
        const sid = getSessionId();
        st.on = false;
        st.info = null;
        st.view = null;
        sync();
        onChange();
        if (sid) { try { await fetch(`/api/reference/${sid}`, { method: 'DELETE' }); } catch (_) { /* gone */ } }
    });
    els.amount.addEventListener('input', () => {
        els.amountVal.textContent = `${amount()}%`;
        els.hint.classList.toggle('over', amount() > 50);
        refresh();
    });
    els.amount.addEventListener('change', () => onChange());

    api.payload = () => (st.on && st.info
        ? { tone_target: 'reference', match_amount: amount() / 100 } : {});
    api.isOn = () => !!(st.on && st.info);
    api.refresh = () => refresh();
    // A new song: the reference lived in the old song's session.
    api.reset = () => {
        st.on = false;
        st.info = null;
        st.view = null;
        st.note = '';
        sync();
    };
    api.setAmount = (pct) => {
        els.amount.value = String(pct);
        els.amountVal.textContent = `${amount()}%`;
        els.hint.classList.toggle('over', amount() > 50);
        refresh(0);
        onChange();
    };
    sync();
    return api;
}

export { TILT_KEYS };
