// main.js — Entry point.  Wires tabs and boots the two panels.

import { initSingleTab } from './single.js';
import { initBatchTab }  from './batch.js';
import { initHelp }      from './help.js';

function wireTabs() {
    const tabs = document.querySelectorAll('.tab');
    const panels = document.querySelectorAll('.tab-panel');
    const processBar = document.getElementById('process-bar');

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
            // Process bar is only useful on the Single tab.
            processBar.hidden = (name !== 'single');
        });
    });
}

async function boot() {
    wireTabs();
    try {
        await initSingleTab();
        await initBatchTab();
        initHelp({ presetSelect: document.getElementById('preset-select') });
    } catch (e) {
        console.error('Boot failed:', e);
        const box = document.getElementById('metrics-box');
        if (box) box.textContent = `UI failed to load: ${e.message}`;
    }
}

document.addEventListener('DOMContentLoaded', boot);
