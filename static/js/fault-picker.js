// fault-picker.js — the "What do you hear?" card, as approved in
// static/tmp/shimmer-what-do-you-hear-mockup.html (docs/ARCHITECTURE.md
// §13.2a, §19.3).
//
// The cards, their tools, and which tools are built all come from
// /api/rules, so this screen never keeps its own copy. Findings arrive with
// the upload and with Analyze. The picks go to the engine as `fixes`
// ({card: amount 0-1}) and `auto` (Analyze turns on what it finds).
//
// A card whose tool is not built yet says so and can only be "noted": it
// never pretends to fix something (§19.2 D3). Noted picks are counted on
// this computer to help test new fixes.

const NOTED_KEY = 'shimmer.notedCards';

function bandText(band) {
    const [lo, hi] = band;
    const f = (hz) => (hz >= 1000 ? `${+(hz / 1000).toFixed(1)} kHz` : `${Math.round(hz)} Hz`);
    return hi == null ? `above ${f(lo)}` : `${f(lo)}–${f(hi)}`.replace(' kHz–', '–');
}

function foundText(card, list) {
    if (card === 'tones') {
        return list.length === 1 ? `${(list[0].value / 1000).toFixed(2)} kHz`
                                 : `${list.length} tones`;
    }
    if (card === 'loudness') return `${list[0].value.toFixed(1)} dB under`;
    return `${list[0].value} ${list[0].unit}`;
}

function countNoted(key) {
    try {
        const counts = JSON.parse(localStorage.getItem(NOTED_KEY) || '{}');
        counts[key] = (counts[key] || 0) + 1;
        localStorage.setItem(NOTED_KEY, JSON.stringify(counts));
    } catch (_) { /* storage off: the pick still shows */ }
}

/**
 * Build the card inside the elements #hear-verdict, #hear-g1, #hear-g2 and
 * #hear-fixes. `onChange()` runs when a pick or an amount changes;
 * `onMasterCard(key, on)` runs when a card that lives in Mastering
 * (Loudness, Lack of air) is turned on or off.
 */
export async function initFaultPicker({ onChange = () => {}, onMasterCard = () => {} } = {}) {
    const $ = (id) => document.getElementById(id);
    const rules = await fetch('/api/rules').then((r) => r.json());
    const ready = new Set(rules.tools_ready || []);
    const cards = rules.cards.map((c) => ({
        key: c.key, label: c.label, desc: c.descriptor, tip: c.tip, icon: c.icon,
        group: c.group, tool: c.tool,
        toolLabel: c.tool ? (rules.tool_labels[c.tool] || c.tool) : null,
        ready: !!c.tool && ready.has(c.tool),
        master: c.tool === 'tone_target' || c.tool === 'loudness_target',
        band: c.band_hz ? bandText(c.band_hz) : '',
        amount: Math.round((c.default_amount ?? rules.default_amount ?? 0.5) * 100),
        on: false, by: null, found: null, noted: false, userOff: false,
    }));
    const byKey = new Map(cards.map((c) => [c.key, c]));

    function tile(c) {
        const b = document.createElement('button');
        b.type = 'button';
        b.className = 'hear-tile' + (c.on ? ' on' : (c.noted ? ' noted' : ''));
        b.setAttribute('aria-pressed', c.on || c.noted ? 'true' : 'false');
        b.title = c.tip + (c.ready ? `\nFix: ${c.toolLabel}`
            : (c.tool ? `\n${c.toolLabel}: not built yet` : '\nNo tested fix yet'));
        let chip = '';
        if (c.found) chip = `<span class="st found">Found · ${c.found}</span>`;
        else if (!c.tool) chip = '<span class="st nofix">No fix yet</span>';
        else if (!c.ready) chip = '<span class="st nofix">Not built yet</span>';
        b.innerHTML = `<span class="ms" aria-hidden="true">${c.icon}</span>
            <span class="t">${c.label}</span><span class="d">${c.desc}</span>${chip}`;
        b.onclick = () => {
            if (!c.ready) {
                c.noted = !c.noted;
                if (c.noted) countNoted(c.key);
            } else {
                c.on = !c.on;
                c.by = c.on ? 'you' : null;
                c.userOff = !c.on;
                if (c.master) onMasterCard(c.key, c.on);
                onChange();
            }
            render();
        };
        return b;
    }

    function fixRow(c) {
        const r = document.createElement('div');
        r.className = 'fx-row';
        const src = c.by === 'Analyze' ? 'by Analyze' : 'by you';
        if (c.master) {
            const note = c.key === 'loudness'
                ? 'Loudness target set to Commercial (−9 LUFS) in Mastering.'
                : 'Brightens the top end in Mastering.';
            r.innerHTML = `<div class="fx-head"><span class="ms" aria-hidden="true">${c.icon}</span>${c.toolLabel}<span class="fx-src">${src}</span></div>
                <div class="fx-note">${note}</div>`;
            return r;
        }
        const note = c.found ? '' : '<div class="fx-note">Analyze didn’t measure this. Starting gentle — check the Removed track.</div>';
        r.innerHTML = `<div class="fx-head"><span class="ms" aria-hidden="true">${c.icon}</span>${c.toolLabel}<span class="fx-for">· ${c.label}</span><span class="fx-src">${src}</span></div>
            <div class="fx-ctl"><label for="amt-${c.key}">Amount</label><input id="amt-${c.key}" type="range" min="0" max="100" step="1" value="${c.amount}"><span class="fx-val" id="val-${c.key}">${c.amount}%</span></div>${note}`;
        const rng = r.querySelector('input');
        rng.oninput = () => {
            c.amount = Math.round(+rng.value);
            r.querySelector(`#val-${c.key}`).textContent = `${c.amount}%`;
        };
        rng.onchange = () => onChange();
        return r;
    }

    function render() {
        $('hear-g1').innerHTML = '';
        $('hear-g2').innerHTML = '';
        cards.forEach((c) => $(c.group === 'artifacts' ? 'hear-g1' : 'hear-g2').appendChild(tile(c)));
        const found = cards.filter((c) => c.found).length;
        const on = cards.filter((c) => c.on);
        const noted = cards.filter((c) => c.noted);
        $('hear-verdict').innerHTML = `<span class="ms" aria-hidden="true">troubleshoot</span>`
            + `Analyze found ${found} · ${on.length} fix${on.length === 1 ? '' : 'es'} on`;
        const fx = $('hear-fixes');
        fx.innerHTML = '<div class="pb-effect-label">Fixes on</div>';
        if (!on.length) fx.insertAdjacentHTML('beforeend', '<div class="fx-note">Nothing on yet. Pick what you hear above.</div>');
        on.forEach((c) => fx.appendChild(fixRow(c)));
        noted.forEach((c) => fx.insertAdjacentHTML('beforeend',
            `<div class="fx-row"><div class="fx-head muted"><span class="ms" aria-hidden="true">${c.icon}</span>${c.label}<span class="fx-src">noted</span></div>
             <div class="fx-note">No tested fix yet. Your pick is saved on this computer to help test new fixes.</div></div>`));
    }

    /** Findings from the upload or Analyze: [{card, value, unit, detail}]. */
    function setFindings(findings) {
        cards.forEach((c) => {
            c.found = null;
            if (c.by === 'Analyze') { c.on = false; c.by = null; }
        });
        const groups = new Map();
        (findings || []).forEach((f) => {
            if (!groups.has(f.card)) groups.set(f.card, []);
            groups.get(f.card).push(f);
        });
        groups.forEach((list, key) => {
            const c = byKey.get(key);
            if (!c) return;
            c.found = foundText(key, list);
            // Fixed tones is the proven tool: Analyze turns it on, unless
            // the user turned it off for this song.
            if (key === 'tones' && c.ready && !c.userOff && !c.on) { c.on = true; c.by = 'Analyze'; }
        });
        render();
        onChange();
    }

    /** What the engine needs: {fixes, auto}. */
    function payload() {
        const fixes = {};
        cards.forEach((c) => { if (c.on && c.ready && !c.master) fixes[c.key] = c.amount / 100; });
        const tones = byKey.get('tones');
        if (tones && !tones.on && tones.userOff) fixes.tones = 0;   // turned off on purpose
        return { fixes, auto: true };
    }

    /** Start over for a new song. */
    function reset() {
        cards.forEach((c) => { c.on = false; c.by = null; c.found = null; c.noted = false; c.userOff = false; });
        render();
    }

    /** Keep a Mastering card in step when its control changes elsewhere. */
    function setMasterCard(key, on) {
        const c = byKey.get(key);
        if (!c) return;
        c.on = !!on;
        c.by = on ? 'you' : null;
        render();
    }

    render();
    return { setFindings, payload, reset, setMasterCard };
}
