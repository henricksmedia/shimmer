// preset.js — Preset dropdown + Auto-detect.

import { fetchPresets, suggestPreset } from './api.js';
import { CONTROL_SPEC } from './controls.js';

/**
 * Populate a <select> from the server's preset list.  Returns the loaded
 * preset metadata so other modules can read defaults.
 */
export async function initPresetSelect(selectEl, {onChange, descEl} = {}) {
    const {presets, default: defaultName} = await fetchPresets();
    selectEl.innerHTML = '';
    // Only artifact-shape presets appear in the dropdown. Legacy
    // version-named keys still arrive in `presets` (visible: false) so
    // saved-settings / auto-detect lookups can resolve their labels.
    const visiblePresets = presets.filter(p => p.visible !== false);
    for (const p of visiblePresets) {
        const opt = document.createElement('option');
        opt.value = p.name;
        opt.textContent = p.label || p.name;
        selectEl.appendChild(opt);
    }
    selectEl.value = defaultName;

    const byName = new Map(presets.map(p => [p.name, p]));

    const applyDescription = () => {
        if (!descEl) return;
        const p = byName.get(selectEl.value);
        descEl.textContent = p ? p.description : '';
    };

    selectEl.addEventListener('change', () => {
        applyDescription();
        if (onChange) onChange(byName.get(selectEl.value));
    });
    applyDescription();

    return {presets, byName, defaultName};
}

// Per-key scaling rule for presetToSliderValues(strength).  Keys not in
// this map are passed through unchanged regardless of strength (band
// edges, detection threshold/slope, mix -- not "amount" knobs).  Each
// entry: {neutral, lo, hi}.  Mirrors the whitelist in
// params.apply_preset_strength on the backend so visible sliders move
// in lockstep with the hidden keys the server scales.
const STRENGTH_SCALE = {
    denoise:        { neutral: 0.0, lo: 0.0, hi: 1.0 },
    deres:          { neutral: 0.0, lo: 0.0, hi: 1.0 },
    deharsh:        { neutral: 0.0, lo: 0.0, hi: 1.0 },
    decheck:        { neutral: 0.0, lo: 0.0, hi: 1.0 },
    high_shelf_db:  { neutral: 0.0, lo: -12.0, hi: 0.0 },
};

function _scaleOne(value, strength, rule) {
    const v = rule.neutral + (value - rule.neutral) * strength;
    if (v < rule.lo) return rule.lo;
    if (v > rule.hi) return rule.hi;
    return v;
}

/**
 * Given a preset's full Params, return only the subset the UI sliders
 * drive (keys listed in CONTROL_SPEC).  When `strength` is provided
 * and != 1.0, amount-style keys (`STRENGTH_SCALE`) are linearly
 * rescaled from the neutral baseline (Params() default = no effect)
 * toward the preset value, then clamped to per-key safety limits.
 *
 * This is the visible-slider mirror of `params.apply_preset_strength`
 * on the backend; the server scales the hidden keys (ceilings, density
 * floors, FlickerTamer depth, iterations, etc.) the same way.
 */
export function presetToSliderValues(preset, strength = 1.0) {
    if (!preset) return {};
    const s = Number.isFinite(strength) ? strength : 1.0;
    const out = {};
    for (const spec of CONTROL_SPEC) {
        if (preset.values && preset.values[spec.key] !== undefined) {
            const v = preset.values[spec.key];
            const rule = STRENGTH_SCALE[spec.key];
            out[spec.key] = (rule && Math.abs(s - 1.0) > 1e-6)
                ? _scaleOne(v, s, rule)
                : v;
        }
    }
    return out;
}

/**
 * Run auto-detect on a file; return the full result dict.
 */
export async function runAutoDetect(file) {
    return suggestPreset(file);
}
