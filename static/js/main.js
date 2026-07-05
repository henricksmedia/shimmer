// main.js — Entry point.  Wires tabs and boots the two panels.

import { initSingleTab } from './single.js';
import { initBatchTab }  from './batch.js';
import { initHelp, openHelp } from './help.js';

function wireTabs() {
    const tabs = document.querySelectorAll('.tab');
    const panels = document.querySelectorAll('.tab-panel');

    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            const name = tab.dataset.tab;
            tabs.forEach(t => {
                const active = t === tab;
                t.classList.toggle('active', active);
                t.setAttribute('aria-selected', active ? 'true' : 'false');
            });
            panels.forEach(p => p.classList.toggle(
                'active', p.id === `tab-${name}`));
        });
    });
}

async function boot() {
    wireTabs();
    try {
        await initSingleTab();
        await initBatchTab();
        initHelp({ presetSelect: document.getElementById('preset-select') });

        // First visit: open the quick-start guide once.
        try {
            if (!localStorage.getItem('shimmer.quickstart-seen')) {
                localStorage.setItem('shimmer.quickstart-seen', '1');
                openHelp('quickstart');
            }
        } catch (_) { /* storage unavailable — skip */ }
    } catch (e) {
        console.error('Boot failed:', e);
        const box = document.getElementById('metrics-box');
        if (box) {
            box.textContent = `UI failed to load: ${e.message}`;
            box.hidden = false;
        }
    }
}

document.addEventListener('DOMContentLoaded', boot);
