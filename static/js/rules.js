// rules.js — the engine's rules, fetched once from GET /api/rules.
//
// The screens used to keep their own copies of the Loudness choices, the
// format ceilings and more, and the copies drifted (docs/ARCHITECTURE.md
// §7). Every script reads them from here instead.

let rulesPromise = null;

/** The /api/rules answer, fetched once per page. */
export function loadRules() {
    if (!rulesPromise) rulesPromise = fetch('/api/rules').then((r) => r.json());
    return rulesPromise;
}

/** The LUFS level of a Loudness choice key, or null. */
export function loudnessLufs(rules, key) {
    const t = (rules.loudness_targets || []).find((x) => x.key === key);
    return t ? t.lufs : null;
}

// One colour per engine stage, for the progress window.
export const STAGE_COLOURS = {
    load: '#2dd4bf', edit: '#22d3ee', rate: '#38bdf8', fixes: '#60a5fa', tone: '#a78bfa',
    eq: '#c084fc', master: '#f5a524', export: '#fbbf24', report: '#f472b6',
};

/** Add each format's true-peak ceiling to its option in a format menu, as
 *  "MP3 (320 kbps) · −2.0 dBTP". The option's own name stays in the page;
 *  the number comes from the engine. Safe to call more than once. */
export function fillFormatCeilings(rules, select) {
    if (!select) return;
    const ceilings = new Map((rules.formats || []).map((f) => [f.key, f.ceiling_dbtp]));
    for (const opt of select.options) {
        if (!opt.dataset.name) opt.dataset.name = opt.textContent.trim();
        const c = ceilings.get(opt.value);
        opt.textContent = Number.isFinite(c)
            ? `${opt.dataset.name} · ${c.toFixed(1).replace('-', '−')} dBTP`
            : opt.dataset.name;
    }
}

/** The engine's stages as the progress window's [key, label, colour] rows,
 *  leaving out the keys in `skip`. */
export function stagePhases(rules, skip = []) {
    return (rules.stages || []).filter((s) => !skip.includes(s.key))
        .map((s) => [s.key, s.label, STAGE_COLOURS[s.key] || '#94a3b8']);
}
