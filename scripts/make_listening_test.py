"""
make_listening_test.py — Render a blind listening test for the damage model.

An objective measure is only worth anything if it agrees with ears. This
builds the material to check that, using the four same-song triplets in
`sources/`.

Design follows the shape of ITU-R BS.1534 (MUSHRA), the standard for
intermediate-quality subjective testing: short excerpts, level-matched,
labelled blind, and with a hidden reference included so the listener's own
consistency can be checked. It is not a formal MUSHRA panel — one listener,
no statistics — but the parts that stop a test from lying are kept:

  * **Level matching.** Every clip is normalised to the same LUFS. Without
    this the louder clip wins regardless of what it did, which is exactly the
    trap that made these masters sound acceptable in the first place.
  * **Blind labels.** Files are A/B/C/D per song, and the key is written to a
    separate file. Read it after listening, not before.
  * **A hidden reference.** One of the labels is the untouched source. If it
    is not ranked cleanest, the test told you nothing that day.

Two things to listen to, and the second matters more:

  1. `*-master-*.wav` — the processed results, level-matched. Which sounds
     most open?
  2. `*-residual-*.wav` — **what each preset removed**, amplified so it is
     audible. This is the honest test of the whole argument. If a residual is
     hiss and fizz, the preset did its job. If you can hear cymbals, vocal
     air, reverb tails or melody in it, the preset took music, and no
     spectrum plot is needed to settle it.

Usage:  python scripts/make_listening_test.py [outdir]
"""
from __future__ import annotations

import json
import os
import random
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shimmer import perceptual as P                       # noqa: E402
from shimmer.audio_io import load_audio, save_audio       # noqa: E402
from shimmer.mastering import apply_gain_to_lufs, measure_loudness  # noqa: E402
from shimmer.pipeline import clean_and_master             # noqa: E402
from shimmer.presets import PRESETS, label_for            # noqa: E402

SRC_DIR = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "sources")
SONGS = ["algorithms-lure", "alive-again", "leave-the-world-behind",
         "we-were-meant-for-the-stars"]

# Three presets spanning the measured damage range, plus the hidden
# reference. Keeping the span wide is the point: if the model is right the
# ranking is obvious, and if it is wrong that will be obvious too.
PRESETS_UNDER_TEST = ["cymbal_sheen", "suno_hash", "deep_scrub"]

EXCERPT_S = 25.0
TEST_LUFS = -18.0        # quiet enough that no clip needs limiting
RESIDUAL_PEAK = 0.5      # residuals are amplified to be audible


def loudest_excerpt(x: np.ndarray, sr: int, secs: float) -> np.ndarray:
    """The densest `secs` of the track — where artifacts and damage both
    live. A quiet intro proves nothing."""
    n = int(secs * sr)
    if x.shape[0] <= n:
        return x
    mono = x.mean(axis=1) if x.ndim > 1 else x
    win = sr // 2
    frames = mono[:len(mono) // win * win].reshape(-1, win)
    energy = np.convolve((frames ** 2).mean(axis=1),
                         np.ones(max(1, n // win)), mode="valid")
    start = int(np.argmax(energy)) * win
    return np.ascontiguousarray(x[start:start + n])


def at_lufs(x: np.ndarray, sr: int, target: float) -> np.ndarray:
    y, _ = apply_gain_to_lufs(x, sr, target)
    peak = float(np.max(np.abs(y))) or 1.0
    if peak > 0.99:                       # never let the test clip
        y = y * (0.99 / peak)
    return y


def main(outdir: str) -> None:
    os.makedirs(outdir, exist_ok=True)
    rng = random.Random(20260908)
    key: dict = {"how_to_listen": [
        "Play the four *-master-*.wav files for one song back to back.",
        "Then play the *-residual-*.wav files. Those are what each preset",
        "REMOVED. Hiss is fine. Cymbals, air, reverb tails or melody are not.",
        "Write down your ranking, THEN open this file's 'answers' section.",
    ], "songs": {}}

    for song in SONGS:
        src_path = os.path.join(SRC_DIR, f"suno-{song}.wav")
        if not os.path.exists(src_path):
            print(f"  skip {song}: no source")
            continue
        x, sr = load_audio(src_path)
        clip = loudest_excerpt(x, sr, EXCERPT_S)

        entries = []
        # The hidden reference: untouched source, same level as the rest.
        entries.append({"preset": None, "label": "reference",
                        "audio": clip, "residual": None,
                        "damage": {"lin_dist": 0.0, "missing": 0.0,
                                   "added": 0.0}})
        for name in PRESETS_UNDER_TEST:
            y, removed, _ = clean_and_master(
                clip, sr, PRESETS[name](), master_params=None,
                eq_params=None, repair=None)
            y = np.asarray(y)[:clip.shape[0]]
            d = P.measure_damage(clip, y, sr)
            entries.append({"preset": name, "label": label_for(name),
                            "audio": y, "residual": np.asarray(removed),
                            "damage": d.as_dict()})

        letters = list("ABCD")[:len(entries)]
        rng.shuffle(letters)

        # ONE gain for every residual in a song, set by the loudest of them.
        #
        # The first version of this script normalised each residual to the
        # same peak. That destroyed the information the test exists to
        # convey: a preset that removes a great deal was quietened, and one
        # that removes little was amplified, until both sounded equally
        # significant. A listener could then only judge "is the content in
        # here recognisable as music", never "how much was taken" - and those
        # are different questions with different answers.
        peaks = [float(np.max(np.abs(e["residual"][:clip.shape[0]])))
                 for e in entries if e["residual"] is not None]
        shared_gain = RESIDUAL_PEAK / (max(peaks) if peaks and max(peaks) > 0
                                       else 1.0)
        shared_gain_db = round(20.0 * np.log10(shared_gain), 1)

        song_key = []
        for letter, e in zip(letters, entries):
            save_audio(os.path.join(outdir, f"{song}-master-{letter}.wav"),
                       at_lufs(e["audio"], sr, TEST_LUFS), sr, subtype="PCM_24")
            gain_db = None
            if e["residual"] is not None:
                r = e["residual"][:clip.shape[0]]
                gain_db = shared_gain_db
                save_audio(
                    os.path.join(outdir, f"{song}-residual-{letter}.wav"),
                    r * shared_gain, sr, subtype="PCM_24")
            song_key.append({
                "file_letter": letter,
                "what_it_is": e["label"] if e["preset"] else
                              "HIDDEN REFERENCE (untouched source)",
                "residual_amplified_db": gain_db,
                "model_says": e["damage"],
            })
            tag = e["label"] if e["preset"] else "reference"
            print(f"  {song} {letter}: {tag:24s} "
                  f"lin_dist {e['damage']['lin_dist']:8.3f}  "
                  f"missing {e['damage']['missing']:.3f}")
        key["songs"][song] = sorted(song_key, key=lambda r: r["file_letter"])

    key["answers"] = ("Each song's list above is the key. 'model_says' is the "
                      "BS.1387 damage measure: lin_dist is spectral-tilt "
                      "damage (higher is worse), missing is removed audible "
                      "content in sones. If your ranking of the residuals "
                      "matches the lin_dist order, the model agrees with your "
                      "ears. If it does not, the model is wrong and needs to "
                      "change - that is the point of running this.")
    with open(os.path.join(outdir, "ANSWER-KEY.json"), "w",
              encoding="utf-8") as f:
        json.dump(key, f, indent=2)
    print(f"\nWritten to {outdir}")
    print("Listen first. ANSWER-KEY.json spoils it.")


def next_round_dir(base: str) -> str:
    """A fresh `round-N` folder, so a re-render can never overwrite a round
    that has already been listened to. Comparing rounds is the whole point:
    a change to the presets or the model is only real if the next round
    sounds different from the last one."""
    os.makedirs(base, exist_ok=True)
    used = [int(d.split("-")[1]) for d in os.listdir(base)
            if d.startswith("round-") and d.split("-")[-1].isdigit()]
    return os.path.join(base, f"round-{max(used, default=0) + 1}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        main(sys.argv[1])
    else:
        main(next_round_dir(
            os.path.join(os.path.dirname(SRC_DIR), "listening-test")))
