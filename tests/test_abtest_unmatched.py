"""A loudness check writes every arm at its own level, and says so.

Level matching is right for "which sounds better" and wrong for "does this
setting make it louder": it would erase the very thing being checked. These
pin both behaviours, so a later edit cannot quietly turn one into the other.
"""
import json
import os

import numpy as np
import pytest
import soundfile as sf

from shimmer import abtest
from shimmer.mastering import measure_loudness

SR = 48000


@pytest.fixture
def bench(tmp_path, monkeypatch):
    monkeypatch.setattr(abtest, "BENCH", str(tmp_path / "ab"))
    os.makedirs(abtest.BENCH, exist_ok=True)
    return abtest.BENCH


def _tone(db):
    t = np.arange(SR * 2) / SR
    x = 10.0 ** (db / 20.0) * np.sin(2 * np.pi * 1000.0 * t)
    return np.stack([x, x], axis=1)


def _key(bench, set_id):
    with open(os.path.join(bench, set_id, "ANSWER-KEY.json"), encoding="utf-8") as f:
        return json.load(f)


def test_an_unmatched_set_keeps_each_arm_at_its_own_level(bench):
    m = abtest.build("lvl", "t", [("quiet", _tone(-20.0)), ("loud", _tone(-10.0))], SR,
                     match_levels=False, question="Which is loudest?",
                     choice="{L} is loudest", tie_label="Can't tell")
    key = _key(bench, "lvl")
    levels = {}
    for row in key["arms"]:
        assert row["gain_db"] == 0.0
        assert row["lufs_after"] == row["lufs_before"]
        y, sr = sf.read(os.path.join(bench, "lvl", row["file"]), always_2d=True)
        on_disk = measure_loudness(y, sr)["lufs_i"]
        assert abs(on_disk - row["lufs_before"]) < 0.05
        levels[row["true_label"]] = on_disk
    assert abs((levels["loud"] - levels["quiet"]) - 10.0) < 0.1
    assert m["level_matched"] is False
    assert m["matched_lufs"] is None


def test_an_unmatched_set_carries_its_question_to_the_page(bench):
    abtest.build("lvl", "t", [("quiet", _tone(-20.0)), ("loud", _tone(-10.0))], SR,
                 match_levels=False, question="Which is loudest?",
                 choice="{L} is loudest", tie_label="Can't tell")
    served = abtest.manifest("lvl")
    assert served["level_matched"] is False
    assert served["question"] == "Which is loudest?"
    assert served["choice"] == "{L} is loudest"
    assert served["tie_label"] == "Can't tell"
    json.dumps(served)  # the route serves it as JSON


def test_the_default_still_matches_levels(bench):
    m = abtest.build("mt", "t", [("quiet", _tone(-20.0)), ("loud", _tone(-10.0))], SR)
    key = _key(bench, "mt")
    assert m["level_matched"] is True
    assert m["matched_lufs"] is not None
    assert len({row["lufs_after"] for row in key["arms"]}) == 1
    assert abtest.manifest("mt")["question"] is None
