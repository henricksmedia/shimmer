# Tone-target evidence

Every measurement behind `docs/BRIGHTNESS-ASSESSMENT.md` §7 — the section
that retracts the tone target shipped in `97609c0` — with the script that
produced it and the number it gave.

This exists because the analysis was done in a session scratch directory that
gets deleted. Without it, §7 is a set of assertions nobody can re-check, and
the next person to doubt the conclusion has to redo two days of work to test
it. Re-running a script here is minutes.

Run everything with the project venv from the repository root:

```
./.venv/Scripts/python.exe scripts/tone-evidence/<name>.py
```

## What each script establishes

| script | question | result |
|---|---|---|
| `chain_test.py` | Does the loopback capture path colour the audio? | **0.28 dB** mean, 0.53 worst, 250 Hz–12.5 kHz. Clean. |
| `spotify_control.py` | Does Spotify's decoder and equalizer colour it? | **−0.57 dB ± 0.38** over 2.5–12.5 kHz across 8 masters played from disk through Spotify. Flat per-band, no tilt. Clean. |
| `excerpt_bias.py` | How much does a short capture misstate a master? | −1.35 dB mean, −4.45 worst, up to 5.71 dB spread between 30 s windows. **See caveat below — this number is weak.** |
| `plausible.py` | Which captures are broken rather than dark? | Gate from the 1st percentile of 317 known-real masters: 10 kHz ≥ −29.1 dB, 16 kHz ≥ −40.1 dB, 4–16 kHz slope ≥ −14.0 dB/oct. Rejects 2 of 15. |
| `pdf_paths.py` | (library) Minimal PDF content-stream reader. | Extracts vector paths and text positions. Used by `real_ltas.py`. |
| `real_ltas.py` | Is the paper's quadratic faithful to its own measured curve? | Recovers the real mean LTAS from the Figure 5 vector data; axis calibration residual **0.001 dB**; the quadratic misstates the real curve by only **−0.26 dB** over 2.5–12.5 kHz. |
| `elowsson_grid.py` | Where does everything sit on one grid? | Target **−0.80**, service masters −1.53, Shimmer output −6.53, captures −8.72, paper −11.75 (2.5–12.5 kHz, dB rel. 200 Hz–2 kHz median). |
| `slope_arbiter.py` | Do the PSD slopes match published corpora? | 1–10 kHz: target −2.92, service −3.22, captures −6.07, paper −7.60 dB/oct. |
| `invariant_slope.py` | The 89 Hz–4.5 kHz percussion-invariant slope. | Target −4.28, service −4.47, captures −5.18, paper −4.46. **This test is nearly worthless — see below.** |
| `three_points.py` | Suno / Shimmer / service / captured on one axis. | Shimmer's *old* output (−6.53) was closer to commercial music (−8.72) than the new target (−0.80) is. |
| `shape_test.py` | Do the captures depart from the paper the way the paper predicts? | Yes. Bass +7.1, low-mid +1.1, mid +0.4, presence +0.9, air +4.4 — the predicted smile. The target instead ramps +0.8 → +7.6 → +12.9 and never returns. |

## Two results here are traps

**`invariant_slope.py` must not be read as evidence that the low end is
calibrated.** It is a two-point secant and is blind to any error common to
both endpoints. The target's error against the paper is +9.36 dB at 89 Hz and
+10.10 dB at 4.5 kHz, so the slope sees only the 0.74 dB difference while the
RMS residual across that span is 4.82 dB. The pre-`97609c0` target scores
−4.545 — *closer* to the paper than the current one — while sitting ~4.9 dB
above it everywhere. Also, the ±0.055 dB/oct figure from the paper is the SD
between eleven group means of ~1122 tracks each, and it is the argmin of a
2-D endpoint search; the per-track SD measured here is 0.744 (service
masters) and 1.085 (captures), 13–20× larger. Use ±1.5 dB/oct if you use it
at all.

**`excerpt_bias.py`'s −1.35 dB is not a solid measurement.** n=8, sd 2.21,
se 0.78, 95% CI [−3.19, +0.50]; a randomly placed window is unbiased in
principle; and the captures' brightness-versus-duration correlation runs the
wrong way (r = −0.362). `spotify_control.py` supersedes it with direct
on-chain evidence: 21–23 s excerpt captures land within 0.75 dB of the full
file. Carry the correction as **−0.6 ± 0.4 dB**, not −1.35.

## Papers

Not committed — they are copyrighted and this repository is public. Fetch
them locally and point the scripts at your own copy.

- **Elowsson & Friberg, "Long-term Average Spectrum in Popular Music and its
  Relation to the Level of the Percussion", AES 142 (2017), paper 9762.**
  12,345 tracks. The source for Eq. 5/6 (the two quadratics), Eq. 7 (the
  slope), Table 1, and the 89 Hz–4.5 kHz invariant.
  Open access: <https://kth.diva-portal.org/smash/record.jsf?pid=diva2:1108529>
  `real_ltas.py` needs the PDF; edit the `PDF` constant in `pdf_paths.py`.
- **Hove, Vuust & Stupacher, *JASA* 145 (2019) 2247** — bass levels in
  Billboard Hot 100 material rose 1955–2016, strongest below 100 Hz. Why the
  paper's Dylan/Beatles-weighted corpus reads ~6 dB low in the bass against
  every contemporary master measured here.
- **Pestana, Reiss & Barbosa, AES 135 (2013)** — 772 recordings, the source
  of the *old* target and of the "≈5 dB/octave" figure. Elowsson's 800 Hz
  slope (−4.985) is the same number.

## adjudication/

Unpolished scripts written by the eight agents that independently re-derived
and attacked the §7 conclusion, kept verbatim for reproducibility. Not
maintained, paths not portable, quality varies. They are here because they
carry independent checks that are expensive to reproduce — notably a
from-scratch reimplementation of the paper's §2.2 analysis pipeline, an
empirical confirmation that `analyze_spectrum` returns integrated band power
(white noise +3.026 dB/oct, pink +0.023), and a synthesis check that built
noise to the paper's exact PSD and measured −11.65 against −11.75 predicted.

Verdict: the arithmetic reproduced by five independent routes; all three
skeptics returned "not refuted", including the one assigned to defend the
target; and the corrections they produced made the defect **larger**, not
smaller — the divergence begins at ~1.25–1.6 kHz, not 4.5 kHz.

## Known rough edges

Absolute paths are hardcoded to `D:\MusicVault\Tools\Shimmer` in most of
these. They were written to answer a question, not to ship. Fix them when a
script graduates into the maintained set — `spotify_control.py` and
`plausible.py` are the two that should, since checklist item 14 needs both.
