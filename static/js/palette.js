// palette.js — Ctrl+K command palette.  Fuzzy search over views, presets,
// transport, and help topics.  Drives existing controls (tab buttons, the
// preset <select>, the player play button) so no other module changes.

import { openHelp } from './help.js';

let veil, input, list, items = [], sel = 0;

function buildActions() {
    const acts = [
        { label: 'Go to Master',        cat: 'view', run: () => clickTab('single') },
        { label: 'Go to Remix (Stems)', cat: 'view', run: () => clickTab('remix') },
        { label: 'Go to Batch',         cat: 'view', run: () => clickTab('batch') },
        { label: 'Go to Signal Chain',  cat: 'view', run: () => clickTab('chain') },
        { label: 'Play / Pause',        cat: 'transport', run: () => document.getElementById('player-play')?.click() },
        { label: 'A/B: Original (1)',   cat: 'transport', run: () => clickTrack('original') },
        { label: 'A/B: Processed (2)',  cat: 'transport', run: () => clickTrack('processed') },
        { label: 'A/B: Removed (3)',    cat: 'transport', run: () => clickTrack('removed') },
        { label: 'Open Advanced artifact controls', cat: 'action', run: () => document.getElementById('advanced-open-btn')?.click() },
        { label: 'Analyze current file', cat: 'action', run: () => document.getElementById('analyze-btn')?.click() },
        { label: 'Help: Quick start',    cat: 'help', run: () => openHelp('quickstart') },
        { label: 'Help: Pick a preset',  cat: 'help', run: () => openHelp('presets') },
        { label: 'Help: Troubleshoot',   cat: 'help', run: () => openHelp('trouble') },
        { label: 'Help: Setup (ffmpeg)', cat: 'help', run: () => openHelp('setup') },
    ];
    const presetSelect = document.getElementById('preset-select');
    if (presetSelect) {
        for (const opt of presetSelect.options) {
            acts.push({
                label: `Preset: ${opt.textContent}`,
                cat: 'preset',
                run: () => {
                    presetSelect.value = opt.value;
                    presetSelect.dispatchEvent(new Event('change', { bubbles: true }));
                    clickTab('single');
                },
            });
        }
    }
    return acts;
}

function clickTab(name) {
    document.querySelector(`.tab[data-tab="${name}"]`)?.click();
}
function clickTrack(track) {
    document.querySelector(`#track-tabs [data-track="${track}"]`)?.click();
}

export function initPalette() {
    veil = document.createElement('div');
    veil.className = 'palette-veil';
    veil.innerHTML = `<div class="palette"><input placeholder="Search presets, views, actions…" aria-label="Command palette"><div class="p-list"></div></div>`;
    document.body.appendChild(veil);
    input = veil.querySelector('input');
    list = veil.querySelector('.p-list');

    veil.addEventListener('click', (e) => { if (e.target === veil) close(); });
    input.addEventListener('input', () => render(input.value));
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') { close(); e.stopPropagation(); }
        if (e.key === 'ArrowDown') { sel = Math.min(items.length - 1, sel + 1); paint(); e.preventDefault(); }
        if (e.key === 'ArrowUp')   { sel = Math.max(0, sel - 1); paint(); e.preventDefault(); }
        if (e.key === 'Enter' && items[sel]) { const a = items[sel]; close(); a.run(); }
    });

    window.addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
            e.preventDefault();
            open();
        }
    });
}

function render(q) {
    const ql = q.toLowerCase();
    items = buildActions().filter(a => a.label.toLowerCase().includes(ql)).slice(0, 12);
    sel = 0;
    paint();
}

function paint() {
    list.innerHTML = items.map((a, i) =>
        `<button type="button" class="p-item ${i === sel ? 'sel' : ''}" data-i="${i}">${a.label}<span class="p-cat">${a.cat}</span></button>`).join('');
    list.querySelectorAll('.p-item').forEach(b =>
        b.addEventListener('click', () => { const a = items[+b.dataset.i]; close(); a.run(); }));
}

function open() { veil.classList.add('open'); input.value = ''; render(''); input.focus(); }
function close() { veil.classList.remove('open'); }
