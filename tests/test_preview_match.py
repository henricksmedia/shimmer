"""
Preview mastering level parity.

Live preview masters one loop slice at a time. Normalising that slice on
its own boosted quiet sections to the target even though the full run
applies one static gain for the whole file, so the Processed monitor
played a level the export never has and the A/B loudness match turned
it down by up to 6 dB. `master(..., loudness_ref=...)` fixes that by
applying the whole-file gain to the slice.

Run:  .venv\\Scripts\\python.exe -m pytest tests/test_preview_match.py -q
"""

from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shimmer.mastering import master, measure_loudness  # noqa: E402
from shimmer.params import MasterParams  # noqa: E402

SR = 44100


def _track(seconds: float = 30.0, seed: int = 0) -> np.ndarray:
    """A track whose first third is 12 dB quieter than the rest."""
    rng = np.random.default_rng(seed)
    n = int(SR * seconds)
    t = np.arange(n) / SR
    x = 0.2 * np.sin(2 * np.pi * 110 * t) + 0.05 * rng.standard_normal(n)
    env = np.ones(n)
    env[: n // 3] = 10 ** (-12 / 20)
    x = x * env
    return np.stack([x, x], axis=1).astype(np.float32)


def _mp(target: float = -14.0) -> MasterParams:
    mp = MasterParams()
    mp.enabled = True
    mp.target_lufs = target
    return mp


class TestPreviewMasteringGain:
    def test_slice_alone_is_normalised_to_target(self):
        x = _track()
        quiet = x[: int(8 * SR)]
        _, rep = master(quiet, SR, _mp())
        assert rep["gain_source"] == "measured"
        # On its own, the quiet slice is pulled all the way up to target.
        assert abs(rep["gain_db"] - (-14.0 - measure_loudness(quiet, SR)["lufs_i"])) < 0.05

    def test_reference_applies_whole_file_gain(self):
        x = _track()
        quiet = x[: int(8 * SR)]
        whole = measure_loudness(x, SR)["lufs_i"]
        sl = measure_loudness(quiet, SR)["lufs_i"]
        _, rep = master(quiet, SR, _mp(),
                        loudness_ref={"whole_lufs": whole, "slice_lufs": sl})
        _, rep_full = master(x, SR, _mp())
        assert rep["gain_source"] == "whole_file"
        # The slice now gets the same static gain the full run applies.
        assert abs(rep["gain_db"] - rep_full["gain_db"]) < 0.05
        assert rep["gain_db"] < rep_full["gain_db"] + 0.05

    def test_reference_tracks_upstream_level_changes(self):
        # If cleaning / tone curve moved the slice by +2 dB before
        # mastering, the estimate of the whole-file level moves with it.
        x = _track()
        quiet = x[: int(8 * SR)]
        whole = measure_loudness(x, SR)["lufs_i"]
        sl = measure_loudness(quiet, SR)["lufs_i"]
        boosted = (quiet * 10 ** (2 / 20)).astype(np.float32)
        _, rep = master(boosted, SR, _mp(),
                        loudness_ref={"whole_lufs": whole, "slice_lufs": sl})
        assert abs(rep["gain_db"] - (-14.0 - (whole + 2.0))) < 0.15

    def test_bad_reference_falls_back(self):
        x = _track()
        quiet = x[: int(8 * SR)]
        _, rep = master(quiet, SR, _mp(),
                        loudness_ref={"whole_lufs": float("-inf"), "slice_lufs": -20.0})
        assert rep["gain_source"] == "measured"
