// main.js — Entry point.  Wires tabs and boots the two panels.

import { initSingleTab } from './single.js';
import { initBatchTab }  from './batch.js';
import { initRemixTab } from './remix.js';
import { initHelp, openHelp } from './help.js';
import { initChainTab } from './chain.js';
import { initPalette } from './palette.js';
import { initPresetBrowser } from './preset-browser.js';
import { initMasterView } from './master-view.js';
import { initRecents } from './recents.js';

const VIEW_TITLES = {
    single: ['Master', 'clean AI artifacts · master for release'],
    remix:  ['Remix', 'stems · per-part effects · rebuild the mix'],
    batch:  ['Batch', 'whole folders, one pass'],
    chain:  ['Signal Chain', 'what actually happens to your audio'],
};

function wireTabs() {
    const tabs = document.querySelectorAll('.tab');
    const panels = document.querySelectorAll('.tab-panel');
    const titleEl = document.getElementById('view-title');
    const subEl = document.getElementById('view-sub');

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
            const [title, sub] = VIEW_TITLES[name] || [name, ''];
            if (titleEl) titleEl.textContent = title;
            if (subEl) subEl.textContent = sub;
        });
    });
}

async function boot() {
    wireTabs();
    // Wordmark = home: back to the Master view.
    document.getElementById('wordmark-home')?.addEventListener('click', () =>
        document.querySelector('.tab[data-tab="single"]')?.click());
    try {
        await initSingleTab();
        await initBatchTab();
        await initRemixTab();
        initChainTab();
        initHelp({ presetSelect: document.getElementById('preset-select') });
        initPalette();
        await initPresetBrowser({
            selectEl: document.getElementById('preset-select'),
            hostEl: document.getElementById('preset-browser'),
        });
        initMasterView();
        initRecents();

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
