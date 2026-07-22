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
        why: 'Fixes two problems in one pass: the glassy sheen baked into ' +
             'the vocal (2-8 kHz), plus the fizzy sizzle above it ' +
             '(4.5-12 kHz). These are the two most common complaints about ' +
             'Suno tracks, and most modern generations have both. Start ' +
             'here if you are not sure.',
    },
    suno_hash: {
        key: 'suno_hash', label: 'Suno Hash',
        why: 'The classic Suno sizzle — a flickering hiss between 5 and ' +
             '12 kHz that sounds like cymbals that never quite stop ' +
             'ringing. This preset uses the one tool that can tell that ' +
             'flicker apart from real cymbals and vocal air, so your highs ' +
             'stay intact. Use it when the vocals sound fine but the top ' +
             'end sizzles.',
    },
    vocal_glaze: {
        key: 'vocal_glaze', label: 'Vocal Glaze',
        why: 'The shimmer is ON the vocal, not around it — the voice ' +
             'itself sounds glassy and plastic. That happens when the ' +
             'model renders the vocal\'s overtones too bright, so regular ' +
             'noise removal cannot separate the two. This preset uses the ' +
             'clean, low part of the voice (300-1500 Hz) as a reference for ' +
             'what should stay.',
    },
    echo_sheen: {
        key: 'echo_sheen', label: 'Echo Sheen',
        why: 'Shimmer that shadows the music — it swells with every note ' +
             'and disappears the moment the music stops. It is not ' +
             'constant, so noise removal misses it. This is the only ' +
             'preset that reaches into the space right after each note to ' +
             'catch the lingering tail.',
    },
    presence_haze: {
        key: 'presence_haze', label: 'Presence Haze',
        why: 'A smooth, airy wash sitting in the 3-8 kHz presence range — ' +
             'the band where vocals and guitars cut through. It shows up ' +
             'with the music and vanishes in the gaps. This preset tracks ' +
             'the noise floor fast enough to catch a wash that only exists ' +
             'while the music is playing.',
    },
    phantom_cymbal: {
        key: 'phantom_cymbal', label: 'Phantom Cymbal',
        why: 'A washy, metallic "shhhh" between 4 and 10 kHz that sounds ' +
             'like a cymbal layer nobody played sitting behind the mix. ' +
             'Two tools work together here, both set to keep working even ' +
             'during busy, dense parts of the song.',
    },
    harsh_veil: {
        key: 'harsh_veil', label: 'Harsh Veil',
        why: 'A gritty, harsh texture across the upper mids (4-12 kHz) ' +
             'that makes the track tiring to listen to. This is the ' +
             'aggressive option: heavy harshness control plus fast noise ' +
             'removal.',
    },
    deep_scrub: {
        key: 'deep_scrub', label: 'Deep Scrub',
        why: 'Everything on, full strength, across 3-18 kHz, run twice. ' +
             'Use this when nothing else worked. Fair warning: you will ' +
             'lose some top-end air. It is a trade.',
    },

    // ── Tonal / narrow / shape-specific ───────────────────────────────
    cymbal_sheen: {
        key: 'cymbal_sheen', label: 'Cymbal Sheen',
        why: 'A steady high tone that never fades — a hi-hat or ride that ' +
             'rings forever, or a narrow sheen around 8-12 kHz. This ' +
             'preset hunts steady tones and ringing, and leaves the rest ' +
             'of your mix alone.',
    },
    laser_whistle: {
        key: 'laser_whistle', label: 'Laser Whistle',
        why: 'A thin digital whistle up in the 9-15 kHz range that comes ' +
             'and goes. It sounds almost like a laser or a mosquito. This ' +
             'preset notches out steady tones surgically, without touching ' +
             'the music around them.',
    },
    air_brittle: {
        key: 'air_brittle', label: 'Brittle Air',
        why: 'The very top of your track (above 12 kHz) sounds glassy and ' +
             'brittle, but your mids are clean. This one works only above ' +
             '12 kHz, so nothing below the air band is affected.',
    },
    sibilance_rattle: {
        key: 'sibilance_rattle', label: 'Sibilance Rattle',
        why: 'Harsh "sss" and "tss" bursts on vocals in the 6-10 kHz ' +
             'range that rattle apart from the word itself. It is classic ' +
             'sibilance, but the AI version — rougher and more electronic.',
    },
    cymbal_chatter: {
        key: 'cymbal_chatter', label: 'Cymbal Chatter',
        why: 'A repeating "ta-ta-ta" rattle on hi-hats or percussion. It ' +
             'is the model\'s internal timing grid leaking into your ' +
             'audio as a rhythm you never played.',
    },
    broadband_fizz: {
        key: 'broadband_fizz', label: 'Broadband Fizz',
        why: 'A constant fuzzy haze across the whole top end (8-18 kHz). ' +
             'Not a tone, not a rhythm — just fuzz everywhere, all the ' +
             'time. Strong shimmer removal plus noise removal across the ' +
             'entire top.',
    },
    checkerboard_grid: {
        key: 'checkerboard_grid', label: 'Checkerboard Grid',
        why: 'Faint, evenly spaced ringing across the frequency range. ' +
             'Most people cannot name this one until it is gone — then the ' +
             'difference is obvious. It comes from the way the model ' +
             'builds audio, and it leaves a comb-like pattern behind.',
    },
    reverb_flutter: {
        key: 'reverb_flutter', label: 'Reverb Flutter',
        why: 'Reverb tails that turn grainy instead of fading smoothly. ' +
             'When the drums or vocals stop, the tail wobbles and stutters ' +
             'instead of dying cleanly.',
    },
    generic: {
        key: 'generic', label: 'Generic',
        why: 'Safe, balanced settings. A good starting point when you ' +
             'cannot identify the artifact yet — listen to the Removed ' +
             'track and adjust from there.',
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
                <div class="quiz-prompt">No problem — let Shimmer decide.</div>
                <p class="quiz-body">
                    Drop your track on the <b>Master</b> screen and click
                    <b>Analyze</b>. Shimmer listens to your song, checks it
                    against all 19 presets, and picks the best match. It also
                    tells you why it chose that one.
                    If you have not loaded a track yet, start with
                    <b>Generic</b> &mdash; it is a safe default that works on
                    most material.
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
