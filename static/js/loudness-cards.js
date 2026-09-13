// loudness-cards.js — the Loudness target as three cards, as approved in
// static/tmp/shimmer-loudness-cards-mockup.html (2026-09-12).
//
// The choices, their names and the default come from /api/rules, so this
// screen keeps no copy of them. The <select> stays in the page, hidden: it
// is still the value every other script reads and sets (saved settings,
// the "What do you hear?" Loudness card). The cards only show it and
// change it.

let rulesPromise = null;

function loadRules() {
    if (!rulesPromise) rulesPromise = fetch('/api/rules').then((r) => r.json());
    return rulesPromise;
}

/** Put the cards in front of `select` (a Loudness target <select>). */
export async function initLoudnessCards(select) {
    if (!select || select.dataset.cards) return;
    select.dataset.cards = '1';
    const rules = await loadRules();
    const box = document.createElement('div');
    box.className = 'loud-cards';
    box.setAttribute('role', 'radiogroup');
    const label = select.id ? document.querySelector(`label[for="${select.id}"]`) : null;
    if (label) {
        if (!label.id) label.id = `${select.id}-label`;
        box.setAttribute('aria-labelledby', label.id);
    }
    select.hidden = true;
    select.insertAdjacentElement('beforebegin', box);

    let shown = null;
    function render() {
        shown = select.value;
        box.innerHTML = '';
        rules.loudness_targets.forEach((t) => {
            const on = select.value === t.key;
            const b = document.createElement('button');
            b.type = 'button';
            b.className = 'loud-card' + (on ? ' on' : '');
            b.setAttribute('role', 'radio');
            b.setAttribute('aria-checked', on ? 'true' : 'false');
            b.title = t.sublabel;
            b.innerHTML = `<span class="t">${t.label}${t.default ? '<span class="def">DEFAULT</span>' : ''}</span>
                <span class="v">${String(t.lufs).replace('-', '−')} LUFS</span><span class="d">${t.sublabel}</span>`;
            b.onclick = () => {
                if (select.value !== t.key) {
                    select.value = t.key;
                    select.dispatchEvent(new Event('change', { bubbles: true }));
                }
                render();
            };
            box.appendChild(b);
        });
    }
    select.addEventListener('change', render);
    // Saved settings are restored by setting the value with no event, so
    // the cards also follow the value when it changes quietly.
    setInterval(() => { if (select.value !== shown) render(); }, 400);
    render();
}
