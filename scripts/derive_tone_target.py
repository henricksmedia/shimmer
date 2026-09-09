"""derive_tone_target.py — build `mastering._REF_SHAPE_DB` from evidence.

Run:  ./.venv/Scripts/python.exe scripts/derive_tone_target.py

Why this exists
---------------
The target has been wrong twice, in opposite directions, and both times it was
a hand-placed array that nobody could re-derive. First it was a 1950-2010
average used as a present-day target. Then it was replaced with the median of
135 masters that one automated service produced from AI renders — a swap from
a published corpus to one vendor's house algorithm, which reads about 7 dB
bright through presence and air against contemporary commercial masters.

So the target is no longer a constant somebody chose. It is the output of this
script, and every number in it is traceable.

How the target is built
-----------------------
**Shape from published research, level correction from measurement.**

The shape comes from Elowsson & Friberg, "Long-term Average Spectrum in
Popular Music and its Relation to the Level of the Percussion", AES 142nd
Convention (2017), paper 9762 — 12,345 tracks. Their Section 3.2 fits the
smoothed mean LTAS with two quadratics on a log-frequency axis of 60 bins per
octave spanning 30 Hz to 15.7 kHz, joined at bin 100 (94 Hz). Those six
coefficients are the whole shape, so the corpus is not needed at run time.
Their fit was checked against their own measured curve, recovered from the
Figure 5 vector data: it is faithful to 0.26 dB over 2.5-12.5 kHz.

That corpus is weighted toward folk and classic-rock CD masters, so it is
dated in two known ways: bass has risen in popular music since (Hove, Vuust &
Stupacher, JASA 145, 2019, strongest below 100 Hz), and percussive material
sits above the mean at both ends of the spectrum (the paper's own Section 4.1).
Both are corrections to a level, not to a shape, which is why measurement is
used only for the correction.

The correction is measured from validated commercial captures in
`docs/reference-library.json` — the captures that pass `references.rejection()`
and are not control captures of our own files.

Three things keep 13 captures from over-fitting a 29-band curve:

  * the correction is smoothed across a wide kernel in log frequency, so it
    cannot follow per-band noise, and it cannot introduce a step (a raw
    zone-by-zone offset would put a 4.7 dB cliff between 160 and 200 Hz,
    an EQ artifact manufactured by the fix);
  * it is shrunk toward zero by its own uncertainty, c^2 / (c^2 + se^2), so a
    band where the captures say little keeps the published shape and a band
    where they speak clearly is corrected in full;
  * everything above 15.7 kHz is outside the paper's stated analysis range and
    is taken from the captures alone, and flagged as such.

Nothing here is fitted to Shimmer's own output, to the service's masters, or
to the target being replaced.
"""
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from shimmer import references as R                        # noqa: E402
from shimmer.mastering import _REF_FREQS, _REF_SHAPE_DB    # noqa: E402

F = np.asarray(_REF_FREQS, dtype=np.float64)
MID = (F >= 200.0) & (F <= 2000.0)

# Elowsson & Friberg Eq. 5 and Eq. 6. Bins are 60 per octave from 30 Hz;
# bin 1 is 30 Hz and bin 543 is 15.7 kHz. Eq. 5 covers bins 1-100 and Eq. 6
# covers 100-543, and the two were adjusted to meet at bin 100.
EQ5 = (-0.000907, 0.256, -32.942)
EQ6 = (-0.000183, 0.0213, -16.735)
PUBLISHED_MAX_HZ = 15700.0

# A third-octave band spans fc*2^(-1/6) to fc*2^(+1/6), so it is
# 2^(1/6) - 2^(-1/6) = 0.23156 of its centre frequency wide. The paper reports
# spectral density; Shimmer measures band power. Without this the comparison
# is wrong by about 9 dB per decade, which is the size of the whole dispute.
BANDWIDTH = 0.231563

SMOOTH_OCTAVES = 1.0      # kernel width for the correction, in octaves


def published_band_db() -> np.ndarray:
    """The paper's mean LTAS on Shimmer's bands, as band power in dB."""
    x = 1.0 + 60.0 * np.log2(F / 30.0)
    a, b, c = (np.where(x < 100.0, EQ5[i], EQ6[i]) for i in range(3))
    psd = a * x ** 2 + b * x + c
    return psd + 10.0 * np.log10(BANDWIDTH * F)


def captures() -> np.ndarray:
    """Validated commercial captures, one row per track."""
    rows = [t for t in R.load().get("tracks", [])
            if not (t.get("rejected") or R.rejection(t)) and not R.is_control(t)]
    if not rows:
        raise SystemExit("No validated commercial captures. Capture some "
                         "music at /static/references/ first.")
    return np.array([np.asarray(t["rel_db"], dtype=np.float64) for t in rows])


def band_floor() -> np.ndarray:
    """Per band, the lowest level a real master reaches, from the corpus.

    A whole-curve gate cannot catch a single bad band. Captures taken before
    2026-09-08 hold a sentinel at 40 Hz — no FFT bin fell inside that band, so
    every one of them recorded about -155 dB there. Smoothed, one such band
    poisons its neighbours and puts a 24 dB step in the target.

    So each band is checked against what the 309 known-real masters do in that
    same band, at the 1st percentile. This says nothing about whether a
    capture agrees with the target; it only asks whether the band contains a
    measurement at all.
    """
    curves = []
    try:
        with open(os.path.join(ROOT, "docs", "tone-reference.json"),
                  encoding="utf-8") as fh:
            for row in json.load(fh).get("tracks", []):
                c = np.asarray(row["rel_db"], dtype=np.float64)
                if c.shape == F.shape:
                    curves.append(c)
    except (OSError, ValueError, KeyError):
        pass
    if len(curves) < 30:
        return np.full(F.shape, -60.0)
    return np.percentile(np.array(curves), 1, axis=0) - 6.0


def smooth(values: np.ndarray, weights: np.ndarray = None) -> np.ndarray:
    """Gaussian smoothing across log frequency.

    Returns the smoothed values and the effective number of bands each
    smoothed point draws on, which is what turns per-band noise into a
    usable standard error.
    """
    lf = np.log2(F)
    sigma = SMOOTH_OCTAVES / 2.355          # FWHM to standard deviation
    out = np.empty_like(values)
    eff = np.empty_like(values)
    for i in range(len(F)):
        k = np.exp(-0.5 * ((lf - lf[i]) / sigma) ** 2)
        if weights is not None:
            k = k * weights
        k = k / k.sum()
        out[i] = float(np.sum(k * values))
        eff[i] = 1.0 / float(np.sum(k ** 2))   # Kish effective sample size
    return out, eff


def main() -> None:
    pub = published_band_db()
    pub_rel = pub - np.median(pub[MID])
    cap = captures()
    n = len(cap)

    # Drop, per band, the values that are not measurements. A band keeps its
    # correction only if most captures actually recorded something there.
    floor = band_floor()
    usable = cap > floor[None, :]
    have = usable.sum(axis=0)
    ok_band = have >= max(3, int(0.6 * n))

    cap_med = np.array([np.median(cap[usable[:, j], j]) if ok_band[j]
                        else np.nan for j in range(len(F))])
    cap_se = np.array([cap[usable[:, j], j].std(ddof=1) / np.sqrt(have[j])
                       if ok_band[j] and have[j] > 1 else np.nan
                       for j in range(len(F))])
    if not ok_band.any():
        raise SystemExit("No band has enough usable captures.")
    for j, hz in enumerate(F):
        if not ok_band[j]:
            print(f"  band {hz:.0f} Hz carries no measurement in "
                  f"{n - have[j]} of {n} captures — left at the published "
                  f"shape")

    # What the captures say the published curve is missing, before any
    # judgement about whether they are saying it clearly. Bands with no
    # measurement contribute nothing and are filled in from their neighbours.
    raw = np.where(ok_band, cap_med - pub_rel, 0.0)
    w = ok_band.astype(np.float64)
    corr, eff = smooth(raw, w)
    # Smoothing averages neighbouring bands, so the error on the smoothed
    # correction falls with the effective number of bands behind each point.
    var = np.where(ok_band, np.nan_to_num(cap_se) ** 2, 0.0)
    se = smooth(var, w)[0] ** 0.5 / np.sqrt(np.maximum(eff, 1.0))
    # A band that had nothing of its own is only as good as its neighbours,
    # so widen its error bar and let the shrinkage pull it back to research.
    se = np.where(ok_band, se, se * 3.0 + 1.0)

    # Shrink toward the published shape by the correction's own uncertainty.
    # A band the captures are sure about is corrected in full; a band they are
    # not keeps the research. This is the standard Wiener form and it is
    # smooth, so it introduces no step of its own.
    weight = corr ** 2 / (corr ** 2 + se ** 2)
    applied = corr * weight

    target = pub_rel + applied
    # Above the paper's stated range there is no published value to correct,
    # so those bands come from the captures alone.
    outside = F > PUBLISHED_MAX_HZ
    target[outside] = cap_med[outside]
    target = target - np.median(target[MID])

    old = np.asarray(_REF_SHAPE_DB, dtype=np.float64)
    print(f"{n} validated commercial captures, "
          f"{int(R.gate()['n'])} masters behind the validity gate")
    print()
    print(f"{'Hz':>7} {'paper':>7} {'captures':>9} {'raw':>6} {'kept':>6} "
          f"{'weight':>7} {'NEW':>7} {'old':>7} {'change':>7}")
    for i, hz in enumerate(F):
        flag = "  (captures only)" if outside[i] else ""
        print(f"{hz:7.0f} {pub_rel[i]:7.2f} {cap_med[i]:9.2f} {raw[i]:6.2f} "
              f"{applied[i]:6.2f} {weight[i]:7.2f} {target[i]:7.2f} "
              f"{old[i]:7.2f} {target[i]-old[i]:+7.2f}{flag}")

    band = (F >= 2500) & (F <= 12500)
    print()
    print(f"2.5-12.5 kHz mean : paper {pub_rel[band].mean():+.2f}, "
          f"captures {cap_med[band].mean():+.2f}, "
          f"NEW {target[band].mean():+.2f}, old {old[band].mean():+.2f}")
    print(f"the new target moves {target[band].mean() - old[band].mean():+.2f} dB "
          f"there, and sits {target[band].mean() - cap_med[band].mean():+.2f} dB "
          f"from the captures")

    # A target that is not smooth becomes an EQ artifact, so say plainly how
    # sharp its worst step is. The old curve is the yardstick.
    step_new = float(np.max(np.abs(np.diff(target))))
    step_old = float(np.max(np.abs(np.diff(old))))
    print(f"largest step between neighbouring bands: new {step_new:.2f} dB, "
          f"old {step_old:.2f} dB")

    # The tolerance band goes with the target: half the 16th-84th spread of
    # the same captures, floored so a band the captures happen to agree on
    # does not become a hair trigger.
    tol = 0.5 * (np.percentile(cap, 84, axis=0) - np.percentile(cap, 16, axis=0))
    tol = np.maximum(tol, 1.5)

    out = {
        "note": "Generated by scripts/derive_tone_target.py. Do not hand-edit.",
        "shape_from": ("Elowsson & Friberg, AES 142 (2017) paper 9762, "
                       "12345 tracks, Eq. 5 and Eq. 6"),
        "correction_from": f"{n} validated commercial captures",
        "smoothing_octaves": SMOOTH_OCTAVES,
        "bands_hz": [float(v) for v in F],
        "published_rel_db": [round(float(v), 2) for v in pub_rel],
        "capture_median_db": [round(float(v), 2) for v in cap_med],
        "correction_raw_db": [round(float(v), 2) for v in raw],
        "correction_applied_db": [round(float(v), 2) for v in applied],
        "correction_se_db": [round(float(v), 2) for v in se],
        "shrink_weight": [round(float(v), 3) for v in weight],
        "target_db": [round(float(v), 2) for v in target],
        "tolerance_db": [round(float(v), 2) for v in tol],
        "n_captures": n,
    }
    path = os.path.join(ROOT, "docs", "tone-target.json")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, indent=1)
        fh.write("\n")
    print(f"\nwrote {os.path.relpath(path, ROOT)}")
    print("\n_REF_SHAPE_DB = np.array([")
    for i in range(0, len(target), 7):
        chunk = ", ".join(f"{v:.1f}" for v in target[i:i + 7])
        print(f"    {chunk},")
    print("], dtype=np.float64)")


if __name__ == "__main__":
    main()
