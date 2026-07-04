// help.js — Help modal: tabs, preset decision tree, and controls reference.
// Public API:
//   initHelp({ presetSelect })          — wire the modal to the page
//   openHelp(tabId, anchorId?)          — open modal on a tab, optionally
//                                          scroll to a control's help card

import { CONTROL_SPEC, GROUP_INTROS } from './controls.js';

let _modal, _tabs, _panels, _lastFocus;
let _presetSelectEl = null;

// ──────────────────────────────────────────────────────────────────────
// Preset decision tree
// ──────────────────────────────────────────────────────────────────────

// Each entry: `key` is the preset id sent to the server; `label` is what we
// show the user in the UI; `why` is shown after the quiz picks this preset
// and should tell the user the ROOT CAUSE the preset targets so they
// understand whether the recommendation matches what they hear.
// Keys map 1:1 to the visible PRESETS dict in presets.py.
const PRESET_RESULTS = {
    // ── Suno-specific (most common modern cases) ──────────────────────
    vocal_glaze_plus: {
        key: 'vocal_glaze_plus', label: 'Vocal Glaze + Top End',
        why: 'Combines Vocal Glaze (vocal-anchored DeHarsh, 2-8 kHz) with ' +
             'Suno Hash (FlickerTamer-led, 4.5-12 kHz). Targets the two ' +
             'most-complained-about Suno artifacts in a single pass: ' +
             'shimmer baked into vocal harmonics PLUS the AM-modulated ' +
             'hiss in the brilliance band. Start here for most modern ' +
             'Suno tracks.',
    },
    suno_hash: {
        key: 'suno_hash', label: 'Suno Hash',
        why: 'Suno\'s diffusion-model residual: narrowband AM-modulated ' +
             'hiss in 5-12 kHz that sounds like cymbal sizzle which never ' +
             'fully decays. Uses FlickerTamer (the only stage that can ' +
             'tell Suno hash apart from real cymbals and vocal air). Use ' +
             'when vocals sound natural but the brilliance band sizzles.',
    },
    vocal_glaze: {
        key: 'vocal_glaze', label: 'Vocal Glaze',
        why: 'Shimmer that sits ON TOP of the vocal itself (2-8 kHz), ' +
             'not after it and not in the gaps. The shimmer IS the vocal ' +
             'overtones rendered too brightly, so normal denoise/shimmer ' +
             'tools cannot separate it. Uses DeHarsh anchored to the ' +
             'clean vocal fundamental (300-1500 Hz) as a vocal-aware ' +
             'shimmer compressor.',
    },
    echo_sheen: {
        key: 'echo_sheen', label: 'Echo Sheen',
        why: 'Shimmer that shadows the music: rises with every note and ' +
             'vanishes the instant the music drops. Not constant (so ' +
             'denoise misses it), not periodic (so flicker tools miss ' +
             'it). The only preset that engages the downward expander to ' +
             'catch the lingering tail at the edges of musical events.',
    },
    presence_haze: {
        key: 'presence_haze', label: 'Presence Haze',
        why: 'Smooth, airy, noise-like wash in the 3-8 kHz presence ' +
             'band. Appears with the music, vanishes in silence. Denoise ' +
             'with a short minimum-statistics window so the noise floor ' +
             'estimate tracks the content-gated wash instead of waiting ' +
             'for quiet frames.',
    },
    phantom_cymbal: {
        key: 'phantom_cymbal', label: 'Phantom Cymbal',
        why: 'Washy, metallic, ringy "shhhhh" in 4-10 kHz that sounds ' +
             'like a phantom cymbal layer behind the music. Combines ' +
             'DeResonator and DeHarsh with lowered thresholds and a high ' +
             'density floor so they fire on dense brilliance frames.',
    },
    harsh_veil: {
        key: 'harsh_veil', label: 'Harsh Veil',
        why: 'Harsh, gritty texture across the upper-mids (4-12 kHz). ' +
             'Aggressive DeHarsh with a very low threshold plus ' +
             'responsive denoise to scrub the gritty layer.',
    },
    deep_scrub: {
        key: 'deep_scrub', label: 'Deep Scrub',
        why: 'Maximum-strength wide-band cleanup (3-18 kHz) with all ' +
             'stages active and 2 iterations. Use when nothing else has ' +
             'worked and you accept a tradeoff in top-end air for the ' +
             'sake of removing the artifact.',
    },

    // ── Tonal / narrow / shape-specific ───────────────────────────────
    cymbal_sheen: {
        key: 'cymbal_sheen', label: 'Cymbal Sheen',
        why: 'A SUSTAINED tonal high-frequency tone that never fades — ' +
             'a hi-hat or ride that won\'t decay, or a narrow sheen at ' +
             '8-12 kHz. Narrow-tone killer + DeResonator do the work.',
    },
    laser_whistle: {
        key: 'laser_whistle', label: 'Laser Whistle',
        why: 'Thin, intermittent narrow-band tonal chirp in 9-15 kHz. ' +
             'A chirpy digital whistle that comes and goes. Narrow-tone ' +
             'killer is the primary surgical tool.',
    },
    air_brittle: {
        key: 'air_brittle', label: 'Brittle Air',
        why: 'Glassy / brittle texture above 12 kHz while the mids stay ' +
             'clean. Surgical: shimmer suppression in 12-18 kHz only, ' +
             'leaves everything below alone.',
    },
    sibilance_rattle: {
        key: 'sibilance_rattle', label: 'Sibilance Rattle',
        why: 'Harsh "sss" / "tss" / "ts" bursts on vocals in 6-10 kHz ' +
             'that rattle separately from the consonants themselves.',
    },
    cymbal_chatter: {
        key: 'cymbal_chatter', label: 'Cymbal Chatter',
        why: 'A repetitive "ta-ta-ta" rattle on hi-hats or percussion ' +
             '— periodic high-band chatter caused by the model\'s frame ' +
             'grid leaking through.',
    },
    broadband_fizz: {
        key: 'broadband_fizz', label: 'Broadband Fizz',
        why: 'A constant fuzzy haze across the entire brilliance band ' +
             '(8-18 kHz). Noise-like and persistent, not periodic and ' +
             'not tonal. Strong shimmer + denoise across the whole top.',
    },
    checkerboard_grid: {
        key: 'checkerboard_grid', label: 'Checkerboard Grid',
        why: 'Faint comb / regularly-spaced ringing in the spectrum ' +
             '(deconv-grid signature). Hard to identify until removed, ' +
             'then obvious. De-checkerboard is the primary stage.',
    },
    reverb_flutter: {
        key: 'reverb_flutter', label: 'Reverb Flutter',
        why: 'Reverb tails grain instead of smoothing — when drums or ' +
             'vocals stop, the tail flutters with a granular wobble ' +
             'instead of dying cleanly. Maximum random-phase resynth.',
    },
    generic: {
        key: 'generic', label: 'Generic',
        why: 'Safe defaults. A good starting point when you cannot ' +
             'identify the artifact yet — listen to the Removed track ' +
             'and refine from there.',
    },
};

// Quiz tree: nested questions narrow the user from "where do you hear it?"
// down to a specific preset, so all 16 visible presets are reachable
// without a 16-option flat list. Each step is either:
//   { type: 'question', prompt, options: [{label, next}] }
// Or `next` may point at a PRESET_RESULTS key (leaf) or another QUIZ key.
const QUIZ = {
    start: {
        type: 'question',
        prompt: 'Where do you hear the artifact most?',
        options: [
            { label: 'On vocals (most common with Suno)',          next: 'vocals' },
            { label: 'On cymbals, hi-hats, or percussion',         next: 'percussion' },
            { label: 'In the very top end (above ~10 kHz)',        next: 'top' },
            { label: 'A wash across the upper-mids (4-10 kHz)',    next: 'wash' },
            { label: 'Reverb tails sound grainy instead of smooth', next: 'reverb_flutter' },
            { label: 'I tried specific presets and nothing worked', next: 'deep_scrub' },
            { label: 'I\'m not sure',                              next: 'unsure' },
        ],
    },

    vocals: {
        type: 'question',
        prompt: 'What does the artifact sound like ON the vocals?',
        options: [
            { label: 'Shimmer sits ON TOP of the vocal itself (vocal IS the shimmer)', next: 'vocal_glaze' },
            { label: 'Vocal shimmer PLUS top-end sizzle (most modern Suno tracks)',    next: 'vocal_glaze_plus' },
            { label: 'A flickering metallic hiss that rides with the voice',           next: 'suno_hash' },
            { label: 'Harsh "sss" / "tss" bursts',                                     next: 'sibilance_rattle' },
            { label: 'A halo of shimmer that follows every note and dies in silence',  next: 'echo_sheen' },
        ],
    },

    percussion: {
        type: 'question',
        prompt: 'What kind of cymbal / percussion artifact?',
        options: [
            { label: 'A constant high tone that rings forever',          next: 'cymbal_sheen' },
            { label: 'Repetitive ta-ta-ta rattle',                       next: 'cymbal_chatter' },
            { label: 'A thin digital whistle that comes and goes',       next: 'laser_whistle' },
            { label: 'A washy metallic ring behind the cymbals',         next: 'phantom_cymbal' },
            { label: 'Flickering hiss on top of cymbals (Suno)',         next: 'suno_hash' },
        ],
    },

    top: {
        type: 'question',
        prompt: 'What does the very top end sound like?',
        options: [
            { label: 'Glassy / brittle, but the mids sound fine',        next: 'air_brittle' },
            { label: 'A constant fuzzy haze across the whole top',       next: 'broadband_fizz' },
            { label: 'Faint comb or grid texture, hard to place',        next: 'checkerboard_grid' },
            { label: 'A thin chirp or whistle',                          next: 'laser_whistle' },
        ],
    },

    wash: {
        type: 'question',
        prompt: 'What does the wash sound like in the upper-mids?',
        options: [
            { label: 'Smooth airy wash, vanishes in silence',            next: 'presence_haze' },
            { label: 'Shimmer that shadows the music and dies in gaps',  next: 'echo_sheen' },
            { label: 'Washy, metallic, cymbal-like ring',                next: 'phantom_cymbal' },
            { label: 'Harsh, gritty texture',                            next: 'harsh_veil' },
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
        head.innerHTML = `<span class="quiz-result-label">We suggest</span> <b class="quiz-result-name">${r.label}</b>`;
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
        use.textContent = `Use ${r.label}`;
        use.addEventListener('click', () => applyPreset(r.key));
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

        const intro = GROUP_INTROS[group];
        if (intro) {
            const introWrap = document.createElement('div');
            introWrap.className = 'help-group-intro';
            if (intro.lead) {
                const lead = document.createElement('p');
                lead.className = 'help-group-intro-lead';
                lead.textContent = intro.lead;
                introWrap.appendChild(lead);
            }
            if (intro.bullets && intro.bullets.length) {
                const ul = document.createElement('ul');
                ul.className = 'help-group-intro-list';
                for (const b of intro.bullets) {
                    const li = document.createElement('li');
                    li.textContent = b;
                    ul.appendChild(li);
                }
                introWrap.appendChild(ul);
            }
            groupEl.appendChild(introWrap);
        }

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
