// chain.js — the Signal Chain view.
//
// Draws what POST /api/chain says each stage does for the settings on the
// Master tab right now (shimmer.core.chain.describe_chain). The server
// works everything out; this file only draws it.
//
// How it is drawn: the stages flow left to right and wrap like text, with
// one wire that drops down and returns to the left edge at each row break
// (no horizontal scrolling). Each stage has its own colour, in signal
// order (rules.js STAGE_COLOURS). A skipped stage is dashed and says why;
// with mastering off, Master's place shows Preserve volume. Each card also
// shows where on the spectrum its stage acts.

import { STAGE_COLOURS } from './rules.js';

// The Advanced drawer's phase dots (1.x's sliders, single.js). They go
// with the drawer.
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

const LO = 20, HI = 20000;             // band bar: log axis, three decades
const CARD_BADGES = 3;                 // badges shown on a card; the rest in the detail

// Where each detail's button goes on the Master tab.
const TARGETS = {
    trim: '#trim-card', hear: '#hear-card', mastering: '#state-master',
    eq: '#state-eq', output: '#state-output',
};

let chain = null;          // last /api/chain response
let selected = 'master';
let hostEl = null;
let refreshTimer = null;

function esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
}

const pos = (hz) => Math.log10(Math.max(LO, Math.min(HI, Number(hz) || LO)) / LO) / Math.log10(HI / LO) * 100;
const colour = (key) => STAGE_COLOURS[key] || '#94a3b8';
const isOff = (s) => !s.on && !s.standin;

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
        render();
    } catch (e) {
        const flow = hostEl.querySelector('.chain-flow');
        if (flow) {
            flow.innerHTML =
                `<div class="chain-error">Could not load the stages: ${esc(e.message)}</div>`;
        }
    }
}

function scheduleRefresh() {
    if (!tabVisible()) return;          // opening the tab asks again
    clearTimeout(refreshTimer);
    refreshTimer = setTimeout(refreshChain, 150);
}

// A detail's button: open the Master tab at the matching section.
function openTarget(key) {
    document.querySelector('.tab[data-tab="single"]')?.click();
    let el = document.querySelector(TARGETS[key] || '');
    if (!el) return;
    const sec = el.closest('details');
    if (sec) { sec.open = true; el = sec; }
    requestAnimationFrame(() => {
        el.scrollIntoView({ behavior: 'smooth', block: 'start' });
        el.classList.add('flash');
        setTimeout(() => el.classList.remove('flash'), 1200);
    });
}

export function initChainTab() {
    hostEl = document.getElementById('chain-host');
    if (!hostEl) return;

    hostEl.innerHTML = `
        <div class="chain-head">
            <h2>Signal Chain</h2>
            <span class="lede">Every stage your song passes through, in order, for the settings on the Master tab right now. Click a stage to read what it does. Dashed stages are skipped for these settings.</span>
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
        selected = btn.dataset.key;
        hostEl.querySelectorAll('.mod').forEach(x => x.classList.toggle('selected', x === btn));
        renderDetail();
    });
    hostEl.querySelector('#chain-detail').addEventListener('click', (e) => {
        const btn = e.target.closest('[data-go]');
        if (btn) openTarget(btn.dataset.go);
    });

    // The wire follows the real card positions, so redraw on any resize.
    new ResizeObserver(() => drawWire()).observe(hostEl.querySelector('.chain-flow'));

    // Re-render whenever the Master tab pushes settings, and every time the
    // tab is opened: a song, a reference or a noted card can change without
    // a settings push.
    document.addEventListener('shimmer:settings-changed', scheduleRefresh);
    document.querySelector('.tab[data-tab="chain"]')?.addEventListener('click', () => {
        clearTimeout(refreshTimer);
        refreshTimer = setTimeout(refreshChain, 0);
    });

    refreshChain();
}

function badge(text, nb) {
    return `<span class="b${nb ? ' sc-nb' : ''}">${esc(text)}</span>`;
}

function badges(s) {
    const nb = new Set(s.nb_badges || []);
    return (s.badges || []).map(t => badge(t, nb.has(t)));
}

// A small log-frequency bar, 20 Hz to 20 kHz: notches as thin marks, the
// range each running fix works in as a filled span, a whole-signal stage
// faintly filled, a tick at the low-cut.
function bandBar(s, large) {
    const b = s.band;
    if (!b) return '';
    let fill = '', cls = '';
    if (b.notches || b.ranges) {
        fill = (b.ranges || []).map(([lo, hi]) => {
            const a = pos(lo);
            return `<i style="left:${a.toFixed(2)}%;width:${Math.max(1, pos(hi) - a).toFixed(2)}%"></i>`;
        }).join('')
            + (b.notches || []).map(hz => `<i style="left:${(pos(hz) - 0.5).toFixed(2)}%;width:1%"></i>`).join('');
    } else if (b.whole) {
        cls = 'whole';
        const left = b.from ? pos(b.from) : 0;
        fill = `<i style="left:${left.toFixed(2)}%;width:${(100 - left).toFixed(2)}%"></i>`;
    }
    const tick = b.tick ? `<b style="left:${pos(b.tick).toFixed(2)}%"></b>` : '';
    const axis = large ? '<div class="m-band-axis"><span>20 Hz</span><span>200 Hz</span><span>2 kHz</span><span>20 kHz</span></div>' : '';
    return `<div class="m-band ${cls}"><div class="m-band-track">${tick}${fill}</div>${axis}</div>`;
}

function cardHtml(s, i) {
    const cls = ['mod', s.key === selected ? 'selected' : '', isOff(s) ? 'inactive' : '', s.standin ? 'sc-standin' : '']
        .filter(Boolean).join(' ');
    const tag = isOff(s) ? '<span class="sc-skip">Skipped</span>'
        : (s.tag ? `<span class="sc-skip">${esc(s.tag)}</span>` : '');
    const bs = badges(s);
    const body = isOff(s)
        ? `<span class="m-off">${esc(s.off)}</span>`
        : bs.slice(0, CARD_BADGES).join('') + (bs.length > CARD_BADGES ? `<span class="b more">+${bs.length - CARD_BADGES}</span>` : '');
    return `<button type="button" class="${cls}" data-key="${esc(s.key)}" style="--phase:${colour(s.key)}"${isOff(s) ? ` title="Skipped: ${esc(s.off)}"` : ''}>
        <div class="m-top"><span class="m-num">${String(i + 1).padStart(2, '0')}</span><span class="m-phase">${esc(s.stage)}</span>${tag}</div>
        <div class="m-name">${esc(s.name)}</div>
        <div class="m-gloss">${esc(s.gloss)}</div>
        ${bandBar(s, false)}
        <div class="m-badges">${body}</div>
    </button>`;
}

function fxRow(f) {
    const tag = f.tag || {};
    const tagStyle = tag.stage ? ` style="--tag:${colour(tag.stage)}"` : '';
    return `<div class="sc-fx-row${f.muted ? ' muted' : ''}">
        <span class="sc-ms" aria-hidden="true">${esc(f.icon)}</span>
        <div class="sc-fx-what"><b>${esc(f.label)}</b>${f.tool ? ` <em>· ${esc(f.tool)}</em>` : ''}<span>${esc(f.text)}</span></div>
        <span class="sc-tag ${esc(tag.kind)}"${tagStyle}>${esc(tag.text)}</span>
    </div>`;
}

function detailHtml(s, i, n) {
    let h = `<div class="cd-phase"><i></i>${esc(s.stage)} · stage ${i + 1} of ${n}</div><h3>${esc(s.name)}</h3>`;
    if (isOff(s)) h += `<p class="chain-off">Skipped: ${esc(s.off)}.</p>`;
    if (s.off_line) h += `<p class="chain-off">${esc(s.off_line)}</p>`;
    if (s.verdict && !isOff(s)) h += `<p class="sc-cd-verdict">${esc(s.verdict)}</p>`;
    h += `<p class="cd-gloss">${esc(s.gloss)}</p>`;
    if (s.band) h += bandBar(s, true) + `<p class="cd-band">${esc(s.band_text)}</p>`;
    (s.paras || []).forEach((p) => { h += `<p class="cd-detail">${esc(p)}</p>`; });
    if ((s.steps || []).length) {
        h += `<ol class="sc-steps">${s.steps.map(([t, d]) => `<li><b>${esc(t)}</b><span>${esc(d)}</span></li>`).join('')}</ol>`;
    }
    if ((s.fixes || []).length) h += `<div class="sc-cd-label">Cards that are on</div><div class="sc-fx">${s.fixes.map(fxRow).join('')}</div>`;
    if ((s.noted || []).length) h += `<div class="sc-cd-label">Noted</div><div class="sc-fx">${s.noted.map(fxRow).join('')}</div>`;
    if ((s.checks || []).length) {
        h += `<div class="sc-cd-label">What it checks</div><div class="cd-badges">${s.checks.map(c => badge(c)).join('')}</div>`;
    } else if ((s.badges || []).length && !isOff(s)) {
        h += `<div class="cd-badges">${badges(s).join('')}</div>`;
    }
    if (s.action) h += `<button type="button" class="btn btn-ghost" data-go="${esc(s.action.target)}">${esc(s.action.label)} ›</button>`;
    else if (s.note) h += `<p class="cd-note">${esc(s.note)}</p>`;
    return h;
}

function render() {
    if (!chain || !hostEl) return;
    const stages = chain.stages || [];
    if (!stages.find(s => s.key === selected)) selected = stages.length ? stages[0].key : null;
    const sum = chain.summary || {};

    hostEl.querySelector('.chain-summary').innerHTML = `
        <div class="sc-verdict"><b>${sum.on ?? 0} of ${sum.total ?? stages.length}</b> stages on. ${esc(sum.text)}</div>
        <div class="chain-facts">${(sum.facts || []).map(f => `<span class="chip">${esc(f)}</span>`).join('')}</div>`;

    hostEl.querySelector('.chain-flow').innerHTML = stages.map(cardHtml).join('');
    renderDetail();
    // Draw now (a hidden or throttled tab may never get a frame) and again
    // on the next frame once fonts and layout have settled.
    drawWire();
    requestAnimationFrame(drawWire);
}

function renderDetail() {
    if (!chain || !hostEl) return;
    const stages = chain.stages || [];
    const i = stages.findIndex(s => s.key === selected);
    const box = hostEl.querySelector('#chain-detail');
    if (i < 0) { box.innerHTML = ''; return; }
    box.style.setProperty('--phase', colour(stages[i].key));
    box.innerHTML = detailHtml(stages[i], i, stages.length);
}

// One continuous wire through every card. Same row: a straight run from
// the card's right edge to the next card's left edge. Row break: out to
// the right, down into the gap between rows, back to the left edge, down
// to the next card, in. Colour is the stage being entered; a skipped
// stage gets a dashed segment.
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
        const color = colour(next.dataset.key);
        const off = next.classList.contains('inactive');
        let d;
        if (Math.abs(ay - by) < 2) {
            d = `M${ax},${ay} H${bx - 6}`;
        } else {
            const gapY = (a.bottom - fr.top) + ((b.top - fr.top) - (a.bottom - fr.top)) / 2;
            d = `M${ax},${ay} H${ax + 10} V${gapY} H${bx - 10} V${by} H${bx - 6}`;
        }
        out.push(`<path d="${d}" fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"${off ? ' stroke-dasharray="4 4"' : ''} opacity="${off ? 0.55 : 0.9}"/>`);
        out.push(`<path d="M${bx - 6},${by - 4} L${bx},${by} L${bx - 6},${by + 4} Z" fill="${color}" opacity="${off ? 0.55 : 0.95}"/>`);
    }
    svg.innerHTML = out.join('');
}
