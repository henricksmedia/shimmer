// help.js — Help modal: tabs, preset decision tree, and controls reference.
// Public API:
//   initHelp({ presetSelect })          — wire the modal to the page
//   openHelp(tabId, anchorId?)          — open modal on a tab, optionally
//                                          scroll to a control's help card

import { CONTROL_SPEC } from './controls.js';

let _modal, _tabs, _panels, _lastFocus;
let _presetSelectEl = null;

// ──────────────────────────────────────────────────────────────────────
// Preset decision tree
// ──────────────────────────────────────────────────────────────────────

const PRESET_RESULTS = {
    suno_v3: {
        name: 'suno_v3',
        why: 'Best for a static, narrow high whistle (5 - 7 kHz).',
    },
    'suno_v3.5': {
        name: 'suno_v3.5',
        why: 'Like v3 but a little broader and noisier.',
    },
    suno_v4: {
        name: 'suno_v4',
        why: 'Built for noisy, shifting top-end shimmer.',
    },
    'suno_v4.5': {
        name: 'suno_v4.5',
        why: 'Targets harsh upper-mid bite around 3.5 - 4.5 kHz.',
    },
    suno_v5: {
        name: 'suno_v5',
        why: 'Cleans the metallic, tinny sound across the whole top end.',
    },
    suno_v5_pro: {
        name: 'suno_v5_pro',
        why: 'Surgical cleanup above 6 kHz, leaves the mids alone.',
    },
    'suno_v5.5': {
        name: 'suno_v5.5',
        why: 'Tames rattle in cymbals, risers, and reverb tails.',
    },
    suno_cymbal: {
        name: 'suno_cymbal',
        why: 'Locks onto a constant cymbal-like tone that never fades.',
    },
    generic: {
        name: 'generic',
        why: 'Safe defaults. A good starting point when unsure.',
    },
};

// Each step is either:
//   { type: 'question', prompt, options: [{label, next}] }
// Or a string key into PRESET_RESULTS for a leaf result.
const QUIZ = {
    start: {
        type: 'question',
        prompt: 'Which one best describes the noise you hear?',
        options: [
            { label: 'A constant high whistle or hiss',                 next: 'whistle' },
            { label: 'Tinny or metallic across the music',              next: 'metallic' },
            { label: 'Harsh or piercing vocals / upper mids',           next: 'suno_v4.5' },
            { label: 'Top end is noisy and keeps changing',             next: 'suno_v4' },
            { label: 'Cymbals, risers, or reverb tails sound rattly',   next: 'suno_v5.5' },
            { label: 'A cymbal tone that rings forever and never fades', next: 'suno_cymbal' },
            { label: 'I\'m not sure',                                    next: 'unsure' },
        ],
    },
    whistle: {
        type: 'question',
        prompt: 'Is the whistle thin and steady, or a bit broader?',
        options: [
            { label: 'Thin and steady',          next: 'suno_v3' },
            { label: 'Broader, a little noisier', next: 'suno_v3.5' },
        ],
    },
    metallic: {
        type: 'question',
        prompt: 'Where do you hear the metallic sound most?',
        options: [
            { label: 'Across most of the track',           next: 'suno_v5' },
            { label: 'Mostly the very top end (above 6 kHz)', next: 'suno_v5_pro' },
        ],
    },
    unsure: {
        type: 'unsure',
    },
};

// ──────────────────────────────────────────────────────────────────────
// Quiz renderer
// ──────────────────────────────────────────────────────────────────────

function renderQuiz(host) {
    host.innerHTML = '';
    const state = { stepId: 'start' };

    const renderStep = () => {
        host.innerHTML = '';
        const step = QUIZ[state.stepId];

        if (typeof step === 'undefined') return;

        if (step.type === 'question') {
            const card = document.createElement('div');
            card.className = 'quiz-card';

            const q = document.createElement('div');
            q.className = 'quiz-prompt';
            q.textContent = step.prompt;
            card.appendChild(q);

            const opts = document.createElement('div');
            opts.className = 'quiz-options';
            for (const opt of step.options) {
                const b = document.createElement('button');
                b.type = 'button';
                b.className = 'quiz-option';
                b.textContent = opt.label;
                b.addEventListener('click', () => {
                    if (PRESET_RESULTS[opt.next]) {
                        renderResult(opt.next);
                    } else {
                        state.stepId = opt.next;
                        renderStep();
                    }
                });
                opts.appendChild(b);
            }
            card.appendChild(opts);
            host.appendChild(card);
            return;
        }

        if (step.type === 'unsure') {
            const card = document.createElement('div');
            card.className = 'quiz-card';
            card.innerHTML = `
                <div class="quiz-prompt">No worries.</div>
                <p class="quiz-body">
                    Click <b>Auto Detect</b> on the main panel and Shimmer
                    will listen to the file and pick a preset for you.
                    If you have not loaded a file yet, start with
                    <b>generic</b> &mdash; it is a safe default.
                </p>
            `;

            const row = document.createElement('div');
            row.className = 'quiz-actions';

            const useGeneric = document.createElement('button');
            useGeneric.type = 'button';
            useGeneric.className = 'btn btn-primary';
            useGeneric.textContent = 'Use generic preset';
            useGeneric.addEventListener('click', () => applyPreset('generic'));
            row.appendChild(useGeneric);

            const restart = document.createElement('button');
            restart.type = 'button';
            restart.className = 'btn btn-ghost';
            restart.textContent = 'Start over';
            restart.addEventListener('click', () => {
                state.stepId = 'start';
                renderStep();
            });
            row.appendChild(restart);

            card.appendChild(row);
            host.appendChild(card);
            return;
        }
    };

    const renderResult = (presetKey) => {
        host.innerHTML = '';
        const r = PRESET_RESULTS[presetKey];

        const card = document.createElement('div');
        card.className = 'quiz-card quiz-result';

        const head = document.createElement('div');
        head.className = 'quiz-result-head';
        head.innerHTML = `<span class="quiz-result-label">We suggest</span> <b class="quiz-result-name">${r.name}</b>`;
        card.appendChild(head);

        const why = document.createElement('p');
        why.className = 'quiz-body';
        why.textContent = r.why;
        card.appendChild(why);

        const row = document.createElement('div');
        row.className = 'quiz-actions';

        const use = document.createElement('button');
        use.type = 'button';
        use.className = 'btn btn-primary';
        use.textContent = `Use ${r.name}`;
        use.addEventListener('click', () => applyPreset(r.name));
        row.appendChild(use);

        const restart = document.createElement('button');
        restart.type = 'button';
        restart.className = 'btn btn-ghost';
        restart.textContent = 'Start over';
        restart.addEventListener('click', () => {
            state.stepId = 'start';
            renderStep();
        });
        row.appendChild(restart);

        card.appendChild(row);
        host.appendChild(card);
    };

    renderStep();
}

function applyPreset(name) {
    if (!_presetSelectEl) return;
    if (![...(_presetSelectEl.options || [])].some(o => o.value === name)) {
        return;
    }
    _presetSelectEl.value = name;
    _presetSelectEl.dispatchEvent(new Event('change'));
    closeHelp();
}

// ──────────────────────────────────────────────────────────────────────
// Controls reference renderer
// ──────────────────────────────────────────────────────────────────────

function renderControlsHelp(host) {
    host.innerHTML = '';

    const byGroup = new Map();
    for (const spec of CONTROL_SPEC) {
        if (!spec.help) continue;
        if (!byGroup.has(spec.group)) byGroup.set(spec.group, []);
        byGroup.get(spec.group).push(spec);
    }

    for (const [group, specs] of byGroup) {
        const groupEl = document.createElement('div');
        groupEl.className = 'help-group';
        const title = document.createElement('div');
        title.className = 'help-group-title';
        title.textContent = group;
        groupEl.appendChild(title);

        for (const spec of specs) {
            const card = document.createElement('div');
            card.className = 'help-card';
            card.id = `help-control-${spec.key}`;

            const h = document.createElement('h4');
            h.textContent = spec.label;
            card.appendChild(h);

            const p = document.createElement('p');
            p.className = 'help-card-short';
            p.textContent = spec.help.short;
            card.appendChild(p);

            const list = document.createElement('ul');
            list.className = 'help-card-list';

            const up = document.createElement('li');
            up.innerHTML = `<b>Turn it up when:</b> ${spec.help.when_up}`;
            list.appendChild(up);

            const dn = document.createElement('li');
            dn.innerHTML = `<b>Turn it down when:</b> ${spec.help.when_down}`;
            list.appendChild(dn);

            card.appendChild(list);

            if (spec.help.typical) {
                const t = document.createElement('div');
                t.className = 'help-card-typical';
                t.innerHTML = `Typical: <span>${spec.help.typical}</span>`;
                card.appendChild(t);
            }

            groupEl.appendChild(card);
        }

        host.appendChild(groupEl);
    }
}

// ──────────────────────────────────────────────────────────────────────
// Modal mechanics
// ──────────────────────────────────────────────────────────────────────

function setActiveTab(tabId) {
    _tabs.forEach(t => {
        const active = t.dataset.tab === tabId;
        t.classList.toggle('active', active);
        t.setAttribute('aria-selected', active ? 'true' : 'false');
    });
    _panels.forEach(p => {
        p.classList.toggle('active', p.dataset.panel === tabId);
    });
}

export function openHelp(tabId = 'presets', anchorId = null) {
    if (!_modal) return;
    _lastFocus = document.activeElement;
    _modal.hidden = false;
    document.body.classList.add('help-open');
    setActiveTab(tabId);

    // Focus the close button for accessibility.
    requestAnimationFrame(() => {
        const closeBtn = _modal.querySelector('#help-close');
        if (closeBtn) closeBtn.focus();

        if (anchorId) {
            const el = _modal.querySelector(`#help-control-${anchorId}`);
            if (el) {
                el.scrollIntoView({ block: 'start', behavior: 'instant' in window ? 'instant' : 'auto' });
                el.classList.add('help-card-flash');
                setTimeout(() => el.classList.remove('help-card-flash'), 1400);
            }
        }
    });
}

export function closeHelp() {
    if (!_modal || _modal.hidden) return;
    _modal.hidden = true;
    document.body.classList.remove('help-open');
    if (_lastFocus && typeof _lastFocus.focus === 'function') {
        _lastFocus.focus();
    }
}

function onKeyDown(e) {
    if (e.key === 'Escape' && !_modal.hidden) {
        e.preventDefault();
        closeHelp();
    }
}

// ──────────────────────────────────────────────────────────────────────
// Init
// ──────────────────────────────────────────────────────────────────────

export function initHelp({ presetSelect } = {}) {
    _modal = document.getElementById('help-modal');
    if (!_modal) return;
    _presetSelectEl = presetSelect || document.getElementById('preset-select');

    _tabs = Array.from(_modal.querySelectorAll('.help-tab'));
    _panels = Array.from(_modal.querySelectorAll('.help-panel'));

    // Tab switching.
    _tabs.forEach(t => {
        t.addEventListener('click', () => setActiveTab(t.dataset.tab));
    });

    // Close on backdrop click + close button.
    _modal.addEventListener('click', (e) => {
        if (e.target === _modal) closeHelp();
    });
    const closeBtn = _modal.querySelector('#help-close');
    if (closeBtn) closeBtn.addEventListener('click', closeHelp);

    // Esc closes.
    document.addEventListener('keydown', onKeyDown);

    // Build content.
    renderQuiz(document.getElementById('preset-quiz'));
    renderControlsHelp(document.getElementById('controls-help-list'));

    // Wire any element on the page that asks for help via `data-help-tab`.
    document.querySelectorAll('[data-help-tab]').forEach(el => {
        el.addEventListener('click', () => {
            openHelp(el.dataset.helpTab, el.dataset.helpAnchor || null);
        });
    });
}
