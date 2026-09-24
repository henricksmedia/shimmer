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
const CAUTION_KEY = 'shimmer.cautionSeen';

function cautionSeen(key) {
    try { return (JSON.parse(localStorage.getItem(CAUTION_KEY) || '[]')).includes(key); }
    catch (_) { return false; }
}

function markCautionSeen(key) {
    try {
        const seen = JSON.parse(localStorage.getItem(CAUTION_KEY) || '[]');
        if (!seen.includes(key)) seen.push(key);
        localStorage.setItem(CAUTION_KEY, JSON.stringify(seen));
    } catch (_) { /* storage off: it asks again next time */ }
}

/**
 * The card's caution (catalog.Card.caution), in the same dialog as the
 * master-once reminder. Resolves true to turn the card on, false to leave
 * it off. Without the dialog in the page, it turns the card on.
 */
function askCaution(c) {
    return new Promise((resolve) => {
        const modal = document.getElementById('card-caution-modal');
        if (!modal || !c.caution) { resolve(true); return; }
        const [title, lead, why] = c.caution;
        document.getElementById('card-caution-title').textContent = title;
        document.getElementById('card-caution-lead').textContent = lead;
        document.getElementById('card-caution-why').textContent = why;
        const on = document.getElementById('card-caution-on');
        const cancel = document.getElementById('card-caution-cancel');
        const finish = (yes) => {
            modal.hidden = true;
            on.removeEventListener('click', onOn);
            cancel.removeEventListener('click', onCancel);
            document.removeEventListener('keydown', onKey);
            resolve(yes);
        };
        const onOn = () => finish(true);
        const onCancel = () => finish(false);
        const onKey = (e) => { if (e.key === 'Escape') finish(false); };
        on.addEventListener('click', onOn);
        cancel.addEventListener('click', onCancel);
        document.addEventListener('keydown', onKey);
        modal.hidden = false;
        on.focus();
    });
}

function bandText(band) {
    const [lo, hi] = band;
    const f = (hz) => (hz >= 1000 ? `${+(hz / 1000).toFixed(1)} kHz` : `${Math.round(hz)} Hz`);
    return hi == null ? `above ${f(lo)}` : `${f(lo)}–${f(hi)}`.replace(' kHz–', '–');
}

// Where a card's problem sits: the same log axis (20 Hz-20 kHz) and bar as
// the Signal Chain view. A range is lit; Fixed tones marks each tone found;
// Loudness covers the whole mix.
const bandPos = (hz) => Math.log10(Math.max(20, Math.min(20000, hz)) / 20) / 3 * 100;

function bandStrip(c) {
    let label, fill = '', cls = '';
    if (c.band_hz) {
        const [lo, hi] = c.band_hz;
        const left = bandPos(lo), right = bandPos(hi ?? 20000);
        label = c.band;
        fill = `<i style="left:${left.toFixed(2)}%;width:${(right - left).toFixed(2)}%"></i>`;
    } else if (c.key === 'tones') {
        label = 'One pitch';
        fill = (c.foundHz || []).map((hz) => `<i class="tick" style="left:${(bandPos(hz) - 0.5).toFixed(2)}%"></i>`).join('');
    } else {
        label = 'Whole mix';
        cls = ' whole';
        fill = '<i style="left:0;width:100%"></i>';
    }
    const state = c.on ? '<span class="bst on">On</span>' : (c.noted ? '<span class="bst">Noted</span>' : '');
    return `<span class="bnd"><span class="m-band${cls}"><span class="m-band-track">${fill}</span></span><span class="bl"><span class="hz">${label}</span>${state}</span></span>`;
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
        group: c.group, tool: c.tool, band_hz: c.band_hz,
        toolLabel: c.tool ? (rules.tool_labels[c.tool] || c.tool) : null,
        ready: !!c.tool && ready.has(c.tool),
        master: c.tool === 'tone_target' || c.tool === 'loudness_target',
        band: c.band_hz ? bandText(c.band_hz) : '',
        amount: Math.round((c.default_amount ?? rules.default_amount ?? 0.5) * 100),
        modes: c.modes || [], mode: (c.modes && c.modes.length) ? c.modes[0][0] : null,
        caution: c.caution || null,
        on: false, by: null, found: null, foundHz: null, noted: false, userOff: false,
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
        b.innerHTML = `<span class="h"><span class="ms" aria-hidden="true">${c.icon}</span><span class="t">${c.label}</span></span>
            <span class="d">${c.desc}</span>${bandStrip(c)}${chip}`;
        b.onclick = async () => {
            if (c.ready && !c.on && c.caution && !cautionSeen(c.key)) {
                // Asked once per computer, the first time it is turned on.
                if (!(await askCaution(c))) return;
                markCautionSeen(c.key);
            }
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
        if (c.modes.length > 1) {
            const ctl = document.createElement('div');
            ctl.className = 'fx-ctl';
            const lab = document.createElement('label');
            lab.htmlFor = `mode-${c.key}`;
            lab.textContent = 'Works on';
            const sel = document.createElement('select');
            sel.id = `mode-${c.key}`;
            c.modes.forEach(([key, label]) => sel.add(new Option(label, key, false, key === c.mode)));
            sel.onchange = () => { c.mode = sel.value; onChange(); };
            ctl.append(lab, sel);
            r.insertBefore(ctl, r.querySelector('.fx-note'));
        }
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
            c.foundHz = null;
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
            if (key === 'tones') c.foundHz = list.map((f) => f.value);
            // Fixed tones is the proven tool: Analyze turns it on, unless
            // the user turned it off for this song.
            if (key === 'tones' && c.ready && !c.userOff && !c.on) { c.on = true; c.by = 'Analyze'; }
        });
        render();
        onChange();
    }

    /** What the engine needs: {fixes, auto, fix_modes}. */
    function payload() {
        const fixes = {};
        cards.forEach((c) => { if (c.on && c.ready && !c.master) fixes[c.key] = c.amount / 100; });
        const tones = byKey.get('tones');
        if (tones && !tones.on && tones.userOff) fixes.tones = 0;   // turned off on purpose
        return { fixes, auto: true, fix_modes: modes() };
    }

    /** Each card's chosen way of working, where it has more than one. */
    function modes() {
        const out = {};
        cards.forEach((c) => { if (c.modes.length > 1) out[c.key] = c.mode; });
        return out;
    }

    /** The cards picked, for the Signal Chain view: {on, noted}. */
    function state() {
        return {
            on: cards.filter((c) => c.on).map((c) => c.key),
            noted: cards.filter((c) => c.noted).map((c) => c.key),
        };
    }

    /** Your own picks, card to Amount 0-1, for saved settings. */
    function picks() {
        const out = {};
        cards.forEach((c) => { if (c.on && c.by === 'you' && c.ready && !c.master) out[c.key] = c.amount / 100; });
        return out;
    }

    /** Turn on the picks from saved settings (card to Amount 0-1). A card
     *  whose fix is not ready yet is noted instead. */
    function restore(fixes, savedModes = {}) {
        Object.entries(savedModes || {}).forEach(([key, mode]) => {
            const c = byKey.get(key);
            if (c && c.modes.some(([k]) => k === mode)) c.mode = mode;
        });
        Object.entries(fixes || {}).forEach(([key, amount]) => {
            const c = byKey.get(key);
            if (!c || c.master || !(Number(amount) > 0)) return;
            if (c.ready) {
                c.on = true;
                c.by = 'you';
                c.userOff = false;
                c.amount = Math.max(1, Math.min(100, Math.round(Number(amount) * 100)));
            } else {
                c.noted = true;
            }
        });
        render();
    }

    /** Start over for a new song. With keepPicks ("Remember settings" on),
     *  your own picks stay; what Analyze found goes. */
    function reset({ keepPicks = false } = {}) {
        cards.forEach((c) => {
            const keep = keepPicks && c.on && c.by === 'you';
            if (!keep) { c.on = false; c.by = null; }
            c.found = null; c.foundHz = null; c.noted = false; c.userOff = false;
        });
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
    return { setFindings, payload, state, reset, setMasterCard, picks, modes, restore };
}
