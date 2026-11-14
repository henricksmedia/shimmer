"""
make_round8.py — Standard mastering, round 1 changes: before vs after.

Per song: the default master (Standard, Commercial -9 LUFS) as it shipped in
2.x up to commit a5fc499, and with round 1 (the glue compressor listens
above 100 Hz; saturation runs above 120 Hz only). Same song, same settings,
nothing else changed. The loudest 30 s, matched to -18 LUFS, blind: two
letters per song, shuffled.

Usage:  python scripts/make_round8.py <song.wav> [<song.wav> ...] [--out DIR]
        (default out: listening-test/round-8)
"""
from __future__ import annotations

import importlib.util
import json
import os
import random
import subprocess
import sys
import tempfile

import numpy as np
import soundfile as sf

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from shimmer.core import Settings, Source, render          # noqa: E402
from shimmer.core.audio import meters                       # noqa: E402
from shimmer.core.master import standard as NEW             # noqa: E402

BEFORE_COMMIT = "a5fc499"
TEST_LUFS = -18.0
SPAN_S = 30.0

MEANING = {
    "before": "Standard as it shipped (before round 1)",
    "after": "Standard with round 1: glue listens above 100 Hz, no saturation under 120 Hz",
}


def _old_standard():
    src = subprocess.run(["git", "-C", ROOT, "show", f"{BEFORE_COMMIT}:shimmer/core/master/standard.py"],
                         capture_output=True, text=True, check=True).stdout
    path = os.path.join(tempfile.mkdtemp(), "standard_before.py")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(src)
    spec = importlib.util.spec_from_file_location("standard_before", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["standard_before"] = mod
    spec.loader.exec_module(mod)
    return mod


def _slug(path: str) -> str:
    stem = os.path.splitext(os.path.basename(path))[0].lower()
    return "".join(c if c.isalnum() else "-" for c in stem).strip("-").replace("--", "-")


def _loudest_span(y: np.ndarray, sr: int) -> tuple:
    n = int(SPAN_S * sr)
    if y.shape[0] <= n:
        return 0, y.shape[0]
    p = np.mean(y.astype(np.float64) ** 2, axis=1)
    c = np.concatenate([[0.0], np.cumsum(p)])
    hop = sr // 2
    starts = np.arange(0, y.shape[0] - n, hop)
    best = int(starts[np.argmax(c[starts + n] - c[starts])])
    return best, best + n


def _at_lufs(x: np.ndarray, sr: int) -> np.ndarray:
    y = x * 10 ** ((TEST_LUFS - meters.loudness(x, sr)) / 20)
    peak = float(np.max(np.abs(y))) or 1.0
    return y * (0.99 / peak) if peak > 0.99 else y


def main(argv) -> int:
    songs = [a for a in argv if a.lower().endswith(".wav")]
    if not songs:
        print(__doc__)
        return 1
    out = argv[argv.index("--out") + 1] if "--out" in argv else os.path.join(ROOT, "listening-test", "round-8")
    blind, renders = os.path.join(out, "blind"), os.path.join(out, "renders")
    os.makedirs(blind, exist_ok=True)
    os.makedirs(renders, exist_ok=True)
    render_mod = sys.modules["shimmer.core.render"]
    variants = {"before": _old_standard(), "after": NEW}
    rng = random.Random(20261114)
    key = {"how_to_listen": [
        "For each song, play A and B back to back. They are matched to the",
        "same loudness, so neither can win by being louder.",
        "Listen to the low end and the beat: which is cleaner and more solid,",
        "and does either one pump with the kick?",
        "Pick one per song (or 'same'), write it down, THEN read 'songs' below.",
    ], "songs": {}}
    for path in songs:
        x, sr = sf.read(path, dtype="float32", always_2d=True)
        slug = _slug(path)
        masters = {}
        for name, mod in variants.items():
            render_mod.standard = mod
            masters[name] = render(Source.from_array(x, sr), Settings()).audio
        render_mod.standard = NEW
        a, b = _loudest_span(masters["after"], sr)
        letters = ["A", "B"]
        rng.shuffle(letters)
        key["songs"][slug] = {"span_s": [round(a / sr, 1), round(b / sr, 1)], "letters": []}
        for letter, name in zip(letters, variants):
            clip = _at_lufs(masters[name][a:b], sr)
            sf.write(os.path.join(blind, f"{slug}-{letter}.wav"), clip, sr, subtype="PCM_24")
            sf.write(os.path.join(renders, f"{slug}-{name}.wav"), masters[name], sr, subtype="PCM_24")
            key["songs"][slug]["letters"].append({"letter": letter, "variant": name,
                                                  "what_it_is": MEANING[name]})
        key["songs"][slug]["letters"].sort(key=lambda d: d["letter"])
        print(f"{slug}: {a / sr:.0f}-{b / sr:.0f} s")
    with open(os.path.join(blind, "ANSWER-KEY.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(key, f, indent=1)
        f.write("\n")
    print(f"Listen in {blind}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
