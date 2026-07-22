// controls.js — Single source of truth for the slider schema.
// Adding a knob = one entry in CONTROL_SPEC.  The rest (DOM rendering,
// value reading, preset application, help cards) is derived automatically.

// Plain-English intros for each slider group. Rendered at the top of
// every group in BOTH the slider panel (so users have context while
// adjusting) AND the help panel (so the reference doc uses the same
// copy). Each entry is `{lead, bullets}` — a one-line opener plus
// scannable directional cues per slider.
export const GROUP_INTROS = {
    'Band': {
        lead: 'These two sliders set the pitch range the tool will touch. ' +
              'Anything below Start Hz or above End Hz is left completely alone.',
        bullets: [
            'Start Hz LEFT — reach further down into the mids (more of the sound gets touched).',
            'Start Hz RIGHT — protect the mids (the tool stays up high).',
            'End Hz RIGHT — reach further up into the treble (catches more top-end fizz).',
            'End Hz LEFT — protect the top end (cymbals and air stay untouched).',
        ],
    },
    'Detection': {
        lead: 'These decide what counts as shimmer and how hard to cut it ' +
              'once it is found.',
        bullets: [
            'Threshold LEFT — catch quieter, more subtle shimmer (riskier; may grab real music).',
            'Threshold RIGHT — only catch the loudest, most obvious shimmer (safer).',
            'Slope LEFT — gentler cut on flagged sounds.',
            'Slope RIGHT — deeper cut on flagged sounds.',
        ],
    },
    'Processing': {
        lead: 'These are the actual cleanup tools — each one targets a ' +
              'different kind of artifact. Turn on only the ones that ' +
              'match what you hear; leaving the rest in their OFF position ' +
              'costs you nothing.',
        bullets: [
            'Denoise, De-resonator, De-harsh, De-checker, Mix — LEFT (0%) is OFF, RIGHT is more of that effect.',
            'Air cut is INVERTED — OFF at the RIGHT edge (0 dB), more cut as you move LEFT toward -12 dB.',
        ],
    },
};

export const CONTROL_SPEC = [
    {
        key: 'start_hz', label: 'Start Hz',
        min: 500, max: 12000, step: 50, group: 'Band',
        help: {
            short: 'The lowest pitch the tool will touch. Anything below ' +
                   'this stays exactly as it is.',
            when_up: 'Bass, vocal warmth, or snare body sound thinned out — ' +
                     'the tool is reaching down too far.',
            when_down: 'You still hear shimmer or fizz below where the tool ' +
                       'is currently looking.',
            typical: '3000 - 6000 Hz',
        },
    },
    {
        key: 'end_hz', label: 'End Hz',
        min: 1000, max: 20000, step: 50, group: 'Band',
        help: {
            short: 'The highest pitch the tool will touch. Anything above ' +
                   'this stays exactly as it is.',
            when_up: 'You still hear sparkle or fizz at the very top end ' +
                     'that the tool is missing.',
            when_down: 'Cymbals or top-end air sound dulled — the tool is ' +
                       'reaching up too far.',
            typical: '8000 - 14000 Hz',
        },
    },

    {
        key: 'thr_db', label: 'Threshold',
        min: 2.0, max: 20.0, step: 0.25, group: 'Detection', unit: ' dB',
        help: {
            short: 'How much louder than its neighbors a sound has to be ' +
                   'before the tool flags it as shimmer.',
            when_up: 'The Removed track has actual music in it — the tool ' +
                     'is grabbing things that should stay.',
            when_down: 'Shimmer is still leaking through — the tool is ' +
                       'being too cautious.',
            typical: '5 - 9 dB',
        },
    },
    {
        key: 'slope', label: 'Slope',
        min: 0.1, max: 1.5, step: 0.05, group: 'Detection',
        help: {
            short: 'How hard to push a sound down once it has been flagged ' +
                   'as shimmer.',
            when_up: 'Shimmer is being found but not cut deep enough.',
            when_down: 'The result sounds dull, hollow, or scooped-out.',
            typical: '0.5 - 0.8',
        },
    },

    {
        key: 'denoise', label: 'Denoise',
        min: 0.0, max: 1.0, step: 0.02, group: 'Processing', isPct: true,
        help: {
            short: 'Removes steady background hiss — the kind that sits ' +
                   'underneath the music like tape noise.',
            when_up: 'You hear a constant hiss or noise floor that does ' +
                     'not go away.',
            when_down: 'The music sounds squeezed, watery, or the high ' +
                       'frequencies feel thin.',
            typical: '20% - 50%',
        },
    },
    {
        key: 'deres', label: 'De-resonator',
        min: 0.0, max: 1.0, step: 0.02, group: 'Processing', isPct: true,
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
        key: 'deharsh', label: 'De-harsh',
        min: 0.0, max: 1.0, step: 0.02, group: 'Processing', isPct: true,
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
        key: 'decheck', label: 'De-checker',
        min: 0.0, max: 1.0, step: 0.02, group: 'Processing', isPct: true,
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
        key: 'high_shelf_db', label: 'Air cut',
        min: -12.0, max: 0.0, step: 0.5, group: 'Processing', unit: ' dB',
        help: {
            short: 'Gently turns down the very top end as a final polish, ' +
                   'softening any leftover digital "sheen".',
            when_up: 'The top end sounds dull or muffled — move the slider ' +
                     'back toward 0.',
            when_down: 'The top end sounds glassy, brittle, or too bright.',
            typical: '-2 to -6 dB',
        },
    },
    {
        key: 'mix', label: 'Mix',
        min: 0.0, max: 1.0, step: 0.02, group: 'Processing', isPct: true,
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
];

function formatValue(spec, v) {
    if (spec.isPct) return `${Math.round(v * 100)}%`;
    if (spec.step >= 1) return `${Math.round(v)}${spec.unit || ''}`;
    const decimals = spec.step < 0.1 ? 2 : 1;
    return `${Number(v).toFixed(decimals)}${spec.unit || ''}`;
}

/**
 * Render the control spec into the host element.  Returns a getValues()
 * function that snapshots the current slider state as {key: number, ...}.
 *
 * If `onHelpClick(specKey)` is provided, a small ? button is rendered
 * next to each slider label that fires it.
 */
export function renderControls(host, onChange, onHelpClick) {
    host.innerHTML = '';
    const byGroup = new Map();
    for (const spec of CONTROL_SPEC) {
        if (!byGroup.has(spec.group)) byGroup.set(spec.group, []);
        byGroup.get(spec.group).push(spec);
    }

    const inputs = new Map();

    for (const [group, specs] of byGroup) {
        const box = document.createElement('div');
        box.className = 'slider-group';
        const title = document.createElement('div');
        title.className = 'slider-group-title';
        title.textContent = group;
        box.appendChild(title);

        const intro = GROUP_INTROS[group];
        if (intro) {
            const introWrap = document.createElement('div');
            introWrap.className = 'slider-group-intro';
            if (intro.lead) {
                const lead = document.createElement('p');
                lead.className = 'slider-group-intro-lead';
                lead.textContent = intro.lead;
                introWrap.appendChild(lead);
            }
            if (intro.bullets && intro.bullets.length) {
                const ul = document.createElement('ul');
                ul.className = 'slider-group-intro-list';
                for (const b of intro.bullets) {
                    const li = document.createElement('li');
                    li.textContent = b;
                    ul.appendChild(li);
                }
                introWrap.appendChild(ul);
            }
            box.appendChild(introWrap);
        }

        for (const spec of specs) {
            const row = document.createElement('div');
            row.className = 'slider-row';

            const labelWrap = document.createElement('div');
            labelWrap.className = 'slider-label-wrap';

            const label = document.createElement('label');
            label.className = 'slider-label';
            label.textContent = spec.label;
            labelWrap.appendChild(label);

            if (onHelpClick && spec.help) {
                const helpBtn = document.createElement('button');
                helpBtn.type = 'button';
                helpBtn.className = 'help-icon';
                helpBtn.textContent = '?';
                helpBtn.title = spec.help.short;
                helpBtn.setAttribute('aria-label', `Help: ${spec.label}`);
                helpBtn.addEventListener('click', () => onHelpClick(spec.key));
                labelWrap.appendChild(helpBtn);
            }

            const range = document.createElement('input');
            range.type = 'range';
            range.min = String(spec.min);
            range.max = String(spec.max);
            range.step = String(spec.step);
            range.dataset.key = spec.key;
            if (spec.help) range.title = spec.help.short;

            const val = document.createElement('span');
            val.className = 'slider-value';

            range.addEventListener('input', () => {
                val.textContent = formatValue(spec, parseFloat(range.value));
                if (onChange) onChange(spec.key, parseFloat(range.value));
            });

            row.append(labelWrap, range, val);
            box.appendChild(row);
            inputs.set(spec.key, {range, val, spec});
        }
        host.appendChild(box);
    }

    const getValues = () => {
        const out = {};
        for (const [key, {range}] of inputs) {
            out[key] = parseFloat(range.value);
        }
        return out;
    };

    const setValues = (params) => {
        for (const [key, {range, val, spec}] of inputs) {
            if (params[key] === undefined || params[key] === null) continue;
            const v = Number(params[key]);
            range.value = String(v);
            val.textContent = formatValue(spec, v);
        }
    };

    return {getValues, setValues, inputs};
}
