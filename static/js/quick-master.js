// quick-master.js — the Master tab's Quick view: three choices, set for the
// song by Analyze (approved mockup, 2026-09-24).
//
// Quick and Advanced are two views of the same settings. Quick has no
// settings of its own: each slider writes into the controls Advanced has
// (the fix cards' Amounts, the Loudness target, the Tilt), and follows them
// when they change there. Quick hides controls; it never turns them off.
// What is on in Advanced but not shown here is listed in one line.
//
//   Clean-up   scales a base set of fix Amounts: Off 0x, Light 0.5x, the
//              middle 1x, Strong 1.5x (never past a card's 100 %). The base
//              is what Analyze recommends ("Recommended"), until the user
//              sets a card by hand in Advanced; then it is theirs ("Your
//              settings"), and "Use recommended" goes back.
//   Loudness   the Loudness target. Moving it turns mastering on.
//   Tone       the Tilt. Analyze marks Bright or Brighter when the top end
//              is dull (Lack of air), without moving it.

const MODE_KEY = 'shimmer.masterMode';
const CLEAN = [
    { label: 'Off', f: 0 },
    { label: 'Light', f: 0.5 },
    { label: 'Recommended', f: 1 },
    { label: 'Strong', f: 1.5 },
];
// The most Clean-up sets a fix to: its 100 %, which is under its damage
// limit, except Vocal grain, whose 100 % is "extra strong"; Quick stops at
// the author's "strong", 75 %. Advanced can still go further by hand.
const CAP = { grain: 75 };
const LOUD = ['streaming', 'loud', 'cd'];
const LOUD_NOTE = {
    streaming: 'Streaming services play it at this level already.',
    loud: 'A little quieter, with more punch left in.',
    cd: 'As loud as most released songs. The loudest hits are rounded off.',
};
const TONE = ['warmer', 'warm', 'neutral', 'bright', 'brightest'];
const TONE_LABEL = ['Warmer', 'Warm', 'Neutral', 'Bright', 'Brighter'];
const TONE_NOTE = [
    '2 dB more low end, 2 dB less top.',
    '1 dB more low end, 1 dB less top.',
    'The tone target only, no tilt.',
    '1 dB more top, 1 dB less low end.',
    '2 dB more top, 2 dB less low end.',
];

/**
 * picker        the fix cards (fault-picker.js): amounts(), setAmounts(), label()
 * masterEnabled, masterTarget, masterTilt   the Advanced controls
 * lufsOf(key)   a Loudness target's LUFS
 * advanced()    what is on in Advanced that Quick does not show: [text]
 * abMatched()   whether the A/B is loudness-matched
 * firstMove()   runs on the first slider move for a song (turns Live on)
 * showAnalysis()  opens the full analysis (Details)
 */
export function initQuickMaster({ picker, masterEnabled, masterTarget, masterTilt, lufsOf,
                                  advanced = () => [], abMatched = () => false,
                                  firstMove = () => {}, showAnalysis = () => {} }) {
    const $ = (id) => document.getElementById(id);
    const tab = $('tab-single');
    const panel = $('quick-master');
    const verdict = $('quick-verdict');
    if (!tab || !panel) return null;
    const clean = $('qm-clean'), loud = $('qm-loud'), tone = $('qm-tone');
    const quickBtn = $('mode-quick'), advBtn = $('mode-advanced');

    const state = {
        base: {},              // card -> % at 1x
        mine: false,           // the base is the user's (not Analyze's)
        recommended: {},       // what Analyze recommends, card -> %
        levels: {},            // card -> "some" / "a lot"
        found: [],             // the findings, for the verdict line
        toneRec: null,         // Tilt Analyze suggests, or null
        moved: false,          // a slider moved for this song
        loaded: false,
    };

    // ── Mode ─────────────────────────────────────────────────────────
    function readMode() {
        try { return localStorage.getItem(MODE_KEY) || 'quick'; } catch (_) { return 'quick'; }
    }
    function setMode(mode) {
        const quick = mode !== 'advanced';
        tab.classList.toggle('quick-mode', quick);
        panel.hidden = !quick;
        verdict.hidden = !quick || !state.loaded;
        quickBtn.classList.toggle('active', quick);
        advBtn.classList.toggle('active', !quick);
        quickBtn.setAttribute('aria-pressed', quick ? 'true' : 'false');
        advBtn.setAttribute('aria-pressed', quick ? 'false' : 'true');
        // The file chip lives in the left column, which Quick hides: it
        // moves to the top of the centre column and back.
        const slot = $('dropzone-slot');
        const left = $('master-col-left'), centre = $('master-col-center');
        if (slot && left && centre) {
            if (quick && slot.parentElement !== centre) centre.prepend(slot);
            if (!quick && slot.parentElement !== left) left.prepend(slot);
        }
        try { localStorage.setItem(MODE_KEY, quick ? 'quick' : 'advanced'); } catch (_) { /* per visit */ }
        render();
    }
    quickBtn.addEventListener('click', () => setMode('quick'));
    advBtn.addEventListener('click', () => setMode('advanced'));
    $('qm-advanced').addEventListener('click', () => setMode('advanced'));
    $('qv-details').addEventListener('click', () => { setMode('advanced'); showAnalysis(); });

    // ── Clean-up ─────────────────────────────────────────────────────
    function scaled(f) {
        const out = {};
        Object.entries(state.base).forEach(([k, pct]) => {
            out[k] = Math.min(CAP[k] || 100, Math.round(pct * f));
        });
        return out;
    }
    function cleanPos() {
        if (!Object.keys(state.base).length) return 2;
        const now = picker.amounts();
        for (let i = CLEAN.length - 1; i >= 0; i--) {
            const want = scaled(CLEAN[i].f);
            const same = Object.keys(want).every((k) => (now[k] || 0) === want[k]);
            if (same) return i;
        }
        return -1;          // set by hand to something else
    }
    function cleanNote(map) {
        const on = Object.entries(map).filter(([, v]) => v > 0);
        if (!state.loaded) return 'Load a song and Analyze sets this.';
        if (!Object.keys(state.base).length) {
            return state.mine ? 'No fix is on.' : 'Analyze found nothing to clean in this song.';
        }
        if (!on.length) return 'The song passes through as it is.';
        return on.map(([k, v]) => {
            const lvl = !state.mine && state.levels[k] ? ` (${state.levels[k]})` : '';
            return `${picker.label(k)} ${v}%${lvl}`;
        }).join(', ') + '.';
    }
    clean.addEventListener('input', () => {
        const pos = +clean.value;
        picker.setAmounts(scaled(CLEAN[pos].f), state.mine ? 'you' : 'Analyze');
        moved();
        render();
    });

    // ── Loudness and Tone: the Advanced controls, both ways ──────────
    loud.addEventListener('input', () => {
        if (!masterEnabled.checked) {
            masterEnabled.checked = true;
            masterEnabled.dispatchEvent(new Event('change'));
        }
        masterTarget.value = LOUD[+loud.value];
        masterTarget.dispatchEvent(new Event('change'));
        moved();
        render();
    });
    tone.addEventListener('input', () => {
        masterTilt.value = TONE[+tone.value];
        masterTilt.dispatchEvent(new Event('change'));
        moved();
        render();
    });
    [masterEnabled, masterTarget, masterTilt].forEach((el) => el.addEventListener('change', render));

    function moved() {
        if (state.moved || !state.loaded) return;
        state.moved = true;
        firstMove();
    }

    // ── Drawing ──────────────────────────────────────────────────────
    function render() {
        const map = picker.amounts();
        const pos = cleanPos();
        const mid = $('qm-clean-mid');
        mid.textContent = state.mine ? 'Your settings' : 'Recommended';
        if (pos >= 0) clean.value = pos;
        $('qm-clean-v').textContent = pos < 0 ? 'Custom' : (pos === 2 ? mid.textContent : CLEAN[pos].label);
        const note = $('qm-clean-note');
        note.textContent = cleanNote(pos >= 0 ? scaled(CLEAN[pos].f) : map);
        if (state.mine && Object.keys(state.recommended).length) {
            const back = document.createElement('button');
            back.type = 'button';
            back.className = 'qm-link';
            back.textContent = 'Use recommended';
            back.addEventListener('click', () => {
                state.base = { ...state.recommended };
                state.mine = false;
                const zero = {};
                Object.keys(map).forEach((k) => { if (!(k in state.base)) zero[k] = 0; });
                picker.setAmounts({ ...zero, ...state.base }, 'Analyze');
                render();
            });
            note.append(' ', back);
        }

        const on = masterEnabled.checked;
        const li = Math.max(0, LOUD.indexOf(masterTarget.value));
        loud.value = li;
        const lufs = lufsOf(LOUD[li]);
        $('qm-loud-v').textContent = on ? `${lufs != null ? String(lufs).replace('-', '−') : ''} LUFS` : 'Off';
        $('qm-loud-note').textContent = !on
            ? 'Mastering is off. Move the slider to turn it on.'
            : LOUD_NOTE[LOUD[li]] + (abMatched()
                ? ' A/B is level-matched, so you won’t hear this as louder.' : '');

        const ti = Math.max(0, TONE.indexOf(masterTilt.value));
        tone.value = ti;
        $('qm-tone-v').textContent = TONE_LABEL[ti];
        const ticks = $('qm-tone-ticks').children;
        const rec = state.toneRec ? TONE.indexOf(state.toneRec) : -1;
        [...ticks].forEach((t, i) => t.classList.toggle('rec', i === rec));
        const air = state.found.find((f) => f.card === 'air');
        $('qm-tone-note').textContent = TONE_NOTE[ti] + (air && rec >= 0 && rec !== ti
            ? ` Analyze: the top end is ${air.value.toFixed(1)} dB dull; ${TONE_LABEL[rec]} is marked.` : '');

        const also = advanced();
        const alsoEl = $('qm-also');
        alsoEl.hidden = !also.length;
        alsoEl.innerHTML = also.length ? `<b>Also on from Advanced:</b> ${also.join(' · ')}` : '';

        $('qm-sub').textContent = !state.loaded ? 'load a song to start'
            : state.mine ? 'your settings, from Advanced' : 'set for this song by Analyze';
        renderVerdict();
    }

    const SHORT = {
        tones: (l) => `${l.length} fixed tone${l.length === 1 ? '' : 's'}`,
        loudness: (l) => `${l[0].value.toFixed(1)} dB quieter than the target`,
        air: (l) => `a dull top end (${l[0].level})`,
        mud: (l) => `low-mid build-up (${l[0].level})`,
        grain: (l) => `vocal grain (${l[0].level})`,
        sibilance: (l) => `sibilance (${l[0].level})`,
        harshness: (l) => `harshness (${l[0].level})`,
    };
    function renderVerdict() {
        verdict.hidden = tab.classList.contains('quick-mode') ? !state.loaded : true;
        const groups = new Map();
        state.found.forEach((f) => {
            if (!groups.has(f.card)) groups.set(f.card, []);
            groups.get(f.card).push(f);
        });
        const parts = [...groups].filter(([k]) => SHORT[k]).map(([k, l]) => SHORT[k](l));
        $('qv-title').textContent = parts.length
            ? `Analyze found ${parts.length} thing${parts.length === 1 ? '' : 's'}`
            : 'Analyze found nothing to fix';
        $('qv-text').textContent = parts.join(' · ');
    }

    // ── From the rest of the tab ─────────────────────────────────────
    return {
        /** A new song: start at Recommended, with nothing moved yet. */
        newSong() {
            state.base = {};
            state.recommended = {};
            state.levels = {};
            state.found = [];
            state.toneRec = null;
            state.mine = false;
            state.moved = false;
            state.loaded = true;
            render();
        },
        /** Findings from the upload, the slow detectors or Analyze. The
         *  cards are already set by them (fault-picker setFindings). */
        setFindings(findings) {
            state.found = findings || [];
            const rec = {};
            const levels = {};
            state.found.forEach((f) => {
                if (f.amount != null) rec[f.card] = Math.max(rec[f.card] || 0, Math.round(f.amount * 100));
                if (f.level) levels[f.card] = f.level;
            });
            state.recommended = rec;
            state.levels = levels;
            const air = state.found.find((f) => f.card === 'air');
            state.toneRec = air ? (air.level === 'a lot' ? 'brightest' : 'bright') : null;
            if (!state.mine) state.base = { ...rec };
            render();
        },
        /** The user set a card by hand in Advanced: it becomes the base. */
        userEdit() {
            state.base = picker.amounts();
            state.mine = true;
            render();
        },
        render,
        mode: () => (tab.classList.contains('quick-mode') ? 'quick' : 'advanced'),
        start() { setMode(readMode()); },
    };
}
