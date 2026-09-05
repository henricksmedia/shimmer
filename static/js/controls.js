// controls.js — Single source of truth for the advanced artifact controls.
// Adding a knob = one entry in CONTROL_SPEC. The rest (the Advanced pane,
// value reading, preset application, help cards) is derived from it.
//
// Every control names the chain stage it drives (`module`, `group`), so
// the pane can group them in chain order and the Focus panel can point at
// the stage on the chain. Labels are the industry terms the Signal Chain
// uses; `gloss` is the plain-words descriptor; `ends` say what the two
// ends of the slider mean, so nobody needs a paragraph to read a slider.

// Sections in chain order. `phase` is the Signal Chain phase key (chain.js
// PHASES) that colours the section and lights on the mini chain.
export const GROUPS = [
    {
        key: 'repair', phase: 'repair', title: 'Repair',
        gloss: 'runs first, on the whole file',
        lead: 'Deterministic fixes before anything adaptive runs, so no later stage reacts to a click.',
    },
    {
        key: 'band', phase: 'split', title: 'Band',
        gloss: 'where the shimmer suppressor listens',
        lead: 'The pitch range the shimmer suppressor works in. This stage leaves everything outside it alone.',
    },
    {
        key: 'detection', phase: 'engine', title: 'Detection',
        gloss: 'what counts as shimmer',
        lead: 'What counts as shimmer, and how hard a flagged sound is pushed down.',
    },
    {
        key: 'tools', phase: 'engine', title: 'Cleanup tools',
        gloss: 'each one targets a different artifact',
        lead: 'Turn on only the ones that match what you hear. A tool at 0% costs nothing.',
    },
    {
        key: 'recombine', phase: 'recombine', title: 'Recombine',
        gloss: 'cleaned highs meet the untouched lows',
        lead: 'How much of the cleaned high band you keep against the original.',
    },
    {
        key: 'post', phase: 'post', title: 'Post',
        gloss: 'the last polish',
        lead: 'A gentle shelf on the very top, after everything else.',
    },
];
const GROUP_BY_KEY = Object.fromEntries(GROUPS.map(g => [g.key, g]));

// Kept for the Help tab: one line per group, no bullet walls. The
// direction cues live on each slider's ends now.
export const GROUP_INTROS = Object.fromEntries(
    GROUPS.map(g => [g.key, { title: g.title, lead: g.lead, bullets: [] }]));

export const CONTROL_SPEC = [
    // ── Repair ──────────────────────────────────────────────────────────
    {
        key: 'declick', label: 'De-click', gloss: 'clicks, pops, crackle in the highs',
        module: 'De-click', group: 'repair',
        min: 0.0, max: 1.0, step: 0.02, isPct: true,
        ends: ['off', 'more clicks caught'],
        help: {
            short: 'Removes clicks, pops and crackle from the high end. ' +
                   'Runs first in the chain, before anything else looks ' +
                   'at the audio; the low end is never touched.',
            when_up: 'You hear crackle or static on "s" sounds and cymbals, ' +
                     'or small pops.',
            when_down: 'Consonants or hi-hat ticks start to sound softened.',
            typical: '0% - 60%',
        },
    },

    // ── Band ────────────────────────────────────────────────────────────
    {
        key: 'start_hz', label: 'Start Hz', gloss: 'lowest pitch the suppressor touches',
        module: 'Shimmer Suppressor', group: 'band',
        min: 500, max: 12000, step: 50, unit: ' Hz',
        ends: ['reaches into the mids', 'protects the mids'],
        help: {
            short: 'The lowest pitch the shimmer suppressor will touch. ' +
                   'Anything below this stays exactly as it is.',
            when_up: 'Bass, vocal warmth, or snare body sound thinned out: ' +
                     'the tool is reaching down too far.',
            when_down: 'You still hear shimmer or fizz below where the tool ' +
                       'is currently looking.',
            typical: '3000 - 6000 Hz',
        },
    },
    {
        key: 'end_hz', label: 'End Hz', gloss: 'highest pitch the suppressor touches',
        module: 'Shimmer Suppressor', group: 'band',
        min: 1000, max: 20000, step: 50, unit: ' Hz',
        ends: ['protects the top end', 'reaches into the air'],
        help: {
            short: 'The highest pitch the shimmer suppressor will touch. ' +
                   'Anything above this stays exactly as it is.',
            when_up: 'You still hear sparkle or fizz at the very top end ' +
                     'that the tool is missing.',
            when_down: 'Cymbals or top-end air sound dulled: the tool is ' +
                       'reaching up too far.',
            typical: '8000 - 14000 Hz',
        },
    },

    // ── Detection ───────────────────────────────────────────────────────
    {
        key: 'thr_db', label: 'Threshold', gloss: 'how far above its neighbours a sound must stand',
        module: 'Shimmer Suppressor', group: 'detection',
        min: 2.0, max: 20.0, step: 0.25, unit: ' dB',
        ends: ['catches subtle shimmer · riskier', 'only the obvious · safer'],
        help: {
            short: 'How much louder than its neighbours a sound has to be ' +
                   'before the tool flags it as shimmer.',
            when_up: 'The Removed track has actual music in it: the tool ' +
                     'is grabbing things that should stay.',
            when_down: 'Shimmer is still leaking through: the tool is ' +
                       'being too cautious.',
            typical: '5 - 9 dB',
        },
    },
    {
        key: 'slope', label: 'Slope', gloss: 'how hard a flagged sound is pushed down',
        module: 'Shimmer Suppressor', group: 'detection',
        min: 0.1, max: 1.5, step: 0.05,
        ends: ['gentler cut', 'deeper cut'],
        help: {
            short: 'How hard to push a sound down once it has been flagged ' +
                   'as shimmer.',
            when_up: 'Shimmer is being found but not cut deep enough.',
            when_down: 'The result sounds dull, hollow, or scooped-out.',
            typical: '0.5 - 0.8',
        },
    },

    // ── Cleanup tools (the STFT engine's stages) ────────────────────────
    {
        key: 'deess', label: 'De-esser', gloss: 'sharp s, sh and t bursts in 4–10 kHz',
        module: 'De-esser', group: 'tools',
        min: 0.0, max: 1.0, step: 0.02, isPct: true,
        ends: ['off', 'more'],
        help: {
            short: 'Tames sharp "s", "sh" and "t" sounds and other short ' +
                   'bursts in 4–10 kHz. Works per frequency, so the rest ' +
                   'of the band keeps its brightness.',
            when_up: 'Consonants or hi-hat splashes cut through like a razor.',
            when_down: 'The singer starts to lisp or the hats lose their snap.',
            typical: '0% - 60%',
        },
    },
    {
        key: 'denoise', label: 'Noise Reduction', gloss: 'steady hiss under the music',
        module: 'Noise Reduction', group: 'tools',
        min: 0.0, max: 1.0, step: 0.02, isPct: true,
        ends: ['off', 'more'],
        help: {
            short: 'Removes steady background hiss, the kind that sits ' +
                   'underneath the music like tape noise.',
            when_up: 'You hear a constant hiss or noise floor that does ' +
                     'not go away.',
            when_down: 'The music sounds squeezed, watery, or the high ' +
                       'frequencies feel thin.',
            typical: '20% - 50%',
        },
    },
    {
        key: 'deres', label: 'De-resonator', gloss: 'single ringing pitches that never fade',
        module: 'De-resonator (dynamic notch)', group: 'tools',
        min: 0.0, max: 1.0, step: 0.02, isPct: true,
        ends: ['off', 'more'],
        help: {
            short: 'Removes single ringing pitches that drone on and never ' +
                   'fade away.',
            when_up: 'One specific pitch keeps ringing on top of the music ' +
                     'like a stuck note.',
            when_down: 'Sustained vocals or lead instruments sound notched ' +
                       'out or hollow.',
            typical: '0% - 50%',
        },
    },
    {
        key: 'deharsh', label: 'De-harsh', gloss: 'metallic bite on vocals, dynamic EQ',
        module: 'De-harsh (dynamic EQ)', group: 'tools',
        min: 0.0, max: 1.0, step: 0.02, isPct: true,
        ends: ['off', 'more'],
        help: {
            short: 'Softens harsh "ssss" sounds and the metallic bite that ' +
                   'AI models add to vocals.',
            when_up: 'Vocals or cymbals sound sharp, piercing, or painful.',
            when_down: 'Vocals lose their consonants ("s" and "t" sound ' +
                       'lispy) or feel dulled.',
            typical: '0% - 60%',
        },
    },
    {
        key: 'flicker_tame', label: 'Flicker Tamer', gloss: 'fast frying flicker in the hash band',
        module: 'Flicker Tamer', group: 'tools',
        min: 0.0, max: 1.0, step: 0.02, isPct: true,
        ends: ['off', 'more'],
        help: {
            short: 'Compresses the fast flicker that makes AI hash sound ' +
                   'like frying. Works in narrow sub-bands, so steady highs ' +
                   'keep their level.',
            when_up: 'The top end fries or sizzles in a fast, busy way, even ' +
                     'after Noise Reduction.',
            when_down: 'Hi-hats or shakers lose their bite and sound smeared.',
            typical: '30% - 70%',
        },
    },
    {
        key: 'decheck', label: 'Comb Suppressor', gloss: 'evenly spaced peaks, the checker grid',
        module: 'Comb Suppressor', group: 'tools',
        min: 0.0, max: 1.0, step: 0.02, isPct: true,
        ends: ['off', 'more'],
        help: {
            short: 'Removes the faint repeating "comb" or grid pattern ' +
                   'some AI models leave behind.',
            when_up: 'You hear a faint repeating ring or metallic grid ' +
                     'texture in the high end.',
            when_down: 'Cymbals or hi-hats lose their natural shimmer and ' +
                       'sparkle.',
            typical: '0% - 50%',
        },
    },
    {
        key: 'tone_kill', label: 'Tone Notcher', gloss: 'whistles that hold a pitch, then drift',
        module: 'Tone Notcher (tracking)', group: 'tools',
        min: 0.0, max: 1.0, step: 0.02, isPct: true,
        ends: ['off', 'more'],
        help: {
            short: 'Tracks whistles that hold one pitch for seconds and ' +
                   'notches them as they drift. Fixed tones are cut earlier ' +
                   'by Static Notches; this catches the ones that move.',
            when_up: 'A thin whistle rides on top of the music and slowly ' +
                     'slides in pitch.',
            when_down: 'Long held notes or sustained vocals get thinner.',
            typical: '0% - 70%',
        },
    },
    {
        key: 'noise_resynth', label: 'Noise Resynthesis', gloss: 'fills the holes deep cleaning leaves',
        module: 'Noise Resynthesis', group: 'tools',
        min: 0.0, max: 1.0, step: 0.02, isPct: true,
        ends: ['off', 'more'],
        help: {
            short: 'Puts a little smooth noise back where the cleaning cut ' +
                   'deep, so the top end does not sound hollow or gated.',
            when_up: 'The cleaned top end sounds empty, choppy, or pumps in ' +
                     'and out.',
            when_down: 'You hear a soft hiss that was not there before.',
            typical: '0% - 30%',
        },
    },

    // ── Recombine ───────────────────────────────────────────────────────
    {
        key: 'mix', label: 'Mix', gloss: 'wet/dry: cleaned against the original',
        module: 'Wet/dry mix', group: 'recombine',
        min: 0.0, max: 1.0, step: 0.02, isPct: true,
        ends: ['original', 'fully cleaned'],
        help: {
            short: 'How much of the cleaned sound you hear. At 0% you ' +
                   'hear the original untouched (shimmer and all); at ' +
                   '100% you hear only the cleaned version.',
            when_up: 'You want more of the cleaning to come through.',
            when_down: 'The cleaning is too aggressive and you want to ' +
                       'blend some of the original back in.',
            typical: '80% - 100%',
        },
    },

    // ── Post ────────────────────────────────────────────────────────────
    {
        key: 'high_shelf_db', label: 'Air cut', gloss: 'high shelf on the very top',
        module: 'Post filters', group: 'post',
        min: -12.0, max: 0.0, step: 0.5, unit: ' dB',
        ends: ['more cut', 'off · 0 dB'],
        help: {
            short: 'Gently turns down the very top end as a final polish, ' +
                   'softening any leftover digital "sheen".',
            when_up: 'The top end sounds dull or muffled: move the slider ' +
                     'back toward 0.',
            when_down: 'The top end sounds glassy, brittle, or too bright.',
            typical: '-2 to -6 dB',
        },
    },
];
export const SPEC_BY_KEY = Object.fromEntries(CONTROL_SPEC.map(s => [s.key, s]));

export function formatValue(spec, v) {
    if (spec.isPct) return `${Math.round(v * 100)}%`;
    if (spec.step >= 1) return `${Math.round(v)}${spec.unit || ''}`;
    const decimals = spec.step < 0.1 ? 2 : 1;
    return `${Number(v).toFixed(decimals)}${spec.unit || ''}`;
}

function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
}

/**
 * Render the controls into `host`, grouped in chain order.
 *
 *   onChange(key, value)   fires on every slider move
 *   onHelpClick(key)       fires from the ? button (opens the Help tab)
 *   opts.onFocus(spec|null, state)  the Focus panel: which control is
 *                          under the pointer or keyboard, with its value
 *                          and baseline
 *   opts.onDirty(changed)  the list of controls that differ from the
 *                          preset baseline changed
 *
 * Returns { getValues, setValues, setBaseline, getBaseline, getChanged,
 *           resetAll, inputs }. `setBaseline(values)` is the preset's
 * values at the current strength: it draws the tick under each slider
 * and decides what "changed" means. Double-click a slider to go back to
 * its baseline; Shift + arrow keys move ten steps.
 */
export function renderControls(host, onChange, onHelpClick, opts = {}) {
    host.innerHTML = '';
    const inputs = new Map();
    const baseline = {};
    const sectionCounts = new Map();

    const byGroup = new Map();
    for (const spec of CONTROL_SPEC) {
        if (!byGroup.has(spec.group)) byGroup.set(spec.group, []);
        byGroup.get(spec.group).push(spec);
    }

    const pct = (spec, v) => `${((v - spec.min) / (spec.max - spec.min)) * 100}%`;
    const isChanged = (spec, v) => {
        const b = baseline[spec.key];
        return Number.isFinite(b) && Math.abs(v - b) > spec.step / 2;
    };

    const syncRow = (key) => {
        const it = inputs.get(key);
        if (!it) return;
        const v = parseFloat(it.range.value);
        it.val.textContent = formatValue(it.spec, v);
        const changed = isChanged(it.spec, v);
        it.row.classList.toggle('changed', changed);
        it.changed.hidden = !changed;
        it.fill.style.width = pct(it.spec, v);
        const b = baseline[key];
        if (Number.isFinite(b)) {
            it.tick.hidden = false;
            it.tick.style.left = pct(it.spec, b);
            it.tick.title = `Preset: ${formatValue(it.spec, b)}`;
        } else {
            it.tick.hidden = true;
        }
    };
    const syncCounts = () => {
        for (const [gkey, badge] of sectionCounts) {
            const n = [...inputs.values()].filter(it => it.spec.group === gkey && isChanged(it.spec, parseFloat(it.range.value))).length;
            badge.textContent = n ? `${n} changed` : '';
            badge.hidden = !n;
        }
        if (opts.onDirty) opts.onDirty(getChanged());
    };
    const focusState = (spec) => {
        const it = inputs.get(spec.key);
        const v = parseFloat(it.range.value);
        return { value: v, valueText: formatValue(spec, v), baseline: baseline[spec.key],
                 baselineText: Number.isFinite(baseline[spec.key]) ? formatValue(spec, baseline[spec.key]) : null,
                 changed: isChanged(spec, v), group: GROUP_BY_KEY[spec.group] };
    };
    const tellFocus = (spec) => { if (opts.onFocus) opts.onFocus(spec, spec ? focusState(spec) : null); };

    for (const [gkey, specs] of byGroup) {
        const g = GROUP_BY_KEY[gkey] || { title: gkey, gloss: '', lead: '', phase: 'engine' };
        const section = el('section', 'adv-section');
        section.dataset.phase = g.phase;
        const head = el('div', 'adv-section-head');
        head.append(el('span', 'adv-section-bar'), el('span', 'adv-section-title', g.title),
                    el('span', 'adv-section-gloss', g.gloss));
        const count = el('span', 'adv-section-count');
        count.hidden = true;
        head.appendChild(count);
        sectionCounts.set(gkey, count);
        section.appendChild(head);
        if (g.lead) section.appendChild(el('div', 'adv-lead', g.lead));

        for (const spec of specs) {
            const row = el('div', 'adv-row');
            row.dataset.key = spec.key;

            const rowHead = el('div', 'adv-row-head');
            const term = el('label', 'adv-term', spec.label);
            term.htmlFor = `adv-${spec.key}`;
            const gloss = el('span', 'adv-gloss', spec.gloss || '');
            const changed = el('span', 'adv-changed', 'changed');
            changed.hidden = true;
            const helpBtn = el('button', 'help-icon', '?');
            helpBtn.type = 'button';
            helpBtn.title = spec.help ? spec.help.short : '';
            helpBtn.setAttribute('aria-label', `Help: ${spec.label}`);
            if (onHelpClick) helpBtn.addEventListener('click', () => onHelpClick(spec.key));
            const val = el('span', 'adv-value');
            rowHead.append(term, gloss, changed, helpBtn, val);

            const track = el('div', 'adv-track');
            const fill = el('i', 'adv-fill');
            const tick = el('i', 'adv-tick');
            tick.hidden = true;
            const range = document.createElement('input');
            range.type = 'range';
            range.id = `adv-${spec.key}`;
            range.min = String(spec.min);
            range.max = String(spec.max);
            range.step = String(spec.step);
            range.dataset.key = spec.key;
            range.setAttribute('aria-label', spec.label);
            track.append(fill, tick, range);

            const ends = el('div', 'adv-ends');
            ends.append(el('span', null, (spec.ends && spec.ends[0]) || ''),
                        el('span', null, (spec.ends && spec.ends[1]) || ''));

            row.append(rowHead, track, ends);
            section.appendChild(row);
            inputs.set(spec.key, { range, val, spec, row, fill, tick, changed });

            range.addEventListener('input', () => {
                syncRow(spec.key);
                syncCounts();
                tellFocus(spec);
                if (onChange) onChange(spec.key, parseFloat(range.value));
            });
            // Shift + arrows: ten steps at a time (DAW habit).
            range.addEventListener('keydown', (e) => {
                if (!e.shiftKey) return;
                const dir = e.key === 'ArrowRight' || e.key === 'ArrowUp' ? 1
                    : e.key === 'ArrowLeft' || e.key === 'ArrowDown' ? -1 : 0;
                if (!dir) return;
                e.preventDefault();
                const v = Math.min(spec.max, Math.max(spec.min, parseFloat(range.value) + dir * spec.step * 10));
                range.value = String(v);
                range.dispatchEvent(new Event('input', { bubbles: true }));
            });
            // Double-click: back to the preset's value.
            range.addEventListener('dblclick', () => {
                const b = baseline[spec.key];
                if (!Number.isFinite(b)) return;
                range.value = String(b);
                range.dispatchEvent(new Event('input', { bubbles: true }));
            });
            const focusIn = () => { row.classList.add('focus'); tellFocus(spec); };
            const focusOut = () => { row.classList.remove('focus'); };
            row.addEventListener('pointerenter', focusIn);
            row.addEventListener('pointerleave', focusOut);
            range.addEventListener('focus', focusIn);
            range.addEventListener('blur', focusOut);
        }
        host.appendChild(section);
    }

    const getValues = () => {
        const out = {};
        for (const [key, { range }] of inputs) out[key] = parseFloat(range.value);
        return out;
    };
    const setValues = (params) => {
        for (const [key, { range }] of inputs) {
            if (params[key] === undefined || params[key] === null) continue;
            range.value = String(Number(params[key]));
            syncRow(key);
        }
        syncCounts();
    };
    const setBaseline = (params) => {
        for (const key of inputs.keys()) {
            const v = params ? params[key] : undefined;
            if (v === undefined || v === null) delete baseline[key];
            else baseline[key] = Number(v);
            syncRow(key);
        }
        syncCounts();
    };
    const getBaseline = () => ({ ...baseline });
    const getChanged = () => {
        const out = [];
        for (const [key, it] of inputs) {
            const v = parseFloat(it.range.value);
            if (isChanged(it.spec, v)) {
                out.push({ key, label: it.spec.label, value: v, valueText: formatValue(it.spec, v),
                           baseline: baseline[key], baselineText: formatValue(it.spec, baseline[key]) });
            }
        }
        return out;
    };
    const resetAll = () => {
        let touched = false;
        for (const [key, it] of inputs) {
            const b = baseline[key];
            if (!Number.isFinite(b)) continue;
            if (Math.abs(parseFloat(it.range.value) - b) > it.spec.step / 2) {
                it.range.value = String(b);
                syncRow(key);
                touched = true;
                if (onChange) onChange(key, b);
            }
        }
        syncCounts();
        return touched;
    };

    return { getValues, setValues, setBaseline, getBaseline, getChanged, resetAll, inputs };
}
