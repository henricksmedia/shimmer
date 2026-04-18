// settings.js — Debounced persistence of UI state.

import { saveSettings as apiSaveSettings, fetchSettings } from './api.js';

/**
 * Create a debounced saver.  Call schedule(payload) to queue a save.
 */
export function makeSettingsSaver(delayMs = 300) {
    let timer = null;
    let pending = null;
    return function schedule(payload) {
        pending = payload;
        clearTimeout(timer);
        timer = setTimeout(() => {
            apiSaveSettings(pending).catch(() => {});
            pending = null;
        }, delayMs);
    };
}

export async function loadSettings() {
    try { return await fetchSettings(); } catch { return {}; }
}
