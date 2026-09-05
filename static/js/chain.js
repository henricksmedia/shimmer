// chain.js — Signal Chain view.
//
// Renders the chain the server derives from the exact settings a
// Clean & Master click would send (POST /api/chain): order from the
// pipeline, numbers from the active preset and strength, both ends from
// the options (Trim, Preserve volume, Export). It used to be a
// hand-written list here, which was right about the order and wrong
// about the numbers whenever a preset moved the crossover or the Mid
// scale. Now the server is the single source of truth and this file only
// draws it.
//
// Presentational only — modules with user controls deep-link to the
// Advanced drawer, which single.js owns.

let chain = null;          // last /api/chain response
let stale = true;          // settings changed while the tab was hidden
let selected = 'shimmer';
let hostEl = null;
let refreshTimer = null;

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
        const lane = hostEl.querySelector('.chain-lane');
        if (lane) {
            lane.innerHTML =
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
            <span class="lede">Every stage your audio passes through, in order, for the preset and options you have set right now. Click a module to learn what it does — stages with sliders open the Advanced drawer. Dashed modules are in the chain but do nothing for this preset.</span>
        </div>
        <div class="chain-scroll"><div class="chain-lane"><div class="chain-error">Loading…</div></div></div>
        <div class="chain-gates"></div>
        <div class="chain-detail" id="chain-detail"></div>`;

    hostEl.querySelector('.chain-lane').addEventListener('click', (e) => {
        const btn = e.target.closest('.mod');
        if (!btn) return;
        selected = btn.dataset.id;
        hostEl.querySelectorAll('.mod').forEach(x => x.classList.toggle('selected', x === btn));
        renderDetail();
    });

    // Re-render whenever the Master tab pushes settings (preset, strength,
    // sliders, mastering, EQ, export) and whenever the tab is opened after
    // a change happened while it was hidden.
    document.addEventListener('shimmer:settings-changed', scheduleRefresh);
    document.querySelector('.tab[data-tab="chain"]')?.addEventListener('click', () => {
        if (stale || !chain) {
            clearTimeout(refreshTimer);
            refreshTimer = setTimeout(refreshChain, 0);
        }
    });

    refreshChain();
}

function render() {
    if (!chain || !hostEl) return;
    const mods = chain.modules || [];
    if (!mods.find(m => m.id === selected)) selected = mods.length ? mods[0].id : null;

    const lane = hostEl.querySelector('.chain-lane');
    lane.innerHTML = mods.map((m, i) => `
        ${i > 0 ? '<div class="chain-wire"></div>' : ''}
        <button type="button" class="mod ${m.id === selected ? 'selected' : ''} ${m.active ? '' : 'inactive'}"
                data-id="${esc(m.id)}" ${m.active ? '' : `title="Off: ${esc(m.off_reason)}"`}>
            <div class="m-cat">${esc(m.cat)}</div>
            <div class="m-name">${esc(m.name)}</div>
            <div class="m-gloss">${esc(m.gloss)}</div>
            <div class="m-badges">${m.active
                ? (m.badges || []).map(b => `<span class="b">${esc(b)}</span>`).join('')
                : '<span class="b off">off</span>'}</div>
        </button>`).join('');

    const g = chain.gates || {};
    const s = chain.summary || {};
    const flat = Array.isArray(g.flatness) ? g.flatness : [0.25, 0.7];
    hostEl.querySelector('.chain-gates').innerHTML = `
        <span class="chip cyan" title="Backs cleaning off on tonal frames; fully on above the upper value">⛩ Spectral-Flatness Gate ${flat[0]}–${flat[1]}</span>
        <span class="chip cyan" title="Cleaning drops to zero on an attack, holds, then ramps back">⛩ Transient Hold ${Math.round(g.hold_ms ?? 70)} ms + ${Math.round(g.release_ms ?? 160)} ms release</span>
        <span class="chip">low band &lt; ${fmtHz(g.low_band_bypass_hz ?? 4500)} bypasses cleaning</span>
        <span class="chip">STFT ${s.n_fft ?? 4096}/${s.hop ?? 1024}${(s.iterations ?? 1) > 1 ? ` · ×${s.iterations} passes` : ''}</span>
        <span class="chip">${s.active_modules ?? mods.length} of ${mods.length} modules active</span>`;

    renderDetail();
}

function renderDetail() {
    if (!chain || !hostEl) return;
    const mod = (chain.modules || []).find(m => m.id === selected);
    const box = hostEl.querySelector('#chain-detail');
    if (!mod) { box.innerHTML = ''; return; }
    const hasAdv = mod.adv && mod.adv.length;
    box.innerHTML = `
        <h3>${esc(mod.name)}${mod.active ? '' : ' <span class="chip">off for this preset</span>'}</h3>
        ${mod.active ? '' : `<p class="chain-off">${esc(mod.off_reason)}</p>`}
        <p>${esc(mod.detail)}</p>
        ${(mod.badges || []).length ? `<div class="m-badges">${mod.badges.map(b => `<span class="b">${esc(b)}</span>`).join('')}</div>` : ''}
        ${hasAdv
            ? `<button type="button" class="btn btn-ghost" id="chain-open-adv">Open its controls in the Advanced drawer ›</button>`
            : `<span class="chip">tuned per preset — no direct user control</span>`}`;
    box.querySelector('#chain-open-adv')?.addEventListener('click', () => {
        document.getElementById('advanced-open-btn')?.click();
    });
}
