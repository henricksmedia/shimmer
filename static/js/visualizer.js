// visualizer.js — Unified player: one canvas (waveform / spectrogram), one
// transport, instant Original / Processed / Removed switching, live spectrum
// + level meter while playing.
//
// The three <audio> elements stay in the DOM (hidden) — the player keeps a
// single shared playhead and swaps which element is audible.

const TRACK_KEYS = ['original', 'processed', 'removed'];

// Audition boost for the Removed track during preview (≈5x). Applied as
// a client-side gain, capped against the slice's own peak so it never
// clips the output.
const REMOVED_BOOST_DB = 14;

// ── Live analyzer calibration ───────────────────────────────────────
// AnalyserNode magnitudes are Blackman-windowed and scaled by 1/N, so a
// full-scale sine reads about -13.6 dB. Add that back so the dB grid is
// in dBFS for sines, the convention most analyzers use.
const SPEC_CAL_DB = 13.6;
// Music falls off at roughly 4.5 dB per octave. Tilting the display by
// that much around 1 kHz makes a normal mix read close to flat, so the
// top end (where the artifacts live) is not crushed into the corner.
const SPEC_TILT_DB_PER_OCT = 4.5;
const SPEC_DB_TOP = 0;
const SPEC_DB_BOTTOM = -84;
const SPEC_GRID_STEP_DB = 12;
// Ghost trace smoothing: per-frame EMA of the other A/B track's spectrum.
const GHOST_EMA = 0.12;

// ── Loudness strip (ITU-R BS.1770 K-weighting) ──────────────────────
// The strip fills with momentary loudness (400 ms) in LUFS, on the same
// scale as its target marker. Filter design follows the standard's
// analog prototypes so it holds at any sample rate (as in libebur128).
const LUFS_STRIP_MIN = -40;
const LUFS_STRIP_MAX = 0;
const LUFS_MOMENTARY_S = 0.4;

function kWeightingCoefficients(fs) {
    // Stage 1: high shelf, +4 dB above ~1.5 kHz.
    const f0 = 1681.974450955533, G = 3.999843853973347, Q = 0.7071752369554196;
    const K = Math.tan(Math.PI * f0 / fs);
    const Vh = Math.pow(10, G / 20);
    const Vb = Math.pow(Vh, 0.4996667741545416);
    const a0 = 1 + K / Q + K * K;
    const shelf = {
        feedforward: [(Vh + Vb * K / Q + K * K) / a0,
                      2 * (K * K - Vh) / a0,
                      (Vh - Vb * K / Q + K * K) / a0],
        feedback:    [1, 2 * (K * K - 1) / a0, (1 - K / Q + K * K) / a0],
    };
    // Stage 2: high-pass at ~38 Hz (the "RLB" weighting).
    const f1 = 38.13547087602444, Q1 = 0.5003270373238773;
    const K1 = Math.tan(Math.PI * f1 / fs);
    const d0 = 1 + K1 / Q1 + K1 * K1;
    const hp = {
        feedforward: [1, -2, 1],
        feedback:    [1, 2 * (K1 * K1 - 1) / d0, (1 - K1 / Q1 + K1 * K1) / d0],
    };
    return { shelf, hp };
}

// ── Colors (match tokens.css) ───────────────────────────────────────
const C = {
    waveTop: 'rgba(139, 149, 163, 0.40)',
    waveRms: 'rgba(139, 149, 163, 0.95)',
    // Overlay mode: waveform drawn on top of the spectrogram, so it
    // reads as a light translucent trace instead of solid color.
    overlayTop: 'rgba(255, 255, 255, 0.22)',
    overlayRms: 'rgba(255, 255, 255, 0.38)',
    waveBg: '#0c0f13',
    playhead: 'rgba(255, 255, 255, 0.9)',
    loopFill: 'rgba(245, 165, 36, 0.12)',
    loopEdge: 'rgba(245, 165, 36, 0.7)',
    bandFill: 'rgba(56, 189, 248, 0.08)',
    bandEdge: 'rgba(56, 189, 248, 0.35)',
    specBar: 'rgba(56, 189, 248, 0.85)',
};

// Per-track waveform colors: A/B state readable at a glance
// (original neutral, processed amber, removed red).
const TRACK_WAVE = {
    original:  { top: 'rgba(139, 149, 163, 0.40)', rms: 'rgba(139, 149, 163, 0.95)' },
    processed: { top: 'rgba(245, 165, 36, 0.38)',  rms: 'rgba(245, 165, 36, 0.92)'  },
    removed:   { top: 'rgba(240, 82, 107, 0.40)',  rms: 'rgba(240, 82, 107, 0.92)'  },
};

export function fmtTime(t) {
    if (!Number.isFinite(t) || t < 0) return '0:00';
    const m = Math.floor(t / 60);
    const s = Math.floor(t % 60);
    return `${m}:${s.toString().padStart(2, '0')}`;
}

// ── Radix-2 iterative FFT (in-place) ────────────────────────────────
function fftInPlace(re, im) {
    const n = re.length;
    for (let i = 1, j = 0; i < n; i++) {
        let bit = n >> 1;
        for (; j & bit; bit >>= 1) j ^= bit;
        j ^= bit;
        if (i < j) {
            const tr = re[i]; re[i] = re[j]; re[j] = tr;
            const ti = im[i]; im[i] = im[j]; im[j] = ti;
        }
    }
    for (let len = 2; len <= n; len <<= 1) {
        const ang = -2 * Math.PI / len;
        const wr = Math.cos(ang), wi = Math.sin(ang);
        const half = len >> 1;
        for (let i = 0; i < n; i += len) {
            let cr = 1, ci = 0;
            for (let k = 0; k < half; k++) {
                const ar = re[i + k], ai = im[i + k];
                const br = re[i + k + half], bi = im[i + k + half];
                const vr = br * cr - bi * ci;
                const vi = br * ci + bi * cr;
                re[i + k] = ar + vr; im[i + k] = ai + vi;
                re[i + k + half] = ar - vr; im[i + k + half] = ai - vi;
                const nr = cr * wr - ci * wi;
                ci = cr * wi + ci * wr;
                cr = nr;
            }
        }
    }
}

// Inferno-ish colormap: t in [0,1] -> [r,g,b]
function heat(t) {
    t = Math.max(0, Math.min(1, t));
    if (t < 0.25) {
        const u = t / 0.25;
        return [10 + 40 * u, 8 + 10 * u, 30 + 70 * u];
    } else if (t < 0.55) {
        const u = (t - 0.25) / 0.3;
        return [50 + 110 * u, 18 + 30 * u, 100 + 10 * u];
    } else if (t < 0.8) {
        const u = (t - 0.55) / 0.25;
        return [160 + 80 * u, 48 + 100 * u, 110 - 70 * u];
    }
    const u = (t - 0.8) / 0.2;
    return [240 + 15 * u, 148 + 90 * u, 40 + 160 * u];
}

// ── Display mixdown ─────────────────────────────────────────────────
// The display (peaks + spectrogram) uses an average of all channels so
// right-channel-only content is never invisible. Cached per buffer —
// renderBase re-runs on every resize/track switch.
const mixdownCache = new WeakMap();
function displayData(buffer) {
    if (buffer.numberOfChannels === 1) return buffer.getChannelData(0);
    let mix = mixdownCache.get(buffer);
    if (mix) return mix;
    mix = new Float32Array(buffer.length);
    mix.set(buffer.getChannelData(0));
    for (let ch = 1; ch < buffer.numberOfChannels; ch++) {
        const d = buffer.getChannelData(ch);
        for (let i = 0; i < mix.length; i++) mix[i] += d[i];
    }
    const inv = 1 / buffer.numberOfChannels;
    for (let i = 0; i < mix.length; i++) mix[i] *= inv;
    mixdownCache.set(buffer, mix);
    return mix;
}

// ── Peak computation ────────────────────────────────────────────────
function computePeaks(buffer, width) {
    const data = displayData(buffer);
    const n = data.length;
    const min = new Float32Array(width);
    const max = new Float32Array(width);
    const rms = new Float32Array(width);
    const step = n / width;
    for (let x = 0; x < width; x++) {
        const i0 = Math.floor(x * step);
        const i1 = Math.min(n, Math.floor((x + 1) * step) + 1);
        let mn = 1e9, mx = -1e9, acc = 0, cnt = 0;
        for (let i = i0; i < i1; i++) {
            const v = data[i];
            if (v < mn) mn = v;
            if (v > mx) mx = v;
            acc += v * v;
            cnt++;
        }
        min[x] = cnt ? mn : 0;
        max[x] = cnt ? mx : 0;
        rms[x] = cnt ? Math.sqrt(acc / cnt) : 0;
    }
    return { min, max, rms };
}

// ── Spectrogram (real STFT, log-frequency, rendered offscreen once) ─
function computeSpectrogram(buffer, widthPx, heightPx) {
    const data = displayData(buffer);
    const sr = buffer.sampleRate;
    const nFft = 1024;
    const bins = nFft / 2;
    const targetCols = Math.min(1600, Math.max(200, widthPx));
    const hop = Math.max(256, Math.floor((data.length - nFft) / targetCols));
    const cols = Math.max(1, Math.floor((data.length - nFft) / hop));
    const rows = Math.min(320, heightPx);

    // Hann window
    const win = new Float32Array(nFft);
    for (let i = 0; i < nFft; i++) {
        win[i] = 0.5 - 0.5 * Math.cos((2 * Math.PI * i) / nFft);
    }

    // Log-frequency row -> bin lookup (fmin 40 Hz .. Nyquist)
    const fMin = 40;
    const fMax = sr / 2;
    const rowBin = new Uint16Array(rows);
    for (let y = 0; y < rows; y++) {
        const frac = 1 - y / (rows - 1);           // top = high freq
        const f = fMin * Math.pow(fMax / fMin, frac);
        rowBin[y] = Math.min(bins - 1, Math.round((f / fMax) * (bins - 1)));
    }

    const mags = new Float32Array(cols * rows);
    const re = new Float32Array(nFft);
    const im = new Float32Array(nFft);
    let dbMax = -Infinity;

    for (let c = 0; c < cols; c++) {
        const s0 = c * hop;
        for (let i = 0; i < nFft; i++) {
            re[i] = (data[s0 + i] || 0) * win[i];
            im[i] = 0;
        }
        fftInPlace(re, im);
        for (let y = 0; y < rows; y++) {
            const b = rowBin[y];
            const m = Math.sqrt(re[b] * re[b] + im[b] * im[b]);
            const db = 20 * Math.log10(m + 1e-9);
            mags[c * rows + y] = db;
            if (db > dbMax) dbMax = db;
        }
    }

    const dbFloor = dbMax - 72;
    const off = document.createElement('canvas');
    off.width = cols;
    off.height = rows;
    const ctx = off.getContext('2d');
    const img = ctx.createImageData(cols, rows);
    for (let c = 0; c < cols; c++) {
        for (let y = 0; y < rows; y++) {
            const db = mags[c * rows + y];
            const t = (db - dbFloor) / (dbMax - dbFloor);
            const [r, g, b] = heat(t);
            const idx = (y * cols + c) * 4;
            img.data[idx] = r;
            img.data[idx + 1] = g;
            img.data[idx + 2] = b;
            img.data[idx + 3] = 255;
        }
    }
    ctx.putImageData(img, 0, 0);
    // Frequency helpers for band overlay (log scale y position of f)
    const yOfFreq = (f) => {
        const frac = Math.log(Math.max(fMin, Math.min(fMax, f)) / fMin) /
                     Math.log(fMax / fMin);
        return (1 - frac); // 0 (top) .. 1 (bottom) normalized
    };
    return { canvas: off, yOfFreq };
}

// ── Unified player ──────────────────────────────────────────────────
export function createUnifiedPlayer({
    els,                 // {original, processed, removed} <audio> elements
    canvas,              // main display canvas
    playBtn,
    timeLabel,
    tabsHost,            // container with [data-track] buttons
    modeWaveBtn,
    modeOverlayBtn,
    modeSpecBtn,
    spectrumCanvas,      // live spectrum canvas (while playing)
    metersHost,          // wrapper for live meters (hidden when idle)
    lufsFillEl,
    lufsTargetEl,
    getShimmerBand = () => ({ lo: 5100, hi: 7200 }),
    onTimeUpdate = null,
}) {
    const state = {
        active: 'original',
        mode: 'waveform',
        loop: null,             // {start, end} in full-timeline seconds
        preview: false,
        previewAnchor: 0,
        available: { original: false, processed: false, removed: false },
        matchEnabled: false,
        gainDb: { original: 0, processed: 0, removed: 0 },
        targetLufs: null,       // set from the chosen Loudness target (/api/rules)
        rafId: null,
    };

    const buffers = new Map();      // key -> AudioBuffer
    const baseLayer = document.createElement('canvas');
    let baseValid = false;
    let specData = null;            // {canvas, yOfFreq} for current base
    let audioCtx = null;
    let analyser = null;
    let meterIn = null;             // everything audible fans out from here
    let kAnalysers = null;          // per-channel K-weighted time-domain taps
    // Loudness strip state: recent (time, mean-square) pairs for the
    // 400 ms momentary window.
    const loud = { window: [] };
    // Ghost traces: smoothed display-dB spectrum per track, so the other
    // A/B track can be drawn behind the live one.
    const ghost = { original: null, processed: null, removed: null };
    const sourceNodes = new WeakMap();  // <audio> -> MediaElementSourceNode
    const elementGains = new WeakMap(); // <audio> -> GainNode (level control)

    // Preview loop engine: three AudioBufferSourceNodes started on the
    // same clock, one persistent GainNode per track. Track switching is
    // a gain crossfade — gapless and sample-aligned.
    const prev = {
        buffers: { processed: null, removed: null },  // slice AudioBuffers
        sources: null,          // {key: AudioBufferSourceNode} while playing
        gains: null,            // {key: GainNode}, created once
        playing: false,
        phase: 0,               // seconds into the loop when paused
        startCtxTime: 0,        // ctx.currentTime at loop phase 0
        loopLen: 0,
        removedBoostDb: REMOVED_BOOST_DB,  // capped per-slice
    };

    const tabBtns = new Map();
    if (tabsHost) {
        for (const btn of tabsHost.querySelectorAll('[data-track]')) {
            tabBtns.set(btn.dataset.track, btn);
            btn.addEventListener('click', () => setTrack(btn.dataset.track));
        }
    }

    // ── Web Audio (live meters) ─────────────────────────────────────
    function ensureCtx() {
        if (!audioCtx) {
            audioCtx = new (window.AudioContext || window.webkitAudioContext)();
            // meterIn -> analyser -> speakers (spectrum, mono downmix)
            // meterIn -> splitter -> K-weighting -> per-channel taps
            meterIn = audioCtx.createGain();
            analyser = audioCtx.createAnalyser();
            analyser.fftSize = 2048;
            analyser.smoothingTimeConstant = 0.7;
            meterIn.connect(analyser);
            analyser.connect(audioCtx.destination);
            try {
                const { shelf, hp } = kWeightingCoefficients(audioCtx.sampleRate);
                const splitter = audioCtx.createChannelSplitter(2);
                meterIn.connect(splitter);
                kAnalysers = [];
                for (let ch = 0; ch < 2; ch++) {
                    const s = new IIRFilterNode(audioCtx, shelf);
                    const h = new IIRFilterNode(audioCtx, hp);
                    const tap = audioCtx.createAnalyser();
                    tap.fftSize = 2048;
                    splitter.connect(s, ch);
                    s.connect(h);
                    h.connect(tap);
                    kAnalysers.push(tap);
                }
            } catch (_) {
                kAnalysers = null;   // very old browser: strip stays empty
            }
        }
        return audioCtx;
    }

    function routeThroughAnalyser(el) {
        const ctx = ensureCtx();
        if (!sourceNodes.has(el)) {
            try {
                const src = ctx.createMediaElementSource(el);
                const gain = ctx.createGain();
                src.connect(gain);
                gain.connect(meterIn);
                sourceNodes.set(el, src);
                elementGains.set(el, gain);
            } catch (_) { /* already connected elsewhere */ }
        }
        if (ctx.state === 'suspended') ctx.resume().catch(() => {});
    }

    // ── Time mapping (full timeline <-> element / loop time) ────────
    const activeEl = () => els[state.active];

    function previewPhase() {
        if (!state.preview) return 0;
        if (!prev.playing || !audioCtx || prev.loopLen <= 0) return prev.phase;
        const t = audioCtx.currentTime - prev.startCtxTime;
        return ((t % prev.loopLen) + prev.loopLen) % prev.loopLen;
    }

    function getTime() {
        if (state.preview) {
            const start = state.loop ? state.loop.start : state.previewAnchor;
            return start + previewPhase();
        }
        const el = activeEl();
        return Number(el.currentTime) || 0;
    }

    function totalDuration() {
        const orig = els.original;
        if (Number.isFinite(orig.duration) && orig.duration > 0) return orig.duration;
        const buf = buffers.get('original');
        return buf ? buf.duration : 0;
    }

    function seekFullTime(t) {
        if (state.preview && state.loop) {
            const phase = Math.max(0, Math.min(
                prev.loopLen || (state.loop.end - state.loop.start),
                t - state.loop.start));
            if (prev.playing) {
                previewStartSources(phase);
            } else {
                prev.phase = phase;
            }
            return;
        }
        const el = activeEl();
        const dur = Number.isFinite(el.duration) ? el.duration : totalDuration();
        el.currentTime = Math.max(0, Math.min(dur || 0, t));
    }

    // ── Levels (loudness-matched A/B + removed audition boost) ──────
    // Total per-track gain in dB. Removed is excluded from matching and
    // always carries the monitoring boost — server files and preview
    // slices both ship UNBOOSTED so the boost is never baked into
    // anything the user exports. Preview caps the boost against the
    // slice's own peak; the full-run path uses the nominal boost.
    function trackGainDb(key) {
        if (key === 'removed') {
            return state.preview ? prev.removedBoostDb : REMOVED_BOOST_DB;
        }
        return state.matchEnabled ? (state.gainDb[key] || 0) : 0;
    }

    function applyVolume() {
        for (const key of TRACK_KEYS) {
            const el = els[key];
            if (!el) continue;
            el.volume = 1;
            const gain = elementGains.get(el);
            if (gain) gain.gain.value = Math.pow(10, trackGainDb(key) / 20);
        }
        applyPreviewGains();
    }

    // ── Preview loop engine ─────────────────────────────────────────
    function previewEnsureGains() {
        ensureCtx();
        if (prev.gains) return;
        prev.gains = {};
        for (const key of TRACK_KEYS) {
            const g = audioCtx.createGain();
            g.gain.value = 0;
            g.connect(meterIn);
            prev.gains[key] = g;
        }
    }

    // Crossfade the per-track loop gains to their targets. Only the
    // active track is audible; ~15 ms ramps keep switches click-free.
    function applyPreviewGains(fromT = null, forceZeroStart = false) {
        if (!prev.gains || !audioCtx) return;
        const t0 = fromT != null ? fromT : audioCtx.currentTime;
        for (const key of TRACK_KEYS) {
            const g = prev.gains[key];
            if (!g) continue;
            const audible = state.preview && key === state.active ? 1 : 0;
            const target = audible * Math.pow(10, trackGainDb(key) / 20);
            g.gain.cancelScheduledValues(t0);
            if (forceZeroStart) g.gain.setValueAtTime(0, t0);
            g.gain.setTargetAtTime(target, t0, 0.006);
        }
    }

    function previewStopSources(fadeS = 0.015) {
        if (!prev.sources) return;
        const now = audioCtx ? audioCtx.currentTime : 0;
        for (const key of TRACK_KEYS) {
            const g = prev.gains && prev.gains[key];
            if (g) {
                g.gain.cancelScheduledValues(now);
                g.gain.setTargetAtTime(0, now, fadeS / 3);
            }
            const s = prev.sources[key];
            if (s) {
                try { s.stop(now + fadeS); } catch (_) { /* not started */ }
                try { s.onended = null; } catch (_) {}
            }
        }
        prev.sources = null;
    }

    // (Re)start all loop sources sample-aligned at the given phase.
    // Old sources fade out, new ones fade in ~30 ms later, so buffer
    // swaps from fresh renders land without clicks.
    function previewStartSources(phase = 0) {
        if (!state.loop) return;
        previewEnsureGains();
        if (audioCtx.state === 'suspended') audioCtx.resume().catch(() => {});
        previewStopSources();

        const start = state.loop.start;
        const loopLen = Math.max(0.05, state.loop.end - state.loop.start);
        prev.loopLen = loopLen;
        phase = Math.max(0, Math.min(loopLen - 0.001, phase));

        const at = audioCtx.currentTime + 0.03;
        prev.sources = {};

        // Original loops a window of its full decoded buffer.
        const origBuf = buffers.get('original');
        if (origBuf) {
            const s = audioCtx.createBufferSource();
            s.buffer = origBuf;
            s.loop = true;
            s.loopStart = Math.min(start, Math.max(0, origBuf.duration - 0.05));
            s.loopEnd = Math.min(start + loopLen, origBuf.duration);
            s.connect(prev.gains.original);
            s.start(at, Math.min(start + phase, Math.max(0, origBuf.duration - 0.01)));
            prev.sources.original = s;
        }
        // Processed / removed are slice buffers: loop the whole buffer.
        for (const key of ['processed', 'removed']) {
            const buf = prev.buffers[key];
            if (!buf) continue;
            const s = audioCtx.createBufferSource();
            s.buffer = buf;
            s.loop = true;
            s.loopStart = 0;
            s.loopEnd = Math.min(loopLen, buf.duration);
            s.connect(prev.gains[key]);
            s.start(at, Math.min(phase, Math.max(0, buf.duration - 0.01)));
            prev.sources[key] = s;
        }

        prev.startCtxTime = at - phase;
        prev.playing = true;
        applyPreviewGains(at, true);
        kickLoop();
    }

    function previewPause() {
        if (!prev.playing) return;
        prev.phase = previewPhase();
        previewStopSources();
        prev.playing = false;
    }

    // ── Transport ───────────────────────────────────────────────────
    function isPlaying() {
        if (state.preview) return prev.playing;
        const el = activeEl();
        return el && !el.paused && !el.ended;
    }

    async function play() {
        if (state.preview) {
            if (!prev.playing) previewStartSources(prev.phase);
            updatePlayBtn();
            return;
        }
        const el = activeEl();
        if (!el || !el.src) return;
        routeThroughAnalyser(el);
        applyVolume();
        try { await el.play(); } catch (_) { /* needs gesture */ }
    }

    function pause() {
        if (state.preview) {
            previewPause();
            updatePlayBtn();
            drawFrame();
            return;
        }
        const el = activeEl();
        if (el) el.pause();
    }

    function toggle() {
        if (isPlaying()) pause(); else play();
    }

    function setTrack(key) {
        if (!TRACK_KEYS.includes(key) || !state.available[key]) return;
        if (key === state.active) return;
        if (state.preview) {
            // Loop sources share one clock: switching is a crossfade,
            // no pause, no seek, no gap.
            state.active = key;
            applyPreviewGains();
            updateTabs();
            // The base layer is colored by state.active; without this the
            // cached layer keeps the prior track's color while Live is on,
            // so the waveform wouldn't recolor on tab switch.
            invalidateBase();
            drawFrame();
            return;
        }
        const wasPlaying = isPlaying();
        const t = getTime();
        pause();
        state.active = key;
        seekFullTime(t);
        updateTabs();
        invalidateBase();
        if (wasPlaying) play();
        drawFrame();
    }

    function updateTabs() {
        for (const [key, btn] of tabBtns) {
            const avail = !!state.available[key];
            btn.classList.toggle('active', key === state.active);
            // aria-disabled (not the `disabled` attribute) keeps the button
            // hoverable so its tooltip can explain how to enable the track;
            // setTrack ignores clicks on unavailable tracks either way.
            btn.setAttribute('aria-disabled', String(!avail));
            const ready = btn.dataset.titleReady;
            if (ready) btn.title = avail ? ready : (btn.dataset.titleDisabled || ready);
        }
    }

    function updatePlayBtn() {
        if (!playBtn) return;
        playBtn.textContent = isPlaying() ? '⏸' : '▶';
        playBtn.setAttribute('aria-label', isPlaying() ? 'Pause' : 'Play');
    }

    function updateTimeLabel() {
        const t = getTime();
        const d = totalDuration();
        if (timeLabel) timeLabel.textContent = `${fmtTime(t)} / ${fmtTime(d)}`;
        // Transport scrubber and anything else that follows the playhead.
        if (onTimeUpdate) onTimeUpdate(t, d, state.loop);
    }

    // ── Sources & buffers ───────────────────────────────────────────
    async function decode(url, key) {
        try {
            const res = await fetch(url);
            const ab = await res.arrayBuffer();
            const ctx = ensureCtx();
            const buf = await ctx.decodeAudioData(ab);
            buffers.set(key, buf);
            if (key === state.active || state.preview) {
                invalidateBase();
                drawFrame();
            }
            // If a preview loop started before the original finished
            // decoding, restart so the original source joins the clock.
            if (key === 'original' && state.preview && prev.playing &&
                prev.sources && !prev.sources.original) {
                previewStartSources(previewPhase());
            }
        } catch (_) { /* non-fatal: canvas stays empty for this track */ }
    }

    function setSource(key, url, { decodeBuffer = true } = {}) {
        const el = els[key];
        if (!el) return;
        // New audio: forget the ghost spectrum for it (and, for a new
        // upload, for every track).
        ghost[key] = null;
        if (key === 'original') { ghost.processed = null; ghost.removed = null; }
        if (!url) {
            el.removeAttribute('src');
            el.load();
            state.available[key] = false;
            buffers.delete(key);
            updateTabs();
            return;
        }
        const bust = url.startsWith('blob:') ? url
            : `${url}${url.includes('?') ? '&' : '?'}_=${Date.now()}`;
        el.src = bust;
        el.loop = false;
        el.load();
        state.available[key] = true;
        buffers.delete(key);
        updateTabs();
        if (decodeBuffer) decode(bust, key);
    }

    // Decode raw WAV bytes on the shared context (used by the preview
    // render cache so each render is decoded exactly once).
    async function decodeAudio(arrayBuffer) {
        const ctx = ensureCtx();
        return ctx.decodeAudioData(arrayBuffer.slice(0));
    }

    function bufferPeak(buf) {
        let peak = 0;
        for (let ch = 0; ch < buf.numberOfChannels; ch++) {
            const d = buf.getChannelData(ch);
            for (let i = 0; i < d.length; i++) {
                const v = Math.abs(d[i]);
                if (v > peak) peak = v;
            }
        }
        return peak;
    }

    // Preview render arrived: install decoded slice buffers for the
    // loop window. If the loop is already running, the swap happens
    // as a ~30 ms crossfaded source restart at the same phase.
    function setPreviewBuffers({ processedBuf, removedBuf, startS, endS }) {
        const wasElementPlaying = !state.preview && isPlaying();
        const sameWindow = state.preview && state.loop &&
            Math.abs(state.loop.start - startS) < 1e-6 &&
            Math.abs(state.loop.end - endS) < 1e-6;
        const phase = sameWindow ? previewPhase() : 0;

        // Entering preview: silence any full-track element playback.
        for (const key of TRACK_KEYS) {
            const el = els[key];
            if (el && !el.paused) el.pause();
        }

        state.preview = true;
        state.previewAnchor = startS;
        state.loop = { start: startS, end: endS };
        prev.buffers.processed = processedBuf || null;
        prev.buffers.removed = removedBuf || null;
        state.available.processed = !!processedBuf;
        state.available.removed = !!removedBuf;

        // Cap the removed audition boost against the slice's own peak
        // so the boost can never clip the output.
        if (removedBuf) {
            const peak = Math.max(bufferPeak(removedBuf), 1e-6);
            prev.removedBoostDb = Math.min(
                REMOVED_BOOST_DB, 20 * Math.log10(0.98 / peak));
        } else {
            prev.removedBoostDb = REMOVED_BOOST_DB;
        }

        updateTabs();
        invalidateBase();
        drawFrame();
        if (prev.playing || wasElementPlaying) {
            previewStartSources(phase);
        } else {
            prev.phase = phase;
        }
        updatePlayBtn();
    }

    function exitPreview() {
        previewStopSources();
        prev.playing = false;
        prev.phase = 0;
        prev.buffers.processed = null;
        prev.buffers.removed = null;
        prev.removedBoostDb = REMOVED_BOOST_DB;
        state.preview = false;
        state.loop = null;
        for (const key of ['processed', 'removed']) {
            const el = els[key];
            if (el) el.loop = false;
            state.available[key] = !!(el && el.getAttribute('src'));
        }
        if (!state.available[state.active]) state.active = 'original';
        updateTabs();
        invalidateBase();
        drawFrame();
        updatePlayBtn();
    }

    async function loadFromJob(jobId) {
        exitPreview();
        setSource('processed', `/api/result/${jobId}?kind=processed`);
        setSource('removed', `/api/result/${jobId}?kind=diff`);
        updateTabs();
    }

    // ── Canvas rendering ────────────────────────────────────────────
    function cssSize() {
        const rect = canvas.getBoundingClientRect();
        return { w: Math.max(50, rect.width), h: Math.max(40, rect.height) };
    }

    function syncCanvasSize() {
        const dpr = window.devicePixelRatio || 1;
        const { w, h } = cssSize();
        const pw = Math.round(w * dpr);
        const ph = Math.round(h * dpr);
        if (canvas.width !== pw || canvas.height !== ph) {
            canvas.width = pw;
            canvas.height = ph;
            invalidateBase();
        }
    }

    function invalidateBase() {
        baseValid = false;
    }

    // The base layer shows the buffer for the DISPLAY track: in preview
    // mode we always display the Original full-track buffer (with the
    // loop window shaded); otherwise the active track's buffer.
    function displayKey() {
        return state.preview ? 'original' : state.active;
    }

    function renderBase() {
        const w = canvas.width, h = canvas.height;
        baseLayer.width = w;
        baseLayer.height = h;
        const ctx = baseLayer.getContext('2d');
        ctx.fillStyle = C.waveBg;
        ctx.fillRect(0, 0, w, h);

        const buf = buffers.get(displayKey());
        if (!buf) { baseValid = true; specData = null; return; }

        const showSpec = state.mode === 'spectrogram' || state.mode === 'overlay';
        const showWave = state.mode === 'waveform' || state.mode === 'overlay';

        if (showSpec) {
            specData = computeSpectrogram(buf, Math.floor(w / 2), Math.floor(h / 2));
            ctx.imageSmoothingEnabled = true;
            ctx.drawImage(specData.canvas, 0, 0, w, h);
            // Shimmer band edge lines
            const band = getShimmerBand();
            ctx.strokeStyle = C.bandEdge;
            ctx.setLineDash([6, 5]);
            ctx.lineWidth = 1;
            for (const f of [band.lo, band.hi]) {
                const y = specData.yOfFreq(f) * h;
                ctx.beginPath();
                ctx.moveTo(0, y);
                ctx.lineTo(w, y);
                ctx.stroke();
            }
            ctx.setLineDash([]);
        } else {
            specData = null;
        }

        if (showWave) {
            const overlay = state.mode === 'overlay';
            const tc = TRACK_WAVE[state.active] || TRACK_WAVE.original;
            const peaks = computePeaks(buf, w);
            const mid = h / 2;
            // min/max peak fill
            ctx.fillStyle = overlay ? C.overlayTop : tc.top;
            for (let x = 0; x < w; x++) {
                const y1 = mid - peaks.max[x] * mid;
                const y2 = mid - peaks.min[x] * mid;
                ctx.fillRect(x, Math.min(y1, y2), 1, Math.max(1, Math.abs(y2 - y1)));
            }
            // RMS body overlay
            ctx.fillStyle = overlay ? C.overlayRms : tc.rms;
            for (let x = 0; x < w; x++) {
                const r = peaks.rms[x] * mid;
                ctx.fillRect(x, mid - r, 1, Math.max(1, r * 2));
            }
        }
        baseValid = true;
    }

    function drawFrame() {
        syncCanvasSize();
        if (!baseValid) renderBase();
        const ctx = canvas.getContext('2d');
        const w = canvas.width, h = canvas.height;
        ctx.drawImage(baseLayer, 0, 0);

        const dur = totalDuration();

        // Loop window overlay (live preview)
        if (state.loop && dur > 0) {
            const x0 = (state.loop.start / dur) * w;
            const x1 = (state.loop.end / dur) * w;
            ctx.fillStyle = C.loopFill;
            ctx.fillRect(x0, 0, x1 - x0, h);
            ctx.strokeStyle = C.loopEdge;
            ctx.lineWidth = 1.5;
            for (const x of [x0, x1]) {
                ctx.beginPath();
                ctx.moveTo(x, 0);
                ctx.lineTo(x, h);
                ctx.stroke();
            }
        }

        // Playhead
        if (dur > 0) {
            const px = (getTime() / dur) * w;
            ctx.strokeStyle = C.playhead;
            ctx.lineWidth = Math.max(1, (window.devicePixelRatio || 1));
            ctx.beginPath();
            ctx.moveTo(px, 0);
            ctx.lineTo(px, h);
            ctx.stroke();
        }
        updateTimeLabel();
    }

    // ── Live meters ─────────────────────────────────────────────────
    const freqDb = new Float32Array(1024);
    const timeData = new Float32Array(2048);
    let specCols = null;            // display spectrum, one value per 2 px

    function drawLiveMeters() {
        if (!analyser || !spectrumCanvas) return;
        const dpr = window.devicePixelRatio || 1;
        const rect = spectrumCanvas.getBoundingClientRect();
        const w = Math.round(rect.width * dpr);
        const h = Math.round(rect.height * dpr);
        if (spectrumCanvas.width !== w || spectrumCanvas.height !== h) {
            spectrumCanvas.width = w;
            spectrumCanvas.height = h;
        }
        const ctx = spectrumCanvas.getContext('2d');
        analyser.getFloatFrequencyData(freqDb);
        ctx.clearRect(0, 0, w, h);

        const sr = audioCtx ? audioCtx.sampleRate : 48000;
        const nyq = sr / 2;
        // Fixed axis (not Nyquist) so labels stay put across sample rates.
        const fMin = 40;
        const fMax = Math.min(20000, nyq);
        const nBins = analyser.frequencyBinCount;
        // Reserve a right-hand gutter for the dB labels and a bottom strip
        // for the frequency labels, so the trace never runs through text.
        const gutterR = 26 * dpr;
        const gutterB = 13 * dpr;
        const plotW = w - gutterR;
        const plotH = h - gutterB;

        const xOfFreq = (f) => {
            const frac = Math.log(Math.max(fMin, Math.min(fMax, f)) / fMin) /
                         Math.log(fMax / fMin);
            return frac * plotW;
        };
        const yOfDb = (db) => {
            const t = (db - SPEC_DB_TOP) / (SPEC_DB_BOTTOM - SPEC_DB_TOP);
            return Math.max(0, Math.min(plotH, t * plotH));
        };

        // Frequency gridlines + labels (drawn first so the trace sits on top)
        const ticks = [
            [100, '100'], [500, '500'], [1000, '1k'], [2000, '2k'],
            [5000, '5k'], [10000, '10k'], [20000, '20k'],
        ];
        ctx.font = `500 ${9 * dpr}px system-ui, sans-serif`;
        ctx.textBaseline = 'bottom';
        for (const [f, text] of ticks) {
            if (f > fMax) continue;
            const x = xOfFreq(f);
            ctx.strokeStyle = 'rgba(255, 255, 255, 0.08)';
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo(x, 0);
            ctx.lineTo(x, plotH);
            ctx.stroke();
            ctx.fillStyle = 'rgba(255, 255, 255, 0.45)';
            const isLast = f >= fMax;
            ctx.textAlign = isLast ? 'right' : 'left';
            const pad = 3 * dpr;
            ctx.fillText(text, isLast ? x - pad : x + pad, h - 2 * dpr);
        }
        // dB gridlines + labels in the right gutter. The scale is dBFS for
        // a sine, after the 4.5 dB/oct display tilt (see SPEC_TILT_DB_PER_OCT).
        ctx.textAlign = 'left';
        ctx.textBaseline = 'middle';
        for (let db = SPEC_DB_TOP - SPEC_GRID_STEP_DB; db > SPEC_DB_BOTTOM;
             db -= SPEC_GRID_STEP_DB) {
            const y = yOfDb(db);
            ctx.strokeStyle = 'rgba(255, 255, 255, 0.07)';
            ctx.beginPath();
            ctx.moveTo(0, y);
            ctx.lineTo(plotW, y);
            ctx.stroke();
            ctx.fillStyle = 'rgba(255, 255, 255, 0.38)';
            ctx.fillText(String(db), plotW + 4 * dpr, y);
        }

        // Shimmer band shading (log-frequency x-axis)
        const band = getShimmerBand();
        ctx.fillStyle = C.bandFill;
        ctx.fillRect(xOfFreq(band.lo), 0, xOfFreq(band.hi) - xOfFreq(band.lo), plotH);
        ctx.strokeStyle = C.bandEdge;
        ctx.lineWidth = 1;
        for (const f of [band.lo, band.hi]) {
            const x = xOfFreq(f);
            ctx.beginPath();
            ctx.moveTo(x, 0);
            ctx.lineTo(x, plotH);
            ctx.stroke();
        }

        // Display spectrum: one calibrated, tilted dB value per 2 px column.
        const nCols = Math.max(2, Math.floor(plotW / 2));
        if (!specCols || specCols.length !== nCols) specCols = new Float32Array(nCols);
        for (let c = 0; c < nCols; c++) {
            const frac = (c * 2) / plotW;
            const f = fMin * Math.pow(fMax / fMin, frac);
            const bin = Math.min(nBins - 1, Math.round((f / nyq) * (nBins - 1)));
            let db = freqDb[bin];
            if (!Number.isFinite(db)) db = SPEC_DB_BOTTOM - 20;
            db += SPEC_CAL_DB + SPEC_TILT_DB_PER_OCT * Math.log2(f / 1000);
            specCols[c] = Math.max(SPEC_DB_BOTTOM - 6, Math.min(SPEC_DB_TOP + 6, db));
        }
        // Keep a smoothed copy per track so the other A/B side can be
        // drawn as a ghost behind the live trace.
        let g = ghost[state.active];
        if (!g || g.length !== nCols) {
            g = Float32Array.from(specCols);
            ghost[state.active] = g;
        } else {
            for (let c = 0; c < nCols; c++) g[c] += (specCols[c] - g[c]) * GHOST_EMA;
        }
        const ghostKey = state.active === 'original' ? 'processed' : 'original';
        const gh = ghost[ghostKey];
        if (gh && gh.length === nCols) {
            ctx.beginPath();
            for (let c = 0; c < nCols; c++) {
                const y = yOfDb(gh[c]);
                if (c === 0) ctx.moveTo(0, y); else ctx.lineTo(c * 2, y);
            }
            ctx.setLineDash([4 * dpr, 3 * dpr]);
            ctx.strokeStyle = 'rgba(255, 255, 255, 0.34)';
            ctx.lineWidth = 1 * dpr;
            ctx.stroke();
            ctx.setLineDash([]);
        }

        // Log-frequency line spectrum — thin bright gradient line with a
        // translucent filled body (blue/teal -> green/yellow -> pink).
        ctx.beginPath();
        for (let c = 0; c < nCols; c++) {
            const y = yOfDb(specCols[c]);
            if (c === 0) ctx.moveTo(0, y); else ctx.lineTo(c * 2, y);
        }
        const grad = ctx.createLinearGradient(0, 0, plotW, 0);
        grad.addColorStop(0.0, '#38bdf8');
        grad.addColorStop(0.3, '#2dd4bf');
        grad.addColorStop(0.55, '#a3e635');
        grad.addColorStop(0.75, '#facc15');
        grad.addColorStop(1.0, '#f472b6');
        ctx.strokeStyle = grad;
        ctx.lineWidth = 1.5 * dpr;
        ctx.stroke();
        // Fill under the line
        ctx.lineTo(plotW, plotH);
        ctx.lineTo(0, plotH);
        ctx.closePath();
        const bodyGrad = ctx.createLinearGradient(0, 0, 0, plotH);
        bodyGrad.addColorStop(0, 'rgba(140, 110, 250, 0.28)');
        bodyGrad.addColorStop(1, 'rgba(140, 110, 250, 0.06)');
        ctx.fillStyle = bodyGrad;
        ctx.fill();

        // Status label, top-left; ghost key, top-right.
        const statusText = {
            original: 'BEFORE · SOURCE',
            processed: 'AFTER · SHIMMER',
            removed: 'REMOVED · SIGNAL — boosted for monitoring',
        }[state.active] || '';
        ctx.font = `600 ${10 * dpr}px system-ui, sans-serif`;
        ctx.textBaseline = 'top';
        if (statusText) {
            ctx.textAlign = 'left';
            ctx.fillStyle = 'rgba(255, 255, 255, 0.55)';
            ctx.fillText(statusText, 8 * dpr, 6 * dpr);
        }
        if (gh && gh.length === nCols) {
            ctx.textAlign = 'right';
            ctx.fillStyle = 'rgba(255, 255, 255, 0.4)';
            const ghostLabel = ghostKey === 'original' ? 'dashed: Original' : 'dashed: Processed';
            ctx.fillText(ghostLabel, plotW - 8 * dpr, 6 * dpr);
        }
        ctx.textAlign = 'left';

        drawLoudnessStrip();
    }

    // Momentary loudness (BS.1770 K-weighting, 400 ms) of what is playing,
    // on the same LUFS scale as the strip's target marker.
    function drawLoudnessStrip() {
        if (!lufsFillEl || !kAnalysers || !audioCtx) return;
        let ms = 0;
        for (const tap of kAnalysers) {
            tap.getFloatTimeDomainData(timeData);
            let acc = 0;
            for (let i = 0; i < timeData.length; i++) acc += timeData[i] * timeData[i];
            ms += acc / timeData.length;
        }
        const now = audioCtx.currentTime;
        loud.window.push({ t: now, ms });
        while (loud.window.length && now - loud.window[0].t > LUFS_MOMENTARY_S) {
            loud.window.shift();
        }
        let sum = 0;
        for (const s of loud.window) sum += s.ms;
        const mean = loud.window.length ? sum / loud.window.length : 0;
        let lufs = -0.691 + 10 * Math.log10(mean + 1e-12);
        // A mono file is up-mixed to two identical channels on the way to
        // the taps, which doubles the power; the standard counts it once.
        const buf = buffers.get(state.preview ? 'original' : state.active);
        if (buf && buf.numberOfChannels === 1) lufs -= 3.01;
        const span = LUFS_STRIP_MAX - LUFS_STRIP_MIN;
        const pct = Math.max(0, Math.min(100, ((lufs - LUFS_STRIP_MIN) / span) * 100));
        lufsFillEl.style.width = `${pct}%`;
        const hasTarget = Number.isFinite(state.targetLufs);
        if (lufsTargetEl) {
            lufsTargetEl.hidden = !hasTarget;
            if (hasTarget) {
                const tPct = Math.max(0, Math.min(100,
                    ((state.targetLufs - LUFS_STRIP_MIN) / span) * 100));
                lufsTargetEl.style.left = `${tPct}%`;
            }
        }
        const host = lufsFillEl.parentElement;
        if (host && Number.isFinite(lufs) && lufs > LUFS_STRIP_MIN - 20) {
            host.title = `Momentary loudness ${lufs.toFixed(1)} LUFS`
                + (hasTarget ? ` · white line = target ${state.targetLufs} LUFS` : '');
        }
    }

    // ── Animation loop ──────────────────────────────────────────────
    function tick() {
        drawFrame();
        const playing = isPlaying();
        if (metersHost) metersHost.hidden = !playing;
        if (playing) drawLiveMeters();
        updatePlayBtn();
        if (playing && !document.hidden) {
            state.rafId = requestAnimationFrame(tick);
        } else {
            state.rafId = null;
        }
    }

    function kickLoop() {
        if (state.rafId == null) state.rafId = requestAnimationFrame(tick);
    }

    // ── Events ──────────────────────────────────────────────────────
    for (const key of TRACK_KEYS) {
        const el = els[key];
        if (!el) continue;
        el.addEventListener('play', () => {
            // Preview mode plays through Web Audio loops, not elements.
            if (state.preview) { el.pause(); return; }
            // Never allow two elements at once.
            for (const k2 of TRACK_KEYS) {
                if (k2 !== key && els[k2] && !els[k2].paused) els[k2].pause();
            }
            state.active = key;
            updateTabs();
            invalidateBase();
            kickLoop();
        });
        el.addEventListener('pause', () => { updatePlayBtn(); drawFrame(); });
        el.addEventListener('ended', () => { updatePlayBtn(); drawFrame(); });
        el.addEventListener('loadedmetadata', () => { updateTimeLabel(); });
    }

    canvas.addEventListener('click', (ev) => {
        const rect = canvas.getBoundingClientRect();
        const frac = (ev.clientX - rect.left) / rect.width;
        const dur = totalDuration();
        if (dur <= 0) return;
        let t = frac * dur;
        if (state.preview && state.loop) {
            // All preview tracks loop the window; clamp seeks into it.
            t = Math.max(state.loop.start, Math.min(state.loop.end - 0.05, t));
        }
        seekFullTime(t);
        drawFrame();
    });

    if (playBtn) playBtn.addEventListener('click', toggle);

    // The canvas height follows the mode (CSS): the waveform is a
    // navigation strip and stays short; the spectrogram modes keep the
    // full height because their vertical resolution is the point.
    function applyModeClass() {
        canvas.classList.toggle('mode-waveform', state.mode === 'waveform');
        canvas.classList.toggle('mode-spectrogram', state.mode !== 'waveform');
    }

    function setMode(mode) {
        state.mode = ['spectrogram', 'overlay'].includes(mode) ? mode : 'waveform';
        if (modeWaveBtn) modeWaveBtn.classList.toggle('active', state.mode === 'waveform');
        if (modeOverlayBtn) modeOverlayBtn.classList.toggle('active', state.mode === 'overlay');
        if (modeSpecBtn) modeSpecBtn.classList.toggle('active', state.mode === 'spectrogram');
        applyModeClass();
        invalidateBase();
        drawFrame();
    }
    if (modeWaveBtn) modeWaveBtn.addEventListener('click', () => setMode('waveform'));
    if (modeOverlayBtn) modeOverlayBtn.addEventListener('click', () => setMode('overlay'));
    if (modeSpecBtn) modeSpecBtn.addEventListener('click', () => setMode('spectrogram'));

    function attachKeyboard() {
        document.addEventListener('keydown', (ev) => {
            const tag = (ev.target && ev.target.tagName || '').toLowerCase();
            if (['input', 'select', 'textarea', 'button'].includes(tag)) return;
            // These shortcuts drive the Single File player only; without
            // this guard they control the hidden player from other tabs
            // (phantom playback on the Remix tab).
            const singleTab = document.getElementById('tab-single');
            if (singleTab && !singleTab.classList.contains('active')) return;
            if (ev.code === 'Space') {
                ev.preventDefault();
                toggle();
            } else if (ev.key === '1') {
                setTrack('original');
            } else if (ev.key === '2') {
                setTrack('processed');
            } else if (ev.key === '3') {
                setTrack('removed');
            } else if (ev.key === 'ArrowLeft' || ev.key === 'ArrowRight') {
                ev.preventDefault();
                const dt = ev.key === 'ArrowLeft' ? -5 : 5;
                seekFullTime(getTime() + dt);
                drawFrame();
            }
        });
    }

    const resizeObserver = new ResizeObserver(() => drawFrame());
    resizeObserver.observe(canvas);
    document.addEventListener('visibilitychange', () => {
        if (!document.hidden && isPlaying()) kickLoop();
    });

    updateTabs();
    updatePlayBtn();
    applyModeClass();
    drawFrame();

    return {
        setSource,
        setTrack,
        setMode,
        // Seek on the shared timeline (clamped into the loop while Live).
        seek(t) { seekFullTime(t); drawFrame(); },
        skip(dt) { seekFullTime(getTime() + dt); drawFrame(); },
        toStart() {
            seekFullTime(state.preview && state.loop ? state.loop.start : 0);
            drawFrame();
        },
        get duration() { return totalDuration(); },
        setPreviewBuffers,
        decodeAudio,
        exitPreview,
        loadFromJob,
        play,
        pause,
        toggle,
        attachKeyboard,
        getTime,
        redraw: drawFrame,
        setLoopRegion(start, end) {
            state.loop = { start, end };
            drawFrame();
        },
        clearLoopRegion() {
            state.loop = null;
            drawFrame();
        },
        setTargetLufs(v) { state.targetLufs = v; },
        setLoudnessMatch(enabled, gainDbByKey = {}) {
            state.matchEnabled = !!enabled;
            Object.assign(state.gainDb, gainDbByKey);
            applyVolume();
        },
        resetTracks() {
            setSource('processed', null);
            setSource('removed', null);
            exitPreview();
            state.active = 'original';
            updateTabs();
            invalidateBase();
            drawFrame();
        },
        get activeTrack() { return state.active; },
    };
}
