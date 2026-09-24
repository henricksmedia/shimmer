// help.js — Help modal: tabs, the "What do you hear?" card guide and quiz,
// the Remix / Batch preset table, and the controls reference.
// Public API:
//   initHelp({ presetSelect })          — wire the modal to the page.
//                                          presetSelect is still accepted,
//                                          but the Master tab no longer
//                                          reads the preset menu: the quiz
//                                          points at a card instead.
//   openHelp(tabId, anchorId?)          — open modal on a tab, optionally
//                                          scroll to a help card
//                                          (#help-control-<anchorId>)
//   closeHelp()                         — close it
//
// The cards, the fix each one runs and which fixes are built come from
// GET /api/rules (shimmer/core/catalog.py), so this file keeps no copy of
// them. It keeps only the words that explain each card, and the 1.x
// preset-to-card table (LEGACY_PRESETS in shimmer/core/settings.py).

import { CONTROL_SPEC, GROUP_INTROS } from './controls.js';
import { loadRules } from './rules.js';

let _modal, _tabs, _panels, _lastFocus;

// ──────────────────────────────────────────────────────────────────────
// The 1.x presets, and the card each one turns on
// ──────────────────────────────────────────────────────────────────────

// `key` is the 1.x preset id; `label` is its name in the Remix and Batch
// menus (/api/presets); `card` is the card it turns on in 2.0, from
// LEGACY_PRESETS in shimmer/core/settings.py (null: no card); `why` says
// what the problem sounds like, so the user can check the answer against
// what they hear. Grouped by card, in the order the table shows them.
const PRESET_RESULTS = {
    // ── Shimmer card ──────────────────────────────────────────────────
    suno_hash: {
        key: 'suno_hash', label: 'Suno Hash (5-12 kHz Flicker)', card: 'shimmer',
        why: 'A flickering, fizzy hiss between about 5 and 12 kHz. It ' +
             'sounds like cymbals that never quite stop ringing, and it ' +
             'rides on the vocals too.',
    },
    vocal_glaze_plus: {
        key: 'vocal_glaze_plus', label: 'Vocal Glaze + Top End', card: 'shimmer',
        why: 'Two problems together: the voice sounds glassy, and there is ' +
             'fizzy sizzle up top. The Shimmer card goes after the fizz. If ' +
             'the voice still sounds glassy, try the Sibilance card as well.',
    },
    broadband_fizz: {
        key: 'broadband_fizz', label: 'Broadband Fizz', card: 'shimmer',
        why: 'A steady, fuzzy haze across the whole top end. Not a tone and ' +
             'not a rhythm: just fuzz everywhere, all the time.',
    },
    presence_haze: {
        key: 'presence_haze', label: 'Presence Haze', card: 'shimmer',
        why: 'A smooth, airy wash in the 3-8 kHz range, where vocals and ' +
             'guitars cut through. It comes with the music and goes in the ' +
             'gaps.',
    },
    echo_sheen: {
        key: 'echo_sheen', label: 'Echo Sheen', card: 'shimmer',
        why: 'Fizz that swells with every note and stops the moment the ' +
             'music stops.',
    },
    cymbal_chatter: {
        key: 'cymbal_chatter', label: 'Cymbal Chatter', card: 'shimmer',
        why: 'A repeating "ta-ta-ta" rattle on hi-hats or percussion, like ' +
             'a rhythm nobody played.',
    },
    phantom_cymbal: {
        key: 'phantom_cymbal', label: 'Phantom Cymbal', card: 'shimmer',
        why: 'A washy, metallic "shhh" between about 4 and 10 kHz, like a ' +
             'cymbal layer nobody played behind the mix.',
    },
    deep_scrub: {
        key: 'deep_scrub', label: 'Deep Scrub', card: 'shimmer',
        why: 'In 1.x this ran every tool at full strength, twice. 2.0 has no ' +
             'such option: this preset turns on the Shimmer card only.',
    },

    // ── Fixed tones card ──────────────────────────────────────────────
    cymbal_sheen: {
        key: 'cymbal_sheen', label: 'Cymbal Sheen', card: 'tones',
        why: 'A steady high tone that never fades, like a hi-hat or ride ' +
             'that rings forever.',
    },
    laser_whistle: {
        key: 'laser_whistle', label: 'Laser Whistle', card: 'tones',
        why: 'A thin, high digital whistle, almost like a mosquito.',
    },
    air_brittle: {
        key: 'air_brittle', label: 'Brittle Air', card: 'tones',
        why: 'The very top of the track, above about 12 kHz, sounds glassy ' +
             'and brittle, but the mids are clean.',
    },
    checkerboard_grid: {
        key: 'checkerboard_grid', label: 'Checkerboard Grid', card: 'tones',
        why: 'Faint, evenly spaced ringing that is hard to name until it is ' +
             'gone.',
    },

    // ── Sibilance card ────────────────────────────────────────────────
    sibilance_rattle: {
        key: 'sibilance_rattle', label: 'Sibilance Rattle', card: 'sibilance',
        why: 'Harsh "s" and "t" bursts on the vocals that rattle and hiss.',
    },
    vocal_glaze: {
        key: 'vocal_glaze', label: 'Vocal Glaze', card: 'sibilance',
        why: 'The voice itself sounds glassy or plastic, as if its ' +
             'overtones are too bright.',
    },

    // ── Other cards ───────────────────────────────────────────────────
    harsh_veil: {
        key: 'harsh_veil', label: 'Harsh Veil', card: 'harshness',
        why: 'A gritty, piercing sound in the upper mids that makes the ' +
             'song tiring to hear.',
    },
    muddy_boxy: {
        key: 'muddy_boxy', label: 'Muddy / Boxy (De-Mud)', card: 'mud',
        why: 'Too much energy in the low mids, so the mix sounds thick and ' +
             'boxy and the words are hard to hear.',
    },
    dark_mix_rescue: {
        key: 'dark_mix_rescue', label: 'Dark Mix Rescue (Brighten)', card: 'air',
        why: 'The whole mix sounds dull, like a blanket over the speakers.',
    },
    reverb_flutter: {
        key: 'reverb_flutter', label: 'Reverb Flutter', card: 'phasiness',
        why: 'Reverb tails that turn grainy or watery instead of fading ' +
             'smoothly.',
    },
    generic: {
        key: 'generic', label: 'Generic', card: null,
        why: 'The safe starting point in 1.x. In 2.0 it turns on no card.',
    },
};

// Quiz tree: questions narrow the user from "where do you hear it?" down to
// a preset, and the result names the card that preset turns on. Each step
// is { type: 'question', prompt, options: [{label, next}] }, where `next`
// is a PRESET_RESULTS key (a result) or another QUIZ key.
const QUIZ = {
    start: {
        type: 'question',
        prompt: 'Where do you hear the problem most?',
        options: [
            { label: 'On the vocals',                                   next: 'vocals' },
            { label: 'On cymbals, hi-hats or other percussion',         next: 'percussion' },
            { label: 'In the very top end, above about 10 kHz',         next: 'top' },
            { label: 'In the upper mids, about 2 to 10 kHz',            next: 'wash' },
            { label: 'Reverb tails sound grainy or watery',             next: 'reverb_flutter' },
            { label: 'The whole mix sounds muddy or dull',              next: 'tone' },
            { label: 'I\'m not sure',                                   next: 'unsure' },
        ],
    },

    vocals: {
        type: 'question',
        prompt: 'What does it sound like on the vocals?',
        options: [
            { label: 'The voice itself sounds glassy or plastic',                  next: 'vocal_glaze' },
            { label: 'A glassy voice plus fizzy sizzle up top (common with Suno)', next: 'vocal_glaze_plus' },
            { label: 'A flickering, metallic hiss that follows the voice',         next: 'suno_hash' },
            { label: 'Harsh, spitty "s" and "sh" sounds',                          next: 'sibilance_rattle' },
            { label: 'Fizz that follows every note and stops in silence',          next: 'echo_sheen' },
        ],
    },

    percussion: {
        type: 'question',
        prompt: 'What does it sound like on the percussion?',
        options: [
            { label: 'A steady high tone that rings forever',        next: 'cymbal_sheen' },
            { label: 'A repeating ta-ta-ta rattle',                  next: 'cymbal_chatter' },
            { label: 'A thin, high digital whistle',                 next: 'laser_whistle' },
            { label: 'A washy, metallic ring behind the cymbals',    next: 'phantom_cymbal' },
            { label: 'A flickering hiss on top of the cymbals',      next: 'suno_hash' },
        ],
    },

    top: {
        type: 'question',
        prompt: 'What does the very top end sound like?',
        options: [
            { label: 'Glassy or brittle, but the mids sound fine',   next: 'air_brittle' },
            { label: 'A steady, fuzzy haze across the whole top',    next: 'broadband_fizz' },
            { label: 'A faint comb or grid texture, hard to place',  next: 'checkerboard_grid' },
            { label: 'A thin chirp or whistle',                      next: 'laser_whistle' },
        ],
    },

    wash: {
        type: 'question',
        prompt: 'What does it sound like in the upper mids?',
        options: [
            { label: 'A smooth, airy wash that stops in silence',    next: 'presence_haze' },
            { label: 'Fizz that follows the music and stops in gaps', next: 'echo_sheen' },
            { label: 'A washy, metallic, cymbal-like ring',          next: 'phantom_cymbal' },
            { label: 'A harsh, gritty, piercing sound',              next: 'harsh_veil' },
        ],
    },

    tone: {
        type: 'question',
        prompt: 'How does the whole mix sound?',
        options: [
            { label: 'Muddy or boxy; the words are hard to hear',    next: 'muddy_boxy' },
            { label: 'Dull, with no sparkle',                        next: 'dark_mix_rescue' },
        ],
    },

    unsure: {
        type: 'unsure',
    },
};

// ──────────────────────────────────────────────────────────────────────
// Card help: the words that explain each "What do you hear?" card
// ──────────────────────────────────────────────────────────────────────

// What each fix is, by tool key (catalog.TOOLS). The industry term first,
// then what it does in plain words.
const TOOL_HELP = {
    notch: 'A notch filter cuts a very narrow band at each steady tone, so ' +
           'the music on either side is kept.',
    declick: 'A de-click finds short pops and crackle and fills them in.',
    deesser: 'A de-esser turns down harsh "s", "t" and "ch" sounds only ' +
             'while they stick out.',
    dynamic_eq: 'A dynamic EQ cuts one band only while it rings out above ' +
                'the rest of the mix.',
    voice_denoise: 'Voice de-noise takes out the hiss and grain that ride on ' +
                   'a voice: a steady hiss floor, a hiss that follows the ' +
                   'voice, and sharp little spikes. It works on the centre of ' +
                   'the mix, where the lead vocal sits.',
    spectral_denoise: 'Spectral de-noise turns down fizzy, flickering hiss, ' +
                      'band by band, only where a trained model hears it.',
    tone_target: 'The tone target is part of mastering. Tone match and Tilt ' +
                 'shape the tone of the whole song.',
    loudness_target: 'The loudness target is part of mastering. It sets how ' +
                     'loud the song plays.',
};

// When to move each card's Amount, and anything else worth knowing, by
// card key (catalog.CARDS). `notReady` shows only while the card's fix is
// not built; `noFix` only while the card has no fix at all.
const CARD_HELP = {
    shimmer: {
        up: 'The fizz on cymbals and vocals is still there, and the Removed ' +
            'track holds only hiss.',
        down: 'Cymbals or the air on the vocals sound dull, the top end ' +
              'sounds watery, or you hear music in the Removed track.',
        note: 'The spectral de-noise uses a small trained model that runs on ' +
              'your own computer. The first time this card is on for a song, ' +
              'it reads the whole song once. That takes about 50 seconds for ' +
              'a 3-minute song. The preview status line at the bottom shows ' +
              'how far it has got. After that, the preview is quick.',
    },
    grain: {
        up: 'The voice still sounds grainy or hissy, and the Removed track ' +
            'holds only hiss and grit.',
        down: 'The voice sounds dull or lispy, the hi-hats lose their snap, ' +
              'or you hear words in the Removed track.',
        note: 'The first time this card is on for a song, it reads the whole ' +
              'song once, so it can follow the hiss as it grows. After that, ' +
              'the preview is quick. Works on: Centre of the mix needs nothing ' +
              'extra. Vocal only splits out the vocal first with the Remix ' +
              'splitter, which is more precise when cymbals sit in the centre ' +
              'with the voice. The first split takes a minute or more. If the ' +
              'splitter is not installed, the card uses the centre of the mix ' +
              'and says so.',
    },
    tones: {
        up: 'You can still hear the whistle or whine.',
        down: 'A held note that belongs in the song sounds thin.',
        note: 'Analyze finds steady tones and turns this card on by itself. ' +
              'If you turn it off, it stays off for this song. It only cuts ' +
              'tones that hold one pitch.',
    },
    sibilance: {
        up: '"S", "sh" and "t" still spit or hiss.',
        down: 'The singer starts to lisp, or the hi-hats lose their snap.',
    },
    clicks: {
        up: 'You still hear pops, ticks or crackle.',
        down: 'Consonants or hi-hat ticks sound soft.',
        notReady: 'The de-click stays off in this version, because it does ' +
                  'not yet find pops in busy music well enough.',
    },
    harshness: {
        up: 'Vocals or guitars still sound piercing.',
        down: 'The mix loses its bite, or the vocal sounds pulled back.',
    },
    phasiness: {
        noFix: 'Shimmer has no tested fix for grainy or watery reverb yet.',
    },
    mud: {
        up: 'The mix still sounds thick, and the words are hard to hear.',
        down: 'The mix sounds thin, or the bass and the low voice lose body.',
    },
    air: {
        note: 'This card works in Mastering and has no Amount slider. ' +
              'Turning it on turns mastering on and sets Tilt to Bright. ' +
              'Turning it off sets Tilt back to Neutral.',
    },
    loudness: {
        note: 'Analyze marks this card when the song plays quieter than ' +
              'released music. It works in Mastering and has no Amount ' +
              'slider. Turning it on turns mastering on and sets the ' +
              'Loudness target to Commercial.',
    },
};

const CARD_GROUPS = { artifacts: 'Artifacts', tone_level: 'Tone and level' };
const NOTED = 'You can still pick the card. Shimmer notes your pick on this ' +
              'computer to help test new fixes, but the sound does not change.';

function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
}

// "Dynamic EQ" -> "dynamic EQ", "De-esser" -> "de-esser" (as chain.py).
function lowerFirst(s) {
    return s.length > 1 && s[1] === s[1].toLowerCase()
        ? s[0].toLowerCase() + s.slice(1) : s;
}

function bandText(band) {
    const [lo, hi] = band;
    const f = (hz) => (hz >= 1000 ? `${+(hz / 1000).toFixed(1)} kHz` : `${Math.round(hz)} Hz`);
    return hi == null ? `above ${f(lo)}` : `${f(lo)}–${f(hi)}`.replace(' kHz–', '–');
}

// One card from /api/rules, with its fix's name and whether it is built.
function cardInfo(rules, key) {
    const card = (rules.cards || []).find((c) => c.key === key);
    if (!card) return null;
    const ready = new Set(rules.tools_ready || []);
    return {
        card,
        toolLabel: card.tool ? ((rules.tool_labels || {})[card.tool] || card.tool) : null,
        ready: !!card.tool && ready.has(card.tool),
        master: card.tool === 'tone_target' || card.tool === 'loudness_target',
    };
}

function fixStatus(info) {
    if (!info.card.tool) return 'No fix yet';
    if (!info.ready) return `${info.toolLabel}: Not built yet`;
    return info.toolLabel;
}

function listItem(head, text) {
    const li = el('li');
    li.append(el('b', null, head), ` ${text}`);
    return li;
}

function renderCardsHelp(host, rules) {
    if (!host) return;
    host.innerHTML = '';
    const groups = new Map();
    for (const c of rules.cards || []) {
        if (!groups.has(c.group)) groups.set(c.group, []);
        groups.get(c.group).push(c);
    }
    for (const [group, cards] of groups) {
        const groupEl = el('div', 'help-group');
        groupEl.appendChild(el('div', 'help-group-title', CARD_GROUPS[group] || group));
        for (const c of cards) {
            const info = cardInfo(rules, c.key);
            const words = CARD_HELP[c.key] || {};
            const card = el('div', 'help-card');
            card.id = `help-control-card-${c.key}`;

            const h = el('h4', null, c.label);
            h.appendChild(el('span', 'help-card-gloss', c.descriptor));
            card.appendChild(h);
            card.appendChild(el('p', 'help-card-short', c.tip));

            const facts = el('div', 'help-card-typical');
            facts.append('Fix:', el('span', null, fixStatus(info)));
            if (c.band_hz) facts.append(' Band:', el('span', null, bandText(c.band_hz)));
            card.appendChild(facts);

            const list = el('ul', 'help-card-list');
            if (!c.tool) {
                list.appendChild(listItem('No fix yet:', `${words.noFix || ''} ${NOTED}`.trim()));
            } else if (!info.ready) {
                const why = words.notReady ||
                    `The ${lowerFirst(info.toolLabel)} is not built yet.`;
                list.appendChild(listItem('Not built yet:', `${why} ${NOTED}`));
            } else {
                if (TOOL_HELP[c.tool]) list.appendChild(listItem('What it runs:', TOOL_HELP[c.tool]));
                if (!info.master && words.up) list.appendChild(listItem('Turn the Amount up when:', words.up));
                if (!info.master && words.down) list.appendChild(listItem('Turn the Amount down when:', words.down));
            }
            if (words.note && (info.ready || !c.tool)) list.appendChild(listItem('Good to know:', words.note));
            card.appendChild(list);
            groupEl.appendChild(card);
        }
        host.appendChild(groupEl);
    }
}

// The Remix / Batch preset menus: each preset and the card it turns on.
function renderPresetTable(host, rules) {
    if (!host) return;
    host.innerHTML = '';
    const table = el('table', 'help-table');
    const head = el('thead');
    const hr = el('tr');
    ['Preset', 'Card it turns on', 'Fix'].forEach((t) => hr.appendChild(el('th', null, t)));
    head.appendChild(hr);
    table.appendChild(head);
    const body = el('tbody');
    for (const r of Object.values(PRESET_RESULTS)) {
        const info = r.card ? cardInfo(rules, r.card) : null;
        const tr = el('tr');
        tr.append(el('td', null, r.label),
                  el('td', null, info ? info.card.label : 'None'),
                  el('td', null, info ? fixStatus(info) : 'Fixed tones only, when found'));
        body.appendChild(tr);
    }
    table.appendChild(body);
    host.appendChild(table);
}

// ──────────────────────────────────────────────────────────────────────
// Going to the card on the Master tab
// ──────────────────────────────────────────────────────────────────────

function songLoaded() {
    const work = document.getElementById('master-work');
    return !!work && !work.hidden;
}

function findTile(label) {
    return [...document.querySelectorAll('#hear-card .hear-tile')]
        .find((b) => (b.querySelector('.t')?.textContent || '') === label) || null;
}

// Close Help, show the Master tab and scroll to What do you hear?. With a
// label, turn that card on first (a click, as if the user made it).
function goToCards(turnOnLabel = null) {
    closeHelp();
    document.querySelector('.tab[data-tab="single"]')?.click();
    if (turnOnLabel) {
        const tile = findTile(turnOnLabel);
        if (tile && !tile.classList.contains('on')) tile.click();
    }
    const target = songLoaded() ? document.getElementById('hear-card') : null;
    if (target) target.scrollIntoView({ block: 'start', behavior: 'smooth' });
}

function goButton(info) {
    const b = el('button', 'btn btn-primary');
    b.type = 'button';
    const label = info ? info.card.label : null;
    const tile = label && songLoaded() ? findTile(label) : null;
    const canTurnOn = !!tile && info.ready && !tile.classList.contains('on');
    b.textContent = canTurnOn ? `Turn on ${label}`
        : (songLoaded() ? 'Go to What do you hear?' : 'Go to the Master tab');
    b.addEventListener('click', () => goToCards(canTurnOn ? label : null));
    return b;
}

// ──────────────────────────────────────────────────────────────────────
// Quiz renderer
// ──────────────────────────────────────────────────────────────────────

function renderQuiz(host) {
    if (!host) return;
    host.innerHTML = '';
    const state = { stepId: 'start' };

    const restartButton = () => {
        const restart = el('button', 'btn btn-ghost', 'Start over');
        restart.type = 'button';
        restart.addEventListener('click', () => {
            state.stepId = 'start';
            renderStep();
        });
        return restart;
    };

    const renderStep = () => {
        host.innerHTML = '';
        const step = QUIZ[state.stepId];

        if (typeof step === 'undefined') return;

        if (step.type === 'question') {
            const card = el('div', 'quiz-card');
            card.appendChild(el('div', 'quiz-prompt', step.prompt));

            const opts = el('div', 'quiz-options');
            for (const opt of step.options) {
                const b = el('button', 'quiz-option', opt.label);
                b.type = 'button';
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
            const card = el('div', 'quiz-card');
            card.innerHTML = `
                <div class="quiz-prompt">No problem. Let Analyze look first.</div>
                <p class="quiz-body">
                    Load your track on the <b>Master</b> tab and click
                    <b>Analyze</b>. It measures fixed tones and loudness,
                    marks what it finds on the <b>What do you hear?</b>
                    cards, and turns on <b>Fixed tones</b> when it finds
                    steady tones. The other cards are up to your ears: turn
                    on <b>Live</b>, listen, and pick what you hear.
                </p>
            `;
            const row = el('div', 'quiz-actions');
            row.append(goButton(null), restartButton());
            card.appendChild(row);
            host.appendChild(card);
        }
    };

    const renderResult = async (presetKey) => {
        const r = PRESET_RESULTS[presetKey];
        let rules = null;
        try { rules = await loadRules(); } catch (_) { /* words only */ }
        host.innerHTML = '';
        const info = r.card && rules ? cardInfo(rules, r.card) : null;
        const name = info ? info.card.label : 'No card';

        const card = el('div', 'quiz-card quiz-result');

        const head = el('div', 'quiz-result-head');
        head.append(el('span', 'quiz-result-label', info && !info.ready ? 'This is' : 'Turn on'),
                    ' ', el('b', 'quiz-result-name', name));
        card.appendChild(head);

        card.appendChild(el('p', 'quiz-body', r.why));

        let master;
        if (!info) {
            master = 'No card matches this preset. Click Analyze on the Master ' +
                     'tab, then pick the cards that match what you hear.';
        } else if (!info.card.tool) {
            master = `The ${name} card has no fix yet. ${NOTED}`;
        } else if (!info.ready) {
            master = `The ${name} card's fix, the ${lowerFirst(info.toolLabel)}, ` +
                     `is not built yet. ${NOTED}`;
        } else if (info.master) {
            master = `On the Master tab, turn on the ${name} card under What ` +
                     `do you hear? ${(CARD_HELP[info.card.key] || {}).note || ''}`.trim();
        } else {
            master = `On the Master tab, turn on the ${name} card under What ` +
                     `do you hear? It runs the ${lowerFirst(info.toolLabel)}. ` +
                     'Set its Amount by ear, and check the Removed track (key 3).';
        }
        card.appendChild(el('p', 'quiz-body', master));

        const inRemix = info
            ? `In Remix or Batch, the ${r.label} preset turns on the same card.` +
              (info.ready ? '' : ' For now, that does not change the sound.')
            : `In Remix or Batch, the ${r.label} preset turns on no card.`;
        card.appendChild(el('p', 'quiz-body', inRemix));

        const row = el('div', 'quiz-actions');
        row.append(goButton(info), restartButton());
        card.appendChild(row);
        host.appendChild(card);
    };

    renderStep();
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
        title.textContent = (GROUP_INTROS[group] && GROUP_INTROS[group].title) || group;
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
            if (spec.gloss) {
                const g = document.createElement('span');
                g.className = 'help-card-gloss';
                g.textContent = spec.gloss;
                h.appendChild(g);
            }
            card.appendChild(h);

            const p = document.createElement('p');
            p.className = 'help-card-short';
            p.textContent = spec.help.short;
            card.appendChild(p);

            if (spec.ends) {
                const ends = document.createElement('div');
                ends.className = 'help-card-ends';
                ends.innerHTML = `Left: <span>${spec.ends[0]}</span> · Right: <span>${spec.ends[1]}</span>`;
                card.appendChild(ends);
            }

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

// `presetSelect` is accepted so older callers keep working; nothing reads
// it now (the quiz points at a card, not the hidden preset menu).
// eslint-disable-next-line no-unused-vars
export function initHelp({ presetSelect } = {}) {
    _modal = document.getElementById('help-modal');
    if (!_modal) return;

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
    // The card guide and the preset table read the cards from the engine.
    loadRules().then((rules) => {
        renderCardsHelp(document.getElementById('cards-help-list'), rules);
        renderPresetTable(document.getElementById('preset-map-help'), rules);
    }).catch(() => {
        const host = document.getElementById('cards-help-list');
        if (host) {
            host.textContent = 'The card list could not load. Restart Shimmer ' +
                               'and open Help again.';
        }
    });

    // Wire any element on the page that asks for help via `data-help-tab`.
    document.querySelectorAll('[data-help-tab]').forEach(el => {
        el.addEventListener('click', () => {
            openHelp(el.dataset.helpTab, el.dataset.helpAnchor || null);
        });
    });
}
