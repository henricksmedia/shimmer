// chain.js — Signal Chain view.
//
// Renders the chain the server derives from the exact settings a
// Clean & Master click would send (POST /api/chain): order from the
// pipeline, numbers from the active preset and strength, both ends from
// the options (Trim, Preserve volume, Export). The server is the single
// source of truth; this file only draws it.
//
// How it is drawn: the stages flow left to right and wrap like text,
// with one continuous wire that drops down and returns to the left edge
// at each row break (no horizontal scrolling). Colour carries meaning:
// each phase of the chain has a hue, and the hues move around the wheel
// in signal order, so the groups read along the path without labels.
// Each card also shows where on the spectrum its stage acts.
//
// Presentational only — modules with user controls deep-link to the
// Advanced drawer, which single.js owns.

// Phase order = signal order = hue order (teal → cyan → blue → violet →
// purple → pink → rose → amber → gold).
export const PHASES = [
    ['edit',      'Edit',      '#2dd4bf'],
    ['repair',    'Repair',    '#22d3ee'],
    ['pre',       'Pre',       '#38bdf8'],
    ['split',     'Split',     '#60a5fa'],
    ['fine',      'Fine pass', '#818cf8'],
    ['engine',    'Engine',    '#a78bfa'],
    ['recombine', 'Recombine', '#c084fc'],
    ['post',      'Post',      '#f472b6'],
    ['level',     'Level',     '#fb7185'],
    ['master',    'Master',    '#f5a524'],
    ['export',    'Export',    '#fbbf24'],
];
const PHASE = Object.fromEntries(PHASES.map(([key, label, color]) => [key, { label, color }]));
const BAND_LO = 40, BAND_HI = 20000;   // log axis for the band bars
const CARD_BADGES = 3;                 // badges shown on a card; the rest in the detail

let chain = null;          // last /api/chain response
let stale = true;          // settings changed while the tab was hidden
let selected = 'shimmer';
let hostEl = null;
let refreshTimer = null;
let wireObserver = null;

function esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
}

function fmtHz(v) {
    v = Number(v) || 0;
    if (v >= 1000) return `${(v / 1000).toFixed(v % 1000 ? 1 : 0)} kHz`;
    return `${Math.round(v)} Hz`;
}

function bandPos(hz) {
    const f = Math.max(BAND_LO, Math.min(BAND_HI, Number(hz) || BAND_LO));
    return (Math.log(f / BAND_LO) / Math.log(BAND_HI / BAND_LO)) * 100;
}

function phaseOf(m) {
    return PHASE[m.phase] || PHASE.engine;
}

function phaseLabel(m) {
    // Keep the engine's stage index and the fine pass's FFT size: they
    // are the useful part of the category text.
    const cat = String(m.cat || '');
    if (m.phase === 'engine' && /^STFT/.test(cat)) return cat.replace(/^STFT/, 'Engine');
    if (m.phase === 'fine') return cat;
    return phaseOf(m).label;
}

// A small log-frequency bar with the stage's band filled in its phase
// colour and a tick at the crossover. Whole-signal stages fill the bar
// faintly; time-only stages (Trim) get no bar.
function bandBar(m, xoverHz, large = false) {
    if (!m.band && m.phase === 'edit') return '';
    const left = m.band ? bandPos(m.band[0]) : 0;
    const right = m.band ? bandPos(m.band[1]) : 100;
    const title = m.band
        ? `acts from ${fmtHz(m.band[0])} to ${fmtHz(m.band[1])}`
        : 'acts on the whole signal';
    const tick = xoverHz ? `<b style="left:${bandPos(xoverHz).toFixed(2)}%"></b>` : '';
    const labels = large
        ? `<div class="m-band-axis"><span>40 Hz</span><span>1 kHz</span><span>20 kHz</span></div>`
        : '';
    return `<div class="m-band ${m.band ? '' : 'whole'}" title="${esc(title)}">
        <div class="m-band-track">${tick}<i style="left:${left.toFixed(2)}%;width:${(right - left).toFixed(2)}%"></i></div>
        ${labels}</div>`;
}

function chainState() {
    try {
        return window.shimmerChainState ? window.shimmerChainState() : {};
    } catch (_) {
        return {};
    }
}

function tabVisible() {
    const panel = document.getElementById('tab-chain');
    return !!(panel && panel.classList.contains('active'));
}

async function refreshChain() {
    if (!hostEl) return;
    try {
        const res = await fetch('/api/chain', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(chainState()),
        });
        if (!res.ok) throw new Error((await res.text()) || `HTTP ${res.status}`);
        chain = await res.json();
        stale = false;
        render();
    } catch (e) {
        const flow = hostEl.querySelector('.chain-flow');
        if (flow) {
            flow.innerHTML =
                `<div class="chain-error">Could not load the signal chain: ${esc(e.message)}</div>`;
        }
    }
}

function scheduleRefresh() {
    if (!tabVisible()) { stale = true; return; }
    clearTimeout(refreshTimer);
    refreshTimer = setTimeout(refreshChain, 150);
}

export function initChainTab() {
    hostEl = document.getElementById('chain-host');
    if (!hostEl) return;

    hostEl.innerHTML = `
        <div class="chain-head">
            <h2>Signal Chain</h2>
            <span class="lede">Every stage your audio passes through, in order, for the preset and options set right now. Follow the wire. Click a stage to read what it does; the bar on each card shows where on the spectrum it works. Dashed stages are in the chain but do nothing for this preset.</span>
        </div>
        <div class="chain-summary"></div>
        <div class="chain-body">
            <div class="chain-flow-wrap">
                <svg class="chain-wire-svg" aria-hidden="true"></svg>
                <div class="chain-flow"><div class="chain-error">Loading…</div></div>
            </div>
            <aside class="chain-detail" id="chain-detail" aria-live="polite"></aside>
        </div>`;

    hostEl.querySelector('.chain-flow').addEventListener('click', (e) => {
        const btn = e.target.closest('.mod');
        if (!btn) return;
        selected = btn.dataset.id;
        hostEl.querySelectorAll('.mod').forEach(x => x.classList.toggle('selected', x === btn));
        renderDetail();
    });

    // The wire follows the real card positions, so redraw on any resize.
    wireObserver = new ResizeObserver(() => drawWire());
    wireObserver.observe(hostEl.querySelector('.chain-flow'));

    // Re-render whenever the Master tab pushes settings (preset, strength,
    // sliders, mastering, EQ, export) and whenever the tab is opened after
    // a change happened while it was hidden.
    document.addEventListener('shimmer:settings-changed', scheduleRefresh);
    document.querySelector('.tab[data-tab="chain"]')?.addEventListener('click', () => {
        if (stale || !chain) {
            clearTimeout(refreshTimer);
            refreshTimer = setTimeout(refreshChain, 0);
        } else {
            requestAnimationFrame(drawWire);
        }
    });

    refreshChain();
}

function render() {
    if (!chain || !hostEl) return;
    const mods = chain.modules || [];
    if (!mods.find(m => m.id === selected)) selected = mods.length ? mods[0].id : null;
    const g = chain.gates || {};
    const s = chain.summary || {};
    const xover = Number(s.crossover_hz || g.low_band_bypass_hz || 0);

    // Summary first: the facts that frame the whole chain, then the
    // phase legend in signal order with on/total counts.
    const flat = Array.isArray(g.flatness) ? g.flatness : [0.25, 0.7];
    const counts = {};
    for (const m of mods) {
        const c = counts[m.phase] || (counts[m.phase] = { on: 0, total: 0 });
        c.total += 1;
        if (m.active) c.on += 1;
    }
    hostEl.querySelector('.chain-summary').innerHTML = `
        <div class="chain-facts">
            <span class="chip amber">${s.active_modules ?? mods.length} of ${mods.length} stages on</span>
            <span class="chip">STFT ${s.n_fft ?? 4096}/${s.hop ?? 1024}${(s.iterations ?? 1) > 1 ? ` · ×${s.iterations} passes` : ''}${s.fine_pass ? ` · fine pass ${s.fine_n_fft}/${s.fine_hop}` : ''}</span>
            <span class="chip">below ${fmtHz(xover)} bypasses cleaning</span>
            <span class="chip" title="Backs cleaning off on tonal frames; fully on above the upper value">gate: flatness ${flat[0]}–${flat[1]}</span>
            <span class="chip" title="Cleaning drops to zero on an attack, holds, then ramps back">gate: transient hold ${Math.round(g.hold_ms ?? 70)} ms + ${Math.round(g.release_ms ?? 160)} ms</span>
        </div>
        <div class="chain-legend">${PHASES.filter(([k]) => counts[k]).map(([k, label, color]) => `
            <span class="leg" style="--phase:${color}"><i></i>${esc(label)} <em>${counts[k].on}/${counts[k].total}</em></span>`).join('')}
        </div>`;

    const flow = hostEl.querySelector('.chain-flow');
    flow.innerHTML = mods.map((m, i) => {
        const ph = phaseOf(m);
        const badges = m.active
            ? (m.badges || []).slice(0, CARD_BADGES).map(b => `<span class="b">${esc(b)}</span>`).join('')
              + ((m.badges || []).length > CARD_BADGES ? `<span class="b more">+${m.badges.length - CARD_BADGES}</span>` : '')
            : `<span class="m-off">off · ${esc(m.off_reason)}</span>`;
        return `
        <button type="button" class="mod ${m.id === selected ? 'selected' : ''} ${m.active ? '' : 'inactive'}"
                data-id="${esc(m.id)}" data-phase="${esc(m.phase)}" style="--phase:${ph.color}"
                ${m.active ? '' : `title="Off: ${esc(m.off_reason)}"`}>
            <div class="m-top"><span class="m-num">${String(i + 1).padStart(2, '0')}</span><span class="m-phase">${esc(phaseLabel(m))}</span></div>
            <div class="m-name">${esc(m.name)}</div>
            <div class="m-gloss">${esc(m.gloss)}</div>
            ${bandBar(m, xover)}
            <div class="m-badges">${badges}</div>
        </button>`;
    }).join('');

    renderDetail();
    // Draw now (a hidden or throttled tab may never get a frame) and again
    // on the next frame once fonts and layout have settled.
    drawWire();
    requestAnimationFrame(drawWire);
}

// One continuous wire through every card. Same row: a straight run from
// the card's right edge to the next card's left edge. Row break: out to
// the right, down into the gap between rows, back to the left edge, down
// to the next card, in. Colour is the phase of the stage being entered;
// a stage that is off gets a dashed segment.
function drawWire() {
    if (!hostEl) return;
    const flow = hostEl.querySelector('.chain-flow');
    const svg = hostEl.querySelector('.chain-wire-svg');
    if (!flow || !svg) return;
    const cards = [...flow.querySelectorAll('.mod')];
    const fr = flow.getBoundingClientRect();
    const w = Math.max(1, Math.round(fr.width));
    const h = Math.max(1, Math.round(fr.height));
    svg.setAttribute('width', w);
    svg.setAttribute('height', h);
    svg.setAttribute('viewBox', `0 0 ${w} ${h}`);
    if (cards.length < 2) { svg.innerHTML = ''; return; }

    const out = [];
    for (let i = 0; i < cards.length - 1; i++) {
        const a = cards[i].getBoundingClientRect();
        const b = cards[i + 1].getBoundingClientRect();
        const ax = a.right - fr.left, ay = a.top - fr.top + a.height / 2;
        const bx = b.left - fr.left, by = b.top - fr.top + b.height / 2;
        const next = cards[i + 1];
        const color = (PHASE[next.dataset.phase] || PHASE.engine).color;
        const dash = next.classList.contains('inactive') ? ' stroke-dasharray="4 4"' : '';
        let d;
        if (Math.abs(ay - by) < 2) {
            d = `M${ax},${ay} H${bx - 6}`;
        } else {
            const gapY = (a.bottom - fr.top) + ((b.top - fr.top) - (a.bottom - fr.top)) / 2;
            d = `M${ax},${ay} H${ax + 10} V${gapY} H${bx - 10} V${by} H${bx - 6}`;
        }
        out.push(`<path d="${d}" fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"${dash} opacity="${next.classList.contains('inactive') ? 0.55 : 0.9}"/>`);
        out.push(`<path d="M${bx - 6},${by - 4} L${bx},${by} L${bx - 6},${by + 4} Z" fill="${color}" opacity="${next.classList.contains('inactive') ? 0.55 : 0.95}"/>`);
    }
    svg.innerHTML = out.join('');
}

function renderDetail() {
    if (!chain || !hostEl) return;
    const mods = chain.modules || [];
    const idx = mods.findIndex(m => m.id === selected);
    const mod = idx >= 0 ? mods[idx] : null;
    const box = hostEl.querySelector('#chain-detail');
    if (!mod) { box.innerHTML = ''; return; }
    const ph = phaseOf(mod);
    const s = chain.summary || {};
    const xover = Number(s.crossover_hz || 0);
    const hasAdv = mod.adv && mod.adv.length;
    const bandText = mod.band
        ? `Works from ${fmtHz(mod.band[0])} to ${fmtHz(mod.band[1])}.`
        : (mod.phase === 'edit' ? 'Works on time, not frequency.' : 'Works on the whole signal.');
    box.style.setProperty('--phase', ph.color);
    box.innerHTML = `
        <div class="cd-phase"><i></i>${esc(phaseLabel(mod))} · stage ${idx + 1} of ${mods.length}</div>
        <h3>${esc(mod.name)}</h3>
        <p class="cd-gloss">${esc(mod.gloss)}</p>
        ${mod.active ? '' : `<p class="chain-off">Off for this preset: ${esc(mod.off_reason)}.</p>`}
        ${bandBar(mod, xover, true)}
        <p class="cd-band">${esc(bandText)}</p>
        <p class="cd-detail">${esc(mod.detail)}</p>
        ${(mod.badges || []).length ? `<div class="cd-badges">${mod.badges.map(b => `<span class="b">${esc(b)}</span>`).join('')}</div>` : ''}
        ${hasAdv
            ? `<button type="button" class="btn btn-ghost" id="chain-open-adv">Open its controls in the Advanced drawer ›</button>`
            : `<p class="cd-note">Set by the preset. No direct control.</p>`}`;
    box.querySelector('#chain-open-adv')?.addEventListener('click', () => {
        document.getElementById('advanced-open-btn')?.click();
    });
}
