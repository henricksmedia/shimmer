// players.js — Synced multi-track playback for A/B/C comparison.
//
// The three result players (Original / Processed / Removed) share a single
// playhead.  One is "active" (audible) at any time; the others are paused
// but seeked to the same currentTime so the user can click any card to
// hear it instantly at the same position.

/**
 * Assign a fresh URL to an <audio>.  Adds a cache-buster so subsequent
 * jobs with the same job_id aren't served a stale response.
 */
export function setAudioSource(audioEl, url) {
    if (!url) {
        audioEl.removeAttribute('src');
        audioEl.load();
        return;
    }
    const bust = url.includes('?') ? '&' : '?';
    audioEl.src = `${url}${bust}_=${Date.now()}`;
    audioEl.load();
}

/**
 * Wire a fixed group of <audio> elements as a synced A/B/C comparison
 * group.  Returns a small handle with `reset()` and `setActive(el)`.
 *
 * - Playing any element pauses the others, seeks them to the shared
 *   playhead, and marks that element as the audible one.
 * - Scrubbing on any element propagates the new time to the others.
 * - The active element gets a `.active` class on its closest
 *   `.results-card` ancestor for styling.
 */
export function installSyncedGroup(audioEls) {
    const els = audioEls.filter(Boolean);
    if (els.length === 0) {
        return {
            reset() {}, setActive() {}, setSuspended() {},
            elements: [], sharedTime: 0, active: null,
        };
    }

    let sharedTime = 0;
    let active = els[0];
    let suppressSeek = false;
    // Suspended elements still pause others on play (so we never play
    // overlapping audio), but they neither push their playhead onto the
    // group nor get yanked by the group's playhead.
    const suspended = new Set();
    const isSuspended = (el) => suspended.has(el);

    const cardOf = (a) => a.closest('.results-card');

    const markActive = (a) => {
        for (const b of els) {
            const card = cardOf(b);
            if (card) card.classList.toggle('active', b === a);
        }
    };

    const seekOthers = (src, t) => {
        if (!Number.isFinite(t)) return;
        if (isSuspended(src)) return;
        suppressSeek = true;
        try {
            for (const a of els) {
                if (a === src) continue;
                if (isSuspended(a)) continue;
                if (!Number.isFinite(a.duration)) continue;
                if (Math.abs(a.currentTime - t) > 0.05) {
                    a.currentTime = Math.min(t, a.duration);
                }
            }
        } finally {
            suppressSeek = false;
        }
    };

    for (const a of els) {
        a.addEventListener('play', () => {
            for (const b of els) {
                if (b !== a && !b.paused) b.pause();
            }
            // Only fan out playhead if both source and active group share
            // a clock (i.e. the playing element isn't suspended).
            if (!isSuspended(a)) seekOthers(a, a.currentTime);
            active = a;
            markActive(a);
        });

        a.addEventListener('pause', () => {
            if (a === active && !isSuspended(a)) sharedTime = a.currentTime;
        });

        a.addEventListener('timeupdate', () => {
            if (a !== active) return;
            if (isSuspended(a)) return;
            sharedTime = a.currentTime;
            seekOthers(a, sharedTime);
        });

        a.addEventListener('seeked', () => {
            if (suppressSeek) return;
            if (isSuspended(a)) return;
            sharedTime = a.currentTime;
            seekOthers(a, sharedTime);
        });
    }

    markActive(active);

    return {
        reset() {
            sharedTime = 0;
            suppressSeek = true;
            try {
                for (const a of els) {
                    try { a.currentTime = 0; } catch (_) { /* not loaded yet */ }
                }
            } finally {
                suppressSeek = false;
            }
        },
        setActive(a) {
            if (!a || !els.includes(a)) return;
            active = a;
            markActive(a);
        },
        setSuspended(el, on) {
            if (!el || !els.includes(el)) return;
            if (on) suspended.add(el); else suspended.delete(el);
        },
        get sharedTime() { return sharedTime; },
        get active() { return active; },
        get elements() { return els.slice(); },
    };
}

/**
 * "Preview mode" controller for a synced group of three players in the
 * order [original, processed, diff].
 *
 * In preview mode:
 *   - The Original element keeps its full-file source and is suspended
 *     from sync so the user can scrub to find problem spots.
 *   - Processed and Diff hold a small looped slice and stay sample-aligned
 *     with each other.
 *   - The cards for the looped pair get a dashed border so the loop state
 *     is visually obvious.
 *
 * `swapLoop({processed, diff})` replaces just the two slice URLs.
 */
export function makePreviewModeController(syncGroup) {
    const els = syncGroup.elements;
    const origEl = els[0];
    const procEl = els[1];
    const diffEl = els[2];

    function setLooping(on) {
        // Original never loops — it plays the full track.
        for (const a of [procEl, diffEl]) {
            if (!a) continue;
            a.loop = !!on;
            const card = a.closest('.results-card');
            if (card) card.classList.toggle('preview-mode', !!on);
        }
        // Original is suspended from sync while preview is on so that
        // scrubbing the full track doesn't reach into the loop pair.
        if (origEl) syncGroup.setSuspended(origEl, !!on);
    }

    async function swapLoop({processed, diff}, {autoplayActive = true} = {}) {
        const activeEl = syncGroup.active;
        const wasLoopPlaying =
            (procEl && !procEl.paused) || (diffEl && !diffEl.paused);
        const ready = [];
        for (const [el, url] of [[procEl, processed], [diffEl, diff]]) {
            if (!el || !url) continue;
            ready.push(new Promise((resolve) => {
                const onLoaded = () => {
                    el.removeEventListener('loadeddata', onLoaded);
                    resolve();
                };
                el.addEventListener('loadeddata', onLoaded, {once: true});
                setAudioSource(el, url);
            }));
        }
        await Promise.all(ready);

        for (const el of [procEl, diffEl]) {
            if (!el) continue;
            try { el.currentTime = 0; } catch (_) { /* ignore */ }
        }
        // Resume only if the loop pair was already playing AND the active
        // card is one of those two — otherwise the user is listening to
        // Original and we shouldn't auto-start the loop.
        if (autoplayActive && wasLoopPlaying &&
                (activeEl === procEl || activeEl === diffEl)) {
            try { await activeEl.play(); } catch (_) { /* user gesture */ }
        }
    }

    return { setLooping, swapLoop };
}
