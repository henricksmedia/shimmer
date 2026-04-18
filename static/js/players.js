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
        return { reset() {}, setActive() {} };
    }

    let sharedTime = 0;
    let active = els[0];
    let suppressSeek = false;

    const cardOf = (a) => a.closest('.results-card');

    const markActive = (a) => {
        for (const b of els) {
            const card = cardOf(b);
            if (card) card.classList.toggle('active', b === a);
        }
    };

    const seekOthers = (src, t) => {
        if (!Number.isFinite(t)) return;
        suppressSeek = true;
        try {
            for (const a of els) {
                if (a === src) continue;
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
            seekOthers(a, a.currentTime);
            active = a;
            markActive(a);
        });

        a.addEventListener('pause', () => {
            if (a === active) sharedTime = a.currentTime;
        });

        a.addEventListener('timeupdate', () => {
            if (a !== active) return;
            sharedTime = a.currentTime;
            seekOthers(a, sharedTime);
        });

        a.addEventListener('seeked', () => {
            if (suppressSeek) return;
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
    };
}
