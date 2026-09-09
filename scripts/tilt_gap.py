"""
tilt_gap.py — How far out of tilt were Shimmer's masters, against a
settings-consistent reference?

Checklist item 2. The assessment quoted "about 11 dB across 800 Hz to
6.3 kHz" from six songs measured against whatever reference master happened
to be filed for each, mastered on mixed settings. This measures the same
gap for every song where the catalogue holds both a Shimmer master and the
service's **MediumNeutral** master, so the yardstick is one setting.

Pairing is by song stem (the service stamps its settings into the filename;
Shimmer's export suffix is stripped with tags.strip_shimmer_suffix), then
every pair is checked to be the same performance with corpus_check's
envelope test, at its threshold. A pair that fails is listed and excluded,
not silently used — the corpus check exists because one such pair got in.

The gap is the reference's tilt minus Shimmer's, where tilt is the 1/3-octave
band level at 6.3 kHz minus the level at 800 Hz, both relative to the median
of 200 Hz-2 kHz (mastering.relative_band_levels), on the middle EXCERPT_S
seconds, the same analysis the tone reference was built with. Positive means
Shimmer's master is duller than the reference across that range.

The Shimmer masters in the catalogue were made by earlier versions of the
chain (their tags, when present, say which); this number is the size of the
defect as shipped, not the current chain's. Re-rendering from source is
verify_tone_fix.py's job.

Usage: python scripts/tilt_gap.py [--out docs/tilt-gap.json]
"""
from __future__ import annotations

import json
import os
import re
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from corpus_check import (ENV_MAX_LAG_S, IDENTITY_MIN_CORR, _best_lag_corr,  # noqa: E402
                          _envelope, split_settings)
from shimmer.audio_io import load_audio                                      # noqa: E402
from shimmer.mastering import (_REF_FREQS, analyze_spectrum,                 # noqa: E402
                               relative_band_levels)
from shimmer.tags import read_tags, strip_shimmer_suffix                    # noqa: E402
from build_tone_reference import ROOTS                                       # noqa: E402

EXCERPT_S = 90.0
LOW_HZ, HIGH_HZ = 800.0, 6300.0
SETTING = "MediumNeutral"
MIN_STEM = 12          # a truncated Shimmer stem must keep at least this much


def norm(stem: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", stem.lower())


def band(hz: float) -> int:
    return int(np.argmin(np.abs(_REF_FREQS - hz)))


def tilt(path: str):
    x, sr = load_audio(path)
    n = int(EXCERPT_S * sr)
    if x.shape[0] > n:
        s = (x.shape[0] - n) // 2
        x = x[s:s + n]
    rel = np.array(relative_band_levels(np.array(analyze_spectrum(x, sr)["band_power_db"])))
    return float(rel[band(HIGH_HZ)] - rel[band(LOW_HZ)]), rel


def collect():
    refs, shims = {}, []
    for root in ROOTS:
        if not os.path.isdir(root):
            continue
        for dirpath, _, files in os.walk(root):
            folder = os.path.basename(dirpath).lower()
            for fn in files:
                if not fn.lower().endswith(".wav"):
                    continue
                path = os.path.join(dirpath, fn)
                song, meta = split_settings(fn)
                if meta.get("service", "").lower() == "mixea":
                    if meta.get("settings") == SETTING:
                        # One reference per song; prefer the non-hd copy only
                        # to be deterministic, they are the same master.
                        key = norm(song)
                        if key not in refs or "hd" not in (meta.get("quality") or ""):
                            refs[key] = (path, song)
                    continue
                if folder == "shimmer":
                    stem = strip_shimmer_suffix(os.path.splitext(fn)[0])
                    shims.append((path, stem, norm(stem)))
    return refs, shims


def pair(refs, shims):
    out = {}
    for path, stem, key in shims:
        match = None
        if key in refs:
            match = key
        elif len(key) >= MIN_STEM:
            cands = [k for k in refs if k.startswith(key)]
            if len(cands) == 1:
                match = cands[0]
        if match is None:
            continue
        # Several Shimmer exports of one song: keep the newest file.
        cur = out.get(match)
        if cur is None or os.path.getmtime(path) > os.path.getmtime(cur):
            out[match] = path
    return out


def main(argv):
    out_path = argv[argv.index("--out") + 1] if "--out" in argv else os.path.join(ROOT, "docs", "tilt-gap.json")
    refs, shims = collect()
    pairs = pair(refs, shims)
    print(f"{len(refs)} {SETTING} masters, {len(shims)} Shimmer exports, {len(pairs)} paired by name\n")
    rows, rejected = [], []
    for key, spath in sorted(pairs.items()):
        rpath, song = refs[key]
        # A service master made FROM a Shimmer export is not an independent
        # yardstick: its stem still carries Shimmer's export suffix.
        if re.search(r"_(processed|trimmed)_[0-9a-f]{0,8}$", song) or "_processed" in song:
            rejected.append({"song": song, "shimmer": spath, "reference": rpath,
                             "reason": "reference was mastered from a Shimmer export"})
            print(f"  rejected {song}: the reference is a master of a Shimmer export")
            continue
        env_r, sr_r, dur_r = _envelope(rpath)
        env_s, sr_s, dur_s = _envelope(spath)
        corr = _best_lag_corr(env_r, env_s, int(ENV_MAX_LAG_S / 0.05))
        if not np.isfinite(corr) or corr < IDENTITY_MIN_CORR or abs(dur_r - dur_s) > 5.0:
            rejected.append({"song": song, "shimmer": spath, "reference": rpath,
                             "corr": round(float(corr), 3), "dur_ref": round(dur_r, 1),
                             "dur_shimmer": round(dur_s, 1)})
            print(f"  rejected {song}: envelope corr {corr:.3f}, durations {dur_r:.0f}/{dur_s:.0f} s")
            continue
        t_r, rel_r = tilt(rpath)
        t_s, rel_s = tilt(spath)
        tags = read_tags(spath)
        rows.append({"song": song, "shimmer": spath, "reference": rpath,
                     "corr": round(float(corr), 3),
                     "tilt_ref_db": round(t_r, 2), "tilt_shimmer_db": round(t_s, 2),
                     "gap_db": round(t_r - t_s, 2),
                     "rel_ref_db": [round(float(v), 2) for v in rel_r],
                     "rel_shimmer_db": [round(float(v), 2) for v in rel_s],
                     "shimmer_note": tags.get("comment") or tags.get("software") or ""})
        print(f"  {song[:48]:48s} gap {t_r - t_s:6.2f} dB  (corr {corr:.3f})", flush=True)
    gaps = np.array([r["gap_db"] for r in rows])
    summary = {}
    if gaps.size:
        summary = {"n": int(gaps.size), "mean_db": round(float(gaps.mean()), 2),
                   "median_db": round(float(np.median(gaps)), 2),
                   "sd_db": round(float(gaps.std(ddof=1)), 2) if gaps.size > 1 else 0.0,
                   "p16_db": round(float(np.percentile(gaps, 16)), 2),
                   "p84_db": round(float(np.percentile(gaps, 84)), 2),
                   "min_db": round(float(gaps.min()), 2), "max_db": round(float(gaps.max()), 2),
                   "positive": int((gaps > 0).sum())}
        print(f"\nTilt gap {LOW_HZ:.0f} Hz -> {HIGH_HZ:.0f} Hz, reference minus Shimmer, "
              f"n = {gaps.size}: mean {gaps.mean():.2f} dB, median {np.median(gaps):.2f}, "
              f"sd {gaps.std(ddof=1) if gaps.size > 1 else 0:.2f}, "
              f"16th-84th percentile {np.percentile(gaps, 16):.2f} to {np.percentile(gaps, 84):.2f}, "
              f"{int((gaps > 0).sum())}/{gaps.size} positive")
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"setting": SETTING, "excerpt_s": EXCERPT_S,
                   "bands_hz": [LOW_HZ, HIGH_HZ], "summary": summary,
                   "pairs": rows, "rejected": rejected}, f, indent=1)
    print(f"\nwrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
