"""Does Spotify's own pipeline colour the audio?

The loopback chain was already cleared: a file played through the soundcard
library and caught on loopback matched the file on disk to 0.28 dB. That
tested Windows, the mixer and the analysis. It did NOT test Spotify's
decoder or its equalizer, which sit upstream of all of it, and every
commercial capture came through them.

Eight masters that exist on this disk were played through Spotify as local
files and captured. So for each one there is a known truth to compare with.

The captures are partial and start wherever playback happened to be, so a
straight comparison against the whole file would measure excerpt selection,
not Spotify. Two things guard against that:

  - each capture is compared against EVERY window of the same length in the
    source file, so the question becomes "does the capture look like some
    part of this master?" rather than "does it look like the average of it"
  - the per-band difference is averaged across all eight tracks, where
    excerpt choice is random and cancels while a systematic colouration adds

A clean path lands inside the window spread on every track and leaves a flat
difference curve. An equalizer or a codec tilt shows up as the same shape on
all eight.
"""
import json
import sys

import numpy as np

sys.path.insert(0, r"D:\MusicVault\Tools\Shimmer")
from shimmer.audio_io import load_audio
from shimmer.mastering import (_REF_FREQS, analyze_spectrum,
                               relative_band_levels)

f = np.asarray(_REF_FREQS, float)
band = (f >= 2500) & (f <= 12500)
SRC = r"D:\MusicVault\Tools\Shimmer\sources"

lib = json.load(open(r"D:\MusicVault\Tools\Shimmer\docs\reference-library.json"))
pairs = [t for t in lib["tracks"] if t["label"].startswith("distrokid-")]
print(f"{len(pairs)} captures pair with a file on disk")
print()

diffs = []
print(f"{'master':<30} {'secs':>5} {'cap':>7} {'disk windows':>22} {'pctile':>7}")
for t in sorted(pairs, key=lambda t: t["label"]):
    name = t["label"]
    cap = np.array(t["rel_db"], float)
    secs = float(t.get("heard_seconds") or 30.0)
    x, sr = load_audio(rf"{SRC}\{name}.wav")
    n = max(int(secs * sr), sr * 5)
    hop = max(n // 2, sr * 5)
    wins = []
    for s0 in range(0, max(1, x.shape[0] - n), hop):
        seg = np.ascontiguousarray(x[s0:s0 + n])
        if seg.shape[0] < n // 2:
            continue
        wins.append(relative_band_levels(
            np.array(analyze_spectrum(seg, sr)["band_power_db"])))
    W = np.array(wins)
    cv, wv = cap[band].mean(), W[:, band].mean(axis=1)
    pct = 100.0 * float((wv < cv).mean())
    print(f"{name.replace('distrokid-', ''):<30} {secs:5.0f} {cv:7.2f} "
          f"[{wv.min():7.2f},{wv.max():7.2f}] n={len(W):<3d} {pct:6.0f}%")
    # difference against the closest window in the mids, where any tilt is
    # smallest, so the top end is compared against a like excerpt
    mid = (f >= 200) & (f <= 2000)
    j = int(np.argmin(np.abs(W[:, mid].mean(axis=1) - cap[mid].mean())))
    diffs.append(cap - W[j])

D = np.array(diffs)
print()
print("Captured minus best-matching source window, averaged over 8 masters:")
print(f"{'Hz':>7} {'mean':>8} {'sd':>7}")
for i, hz in enumerate(f):
    if hz < 100 or hz > 16000:
        continue
    print(f"{hz:7.0f} {D[:, i].mean():+8.2f} {D[:, i].std(ddof=1):7.2f}")

m = D[:, band].mean()
se = D[:, band].mean(axis=1).std(ddof=1) / np.sqrt(len(D))
print()
print(f"2.5-12.5 kHz: {m:+.2f} dB, standard error {se:.2f} over n={len(D)}")
print("CHAIN IS CLEAN" if abs(m) < 2 * se + 0.5 else
      "SPOTIFY IS COLOURING THE AUDIO")
