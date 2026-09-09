"""Capture-chain self-test.

Plays a known file through the default output device and captures it back
through loopback at the same time, then compares the captured curve with the
same file measured directly from disk.

A clean chain agrees within a fraction of a dB. Any system EQ, "audio
enhancement", or resampling colouration shows up here as a difference, and
the shape of the difference says which.

This is the test that decides whether "commercial music is 8 dB darker than
the tone target" is a finding about music or a fault in the measurement.
"""
import sys
import threading
import time

import numpy as np
import soundcard as sc
import soundfile as sf

sys.path.insert(0, r"D:\MusicVault\Tools\Shimmer")
from shimmer.audio_io import load_audio
from shimmer.mastering import (analyze_spectrum, relative_band_levels,
                               _REF_FREQS)

FILE = r"D:\MusicVault\Tools\Shimmer\sources\distrokid-alive-again.wav"
SECONDS = 30.0
SR = 48000

x, sr = load_audio(FILE)
start = x.shape[0] // 3
clip = np.ascontiguousarray(x[start:start + int(SECONDS * sr)])
if clip.ndim == 1:
    clip = clip[:, None]
if clip.shape[1] == 1:
    clip = np.repeat(clip, 2, axis=1)

file_rel = relative_band_levels(
    np.array(analyze_spectrum(clip, sr)["band_power_db"]))

captured = {"acc": None, "n": 0, "raw": []}


def capture() -> None:
    mic = [m for m in sc.all_microphones(include_loopback=True)
           if m.name == sc.default_speaker().name][0]
    with mic.recorder(samplerate=SR, channels=2, blocksize=4096) as rec:
        t0 = time.time()
        while time.time() - t0 < SECONDS + 1.5:
            data = rec.record(numframes=4096)
            mono = data.mean(axis=1)
            captured["raw"].append(mono.copy())
            if np.sqrt(np.mean(mono ** 2)) > 10 ** (-60 / 20):
                bp = np.array(analyze_spectrum(mono, SR)["band_power_db"])
                lin = 10.0 ** (bp / 10.0)
                captured["acc"] = (lin if captured["acc"] is None
                                   else captured["acc"] + lin)
                captured["n"] += 1


t = threading.Thread(target=capture, daemon=True)
t.start()
time.sleep(0.8)                       # let the recorder settle before sound

spk = sc.default_speaker()
print(f"playing {SECONDS:.0f}s through {spk.name} …")
spk.play(clip, samplerate=sr)
t.join(timeout=10)

if not captured["n"]:
    print("NOTHING CAPTURED — the loopback device is not the one playing.")
    raise SystemExit(1)

# Guard: is the loopback hearing ONLY what we played? If anything else is
# playing, the capture is a mix of both and the comparison is meaningless.
# The first run of this test was silently invalid for exactly that reason.
rec_mono = np.concatenate(captured["raw"])
play_mono = clip.mean(axis=1)
n = min(len(rec_mono), len(play_mono))
a, b = rec_mono[:n], play_mono[:n]
env = lambda v, h=2048: np.array([np.sqrt(np.mean(v[i:i+h] ** 2))
                                  for i in range(0, len(v) - h, h)])
ea, eb = env(a), env(b)
m = min(len(ea), len(eb))
best = 0.0
for lag in range(0, 60):
    x1, y1 = ea[lag:m], eb[:m - lag]
    if len(x1) < 20 or x1.std() < 1e-9 or y1.std() < 1e-9:
        continue
    best = max(best, float(np.corrcoef(x1, y1)[0, 1]))
print(f"loopback vs played envelope correlation: {best:.3f}")
if best < 0.80:
    print("ABORT - the loopback is hearing something other than this test.")
    print("Pause all other audio and run it again.")
    raise SystemExit(2)

cap_rel = relative_band_levels(
    10.0 * np.log10(np.maximum(captured["acc"] / captured["n"], 1e-20)))
d = cap_rel - file_rel
f = np.asarray(_REF_FREQS)
band = (f >= 250) & (f <= 12500)

print()
print(f"{'Hz':>7} {'file':>8} {'captured':>9} {'diff':>7}")
for i, hz in enumerate(f):
    if hz < 100 or hz > 16000:
        continue
    print(f"{hz:7.0f} {file_rel[i]:8.2f} {cap_rel[i]:9.2f} {d[i]:+7.2f}")

print()
print(f"250 Hz - 12.5 kHz : mean |diff| {np.mean(np.abs(d[band])):.2f} dB, "
      f"max {d[band][np.argmax(np.abs(d[band]))]:+.2f} dB")
verdict = ("CHAIN IS CLEAN — captured audio matches the file, so the 8 dB "
           "gap is real music, not measurement."
           if np.mean(np.abs(d[band])) < 1.0 else
           "CHAIN IS COLOURING THE AUDIO — the capture does not match the "
           "file, so the 8 dB gap is at least partly this, not the music.")
print(verdict)
