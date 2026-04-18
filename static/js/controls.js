// controls.js — Single source of truth for the slider schema.
// Adding a knob = one entry in CONTROL_SPEC.  The rest (DOM rendering,
// value reading, preset application, help cards) is derived automatically.

export const CONTROL_SPEC = [
    {
        key: 'start_hz', label: 'Start Hz',
        min: 500, max: 12000, step: 50, group: 'Band',
        help: {
            short: 'Lowest pitch the tool will look at for shimmer.',
            when_up: 'Low and mid sounds are getting touched (bass, vocal warmth, snare body).',
            when_down: 'You can still hear shimmer below the current setting.',
            typical: '3000 - 6000 Hz',
        },
    },
    {
        key: 'end_hz', label: 'End Hz',
        min: 1000, max: 20000, step: 50, group: 'Band',
        help: {
            short: 'Highest pitch the tool will look at for shimmer.',
            when_up: 'High sparkle or fizz is being missed.',
            when_down: 'Cymbals or top-end sparkle is being dulled.',
            typical: '8000 - 14000 Hz',
        },
    },

    {
        key: 'thr_db', label: 'Threshold',
        min: 2.0, max: 20.0, step: 0.25, group: 'Detection', unit: ' dB',
        help: {
            short: 'How loud a sound must be before Shimmer treats it as fizz.',
            when_up: 'Removed track has music in it (you are cutting too much).',
            when_down: 'Fizz is still getting through.',
            typical: '5 - 9 dB',
        },
    },
    {
        key: 'slope', label: 'Slope',
        min: 0.1, max: 1.5, step: 0.05, group: 'Detection',
        help: {
            short: 'How hard to push down a sound once it is flagged as fizz.',
            when_up: 'Fizz is found but not reduced enough.',
            when_down: 'Result sounds dull or hollow.',
            typical: '0.5 - 0.8',
        },
    },

    {
        key: 'denoise', label: 'Denoise',
        min: 0.0, max: 1.0, step: 0.02, group: 'Processing', isPct: true,
        help: {
            short: 'Removes steady background hiss between notes.',
            when_up: 'You hear a constant hiss or noise floor.',
            when_down: 'Music sounds squeezed, warble, or low-mids feel thin.',
            typical: '20% - 50%',
        },
    },
    {
        key: 'deres', label: 'De-resonator',
        min: 0.0, max: 1.0, step: 0.02, group: 'Processing', isPct: true,
        help: {
            short: 'Removes a single tone that keeps ringing forever.',
            when_up: 'One pitch keeps droning on top of your music.',
            when_down: 'Sustained notes (vocals, leads) sound notched out.',
            typical: '0% - 50%',
        },
    },
    {
        key: 'deharsh', label: 'De-harsh',
        min: 0.0, max: 1.0, step: 0.02, group: 'Processing', isPct: true,
        help: {
            short: 'Softens harsh "ssss" and metallic upper-mid bite.',
            when_up: 'Vocals or cymbals sound sharp or piercing.',
            when_down: 'Result sounds lispy or lost its edge.',
            typical: '0% - 60%',
        },
    },
    {
        key: 'decheck', label: 'De-checker',
        min: 0.0, max: 1.0, step: 0.02, group: 'Processing', isPct: true,
        help: {
            short: 'Removes the regular "comb" pattern that some AI models leave.',
            when_up: 'You hear a faint repeating ringing or grid texture.',
            when_down: 'Cymbals or hi-hats lose their natural shimmer.',
            typical: '0% - 50%',
        },
    },
    {
        key: 'high_shelf_db', label: 'Air cut',
        min: -12.0, max: 0.0, step: 0.5, group: 'Processing', unit: ' dB',
        help: {
            short: 'Gently turns down the very top end (digital "sheen").',
            when_up: 'Top end sounds dull. (Move slider toward 0.)',
            when_down: 'Top end sounds glassy, brittle, or too bright.',
            typical: '-2 to -6 dB',
        },
    },
    {
        key: 'mix', label: 'Mix',
        min: 0.0, max: 1.0, step: 0.02, group: 'Processing', isPct: true,
        help: {
            short: 'How much of the cleaned sound to blend with the original.',
            when_up: 'You want more cleaning.',
            when_down: 'Cleaning is too strong; you want some original back.',
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
