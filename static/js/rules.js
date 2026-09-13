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
