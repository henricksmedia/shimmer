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
    for (const p of presets) {
        const opt = document.createElement('option');
        opt.value = p.name;
        opt.textContent = p.name;
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

/**
 * Given a preset's full Params, return only the subset the UI sliders
 * drive (keys listed in CONTROL_SPEC).  Silent fields fall back to the
 * preset's own default.
 */
export function presetToSliderValues(preset) {
    if (!preset) return {};
    const out = {};
    for (const spec of CONTROL_SPEC) {
        if (preset.values && preset.values[spec.key] !== undefined) {
            out[spec.key] = preset.values[spec.key];
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
