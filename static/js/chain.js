// chain.js — Signal Chain view.  A read-along map of the actual processing
// pipeline (pipeline.py order): every stage as an inspectable module.
// Presentational only — modules with user controls deep-link to the
// Advanced drawer, which single.js owns.

const CHAIN = [
    { id: 'tone',     cat: 'Pre',       name: 'Tone Curve',             gloss: 'bounded static EQ from raw analysis', badges: ['+2.0 / −3.0 dB max', 'pre-clean'],
      detail: 'When mastering is on, a corrective tone curve is computed from the raw file and applied before cleaning. Boosts are capped at +2 dB (+0.5 dB in the 5–12 kHz band) so AI fizz can never be re-amplified.' },
    { id: 'xover',    cat: 'Split',     name: 'Linear-Phase Crossover', gloss: 'low band bypasses everything', badges: ['4500 Hz', '1023-tap FIR'],
      detail: 'A complementary linear-phase FIR split at 4.5 kHz. Everything below the crossover — kick, bass, vocals’ body — bypasses the cleaning engine entirely and is recombined untouched.' },
    { id: 'ms',       cat: 'Split',     name: 'High Band → M/S',        gloss: 'Mid cleaned gently, Side fully', badges: ['Mid 0.2×', 'Side 1.0×'],
      detail: 'The high band is encoded to Mid/Side. The Mid (center) channel is cleaned at 20% strength to protect vocals and snare; the Side channel takes the full treatment — most AI shimmer lives in the sides.' },
    { id: 'expander', cat: 'STFT 1/9',  name: 'Expander',               gloss: 'downward expander, 3–8 kHz', badges: ['−45 dB thr', '2:1'],
      detail: 'Pushes down 3–8 kHz energy when the music drops below threshold — catches shimmer tails at the edges of musical events. Engaged by presets like Echo Sheen.' },
    { id: 'denoise',  cat: 'STFT 2/9',  name: 'Denoise',                gloss: 'minimum-statistics noise floor', badges: ['1.5–16 kHz', '−18 dB floor'], adv: ['denoise'],
      detail: 'A Wiener-style spectral denoiser with a minimum-statistics floor tracker. Driven by the Denoise slider.' },
    { id: 'deres',    cat: 'STFT 3/9',  name: 'De-Resonator',           gloss: 'dynamic notches on ringing peaks', badges: ['0.3–12 kHz', '8 dB max'], adv: ['deres'],
      detail: 'Finds narrow spectral peaks that persist over time — resonant rings and birdies — and notches them dynamically. Driven by the De-resonator slider.' },
    { id: 'shimmer',  cat: 'STFT 4/9',  name: 'Shimmer Suppressor',     gloss: 'the core narrowband detector', badges: ['band + threshold + slope'], adv: ['start_hz', 'end_hz', 'thr_db', 'slope'],
      detail: 'The original Shimmer stage: detects narrowband energy that pokes above the local spectral median inside the detection band, and attenuates it. The Band, Threshold, and Slope controls all act here.' },
    { id: 'deharsh',  cat: 'STFT 5/9',  name: 'De-Harsh',               gloss: 'dynamic 5–9 kHz fizz tamer', badges: ['6 dB max'], adv: ['deharsh'],
      detail: 'A dynamic de-esser for the 5–9 kHz fizz band, referenced against the clean 1–4 kHz body so it only fires when the top is disproportionately hot. Driven by the De-harsh slider.' },
    { id: 'flicker',  cat: 'STFT 6/9',  name: 'Flicker Tamer',          gloss: 'sub-band AM compressor for Suno hash', badges: ['4.5–12 kHz', '6 bands'],
      detail: 'Splits the brilliance band into sub-bands and compresses frame-to-frame amplitude flicker — the signature Suno "hash". Tuned per preset.' },
    { id: 'decheck',  cat: 'STFT 7/9',  name: 'De-Checker',             gloss: 'periodic grid-tooth suppressor', badges: ['3–16 kHz', '80–600 Hz spacing'], adv: ['decheck'],
      detail: 'Detects evenly-spaced spectral teeth (the deconvolution "checkerboard" grid) and suppresses the comb. Driven by the De-checker slider.' },
    { id: 'tonekill', cat: 'STFT 8/9',  name: 'Narrow-Tone Kill',       gloss: 'steady whistle notcher', badges: ['3.5–20 kHz', '20 dB max'],
      detail: 'Hunts steady-state synthetic whistles that hold one frequency for seconds, and notches them hard. Tuned per preset (Laser Whistle).' },
    { id: 'resynth',  cat: 'STFT 9/9',  name: 'Noise Resynth',          gloss: 'random-phase de-crystallizer', badges: [],
      detail: 'Blends a random-phase copy of the residual back in, replacing crystalline artifact texture with natural-sounding noise.' },
    { id: 'gates',    cat: 'Always on', name: 'Gates',                  gloss: 'flatness gate + transient hold', badges: ['hold 70 ms'],
      detail: 'Two safety gates ride along every STFT stage: a spectral-flatness gate backs the cleaning off on noisy or percussive frames, and a transient-hold gate protects attacks for ~70 ms so drums keep their snap.' },
    { id: 'swc',      cat: 'Recombine', name: 'Side Width Comp',        gloss: 'restores stereo width', badges: ['+1.5 dB max'],
      detail: 'Cleaning the Side channel narrows the image; this stage measures the loss and applies bounded make-up gain so the mix keeps its width.' },
    { id: 'mix',      cat: 'Recombine', name: 'Recombine + Wet/Dry',    gloss: 'M/S decode, rejoin low band, blend', badges: [], adv: ['mix'],
      detail: 'M/S decodes the cleaned high band, rejoins the untouched low band, and blends against the original by the Mix control.' },
    { id: 'post',     cat: 'Post',      name: 'Post Filters + Fades',   gloss: 'shelves + subsonic HP, zero-phase', badges: ['5 ms fades'], adv: ['high_shelf_db'],
      detail: 'Zero-phase finishing filters: the Air-cut high shelf, subsonic high-pass, and short edge fades.' },
    { id: 'eq',       cat: 'Post',      name: 'Parametric EQ',          gloss: 'your EQ — post-clean, pre-master', badges: ['12 bands max'],
      detail: 'Your Parametric EQ card is applied here — zero-phase, after cleaning and before mastering, so your tonal moves are never fighting the artifact detector.' },
    { id: 'm-hp',     cat: 'Master',    name: 'HP / DC Removal',        gloss: 'subsonic cleanup', badges: ['25 Hz'],
      detail: 'A gentle high-pass removes DC offset and subsonic rumble before loudness measurement.' },
    { id: 'm-gain',   cat: 'Master',    name: 'LUFS Gain',              gloss: 'one static gain to target', badges: ['−14 / −11 / −9'],
      detail: 'A single static gain moves integrated loudness to your target. No multiband compression, no pumping — the dynamics you generated are the dynamics you keep.' },
    { id: 'm-clip',   cat: 'Master',    name: 'Soft Clip',              gloss: 'rounds the top ~2 dB', badges: [],
      detail: 'A cubic soft-clipper shaves only the top couple of dB of peaks so the limiter works less hard.' },
    { id: 'm-limit',  cat: 'Master',    name: 'True-Peak Limiter',      gloss: 'keeps loud parts from clipping', badges: ['4× OS', '2 ms lookahead'],
      detail: '4× oversampled lookahead limiting to the format-aware ceiling: −1.0 dBTP for WAV/FLAC, −1.5 dBTP for lossy formats so the encoder can’t clip on decode.' },
];

let selected = 'shimmer';

export function initChainTab() {
    const host = document.getElementById('chain-host');
    if (!host) return;

    host.innerHTML = `
        <div class="chain-head">
            <h2>Signal Chain</h2>
            <span class="lede">Every stage your audio passes through, in order. Click a module to learn what it does — stages with sliders open the Advanced drawer.</span>
        </div>
        <div class="chain-scroll"><div class="chain-lane"></div></div>
        <div class="chain-gates">
            <span class="chip cyan" title="Backs cleaning off on noisy or percussive frames">⛩ Spectral-Flatness Gate</span>
            <span class="chip cyan" title="Protects attacks — 70 ms hold">⛩ Transient Hold</span>
            <span class="chip">low band &lt; 4.5 kHz bypasses cleaning entirely</span>
        </div>
        <div class="chain-detail" id="chain-detail"></div>`;

    const lane = host.querySelector('.chain-lane');
    lane.innerHTML = CHAIN.map((m, i) => `
        ${i > 0 ? '<div class="chain-wire"></div>' : ''}
        <button type="button" class="mod ${m.id === selected ? 'selected' : ''}" data-id="${m.id}">
            <div class="m-cat">${m.cat}</div>
            <div class="m-name">${m.name}</div>
            <div class="m-gloss">${m.gloss}</div>
            ${m.badges.length ? `<div class="m-badges">${m.badges.map(b => `<span class="b">${b}</span>`).join('')}</div>` : ''}
        </button>`).join('');

    lane.addEventListener('click', (e) => {
        const btn = e.target.closest('.mod');
        if (!btn) return;
        selected = btn.dataset.id;
        lane.querySelectorAll('.mod').forEach(x => x.classList.toggle('selected', x === btn));
        renderDetail(host);
    });

    renderDetail(host);
}

function renderDetail(host) {
    const mod = CHAIN.find(m => m.id === selected);
    const box = host.querySelector('#chain-detail');
    const hasAdv = mod.adv && mod.adv.length;
    box.innerHTML = `
        <h3>${mod.name}</h3>
        <p>${mod.detail}</p>
        ${hasAdv
            ? `<button type="button" class="btn btn-ghost" id="chain-open-adv">Open its controls in the Advanced drawer ›</button>`
            : `<span class="chip">tuned per preset — no direct user control</span>`}`;
    box.querySelector('#chain-open-adv')?.addEventListener('click', () => {
        document.getElementById('advanced-open-btn')?.click();
    });
}
