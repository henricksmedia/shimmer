// preset-browser.js — searchable, symptom-grouped preset browser.
// The hidden #preset-select stays the single source of truth: clicking an
// item sets select.value and dispatches `change`, so preset.js, settings
// persistence, auto-detect Apply, and the palette all keep working
// unchanged.  The browser listens for that same `change` event to stay
// in sync with every programmatic path.

import { fetchPresets } from './api.js';

// Symptom grouping for the visible artifact presets.  Keys not listed
// fall into "More".
const GROUPS = [
    { label: 'Start here',       keys: ['generic'] },
    { label: 'Flicker & hash',   keys: ['suno_hash', 'broadband_fizz', 'checkerboard_grid'] },
    { label: 'Cymbals & highs',  keys: ['cymbal_sheen', 'cymbal_chatter', 'phantom_cymbal', 'air_brittle'] },
    { label: 'Whistles & tones', keys: ['laser_whistle', 'echo_sheen', 'reverb_flutter'] },
    { label: 'Vocals',           keys: ['sibilance_rattle', 'vocal_glaze', 'vocal_glaze_plus', 'presence_haze'] },
    { label: 'Broadband rescue', keys: ['harsh_veil', 'deep_scrub'] },
    { label: 'Tone rescue',      keys: ['muddy_boxy', 'dark_mix_rescue'] },
];

export async function initPresetBrowser({ selectEl, hostEl }) {
    if (!selectEl || !hostEl) return;

    const { presets } = await fetchPresets();
    const visible = presets.filter(p => p.visible !== false);
    const byName = new Map(visible.map(p => [p.name, p]));

    // Group visible presets; anything unmapped goes in "More".
    const grouped = GROUPS
        .map(g => ({ label: g.label, items: g.keys.map(k => byName.get(k)).filter(Boolean) }))
        .filter(g => g.items.length);
    const mapped = new Set(GROUPS.flatMap(g => g.keys));
    const rest = visible.filter(p => !mapped.has(p.name));
    if (rest.length) grouped.push({ label: 'More', items: rest });

    hostEl.innerHTML = `
        <div class="pb-search">
            <span aria-hidden="true">🔎</span>
            <input type="text" placeholder="Search ${visible.length} presets…" aria-label="Search presets">
        </div>
        <div class="pb-list"></div>
        <div class="pb-effect" title="What this preset dials into the cleaning engine — open Advanced artifact controls to fine-tune"></div>`;
    const searchInput = hostEl.querySelector('input');
    const listEl = hostEl.querySelector('.pb-list');
    const effectEl = hostEl.querySelector('.pb-effect');

    // Compact "what this preset changes" readout: the moves that matter,
    // rendered as chips so choosing a preset visibly does something.
    function paintEffect() {
        const p = byName.get(selectEl.value);
        const v = p?.values;
        if (!v) { effectEl.innerHTML = ''; return; }
        const chips = [];
        const kHz = (x) => (x >= 1000 ? `${(x / 1000).toFixed(x % 1000 ? 1 : 0)}k` : x);
        if (v.start_hz != null && v.end_hz != null) chips.push(`band ${kHz(v.start_hz)}–${kHz(v.end_hz)} Hz`);
        if (v.thr_db != null) chips.push(`threshold ${v.thr_db} dB`);
        const amounts = [['denoise', 'denoise'], ['deres', 'de-resonate'], ['deharsh', 'de-harsh'], ['decheck', 'de-checker'],
                         ['tone_kill', 'tone kill'], ['flicker_tame', 'flicker tame'], ['noise_resynth', 'resynth']];
        for (const [key, label] of amounts) {
            if (v[key] > 0) chips.push(`${label} ${Math.round(v[key] * 100)}%`);
        }
        if (v.high_shelf_db < 0) chips.push(`air cut ${v.high_shelf_db} dB`);
        if (v.iterations > 1) chips.push(`${v.iterations} passes`);
        if (v.mix != null && v.mix < 1) chips.push(`mix ${Math.round(v.mix * 100)}%`);
        effectEl.innerHTML = `<div class="pb-effect-label">Active preset sets</div>` +
            chips.slice(0, 8).map((c) => `<span class="chip mono">${c}</span>`).join('') +
            `<div class="pb-effect-note">Selecting applies it instantly — the preview loop plays it live, and Clean &amp; Master bakes it into the file.</div>`;
    }

    function paint(query = '') {
        const q = query.trim().toLowerCase();
        listEl.innerHTML = grouped.map(g => {
            const items = g.items.filter(p =>
                !q ||
                (p.label || p.name).toLowerCase().includes(q) ||
                (p.description || '').toLowerCase().includes(q));
            if (!items.length) return '';
            return `<div class="pb-group"><div class="g-label">${g.label}</div>${items.map(p => `
                <button type="button"
                        class="preset-item ${selectEl.value === p.name ? 'selected' : ''}"
                        data-key="${p.name}" title="${(p.description || '').replace(/"/g, '&quot;')}">
                    ${p.label || p.name}
                </button>`).join('')}</div>`;
        }).join('') || '<div class="pb-empty">No presets match.</div>';
    }

    listEl.addEventListener('click', (e) => {
        const btn = e.target.closest('.preset-item');
        if (!btn) return;
        selectEl.value = btn.dataset.key;
        selectEl.dispatchEvent(new Event('change'));
    });

    searchInput.addEventListener('input', () => paint(searchInput.value));

    // Stay in sync with every programmatic change (settings restore,
    // auto-detect Apply, command palette) — they all dispatch `change`.
    selectEl.addEventListener('change', () => {
        listEl.querySelectorAll('.preset-item').forEach(b =>
            b.classList.toggle('selected', b.dataset.key === selectEl.value));
        paintEffect();
    });

    paint();
    paintEffect();
}
