"""The listening bench must refuse a comparison it cannot make honestly.

Every case here is a way the bench could hand back a verdict that means
nothing: two arms at different speeds, a set of silence, a set id that reads
or writes outside the bench folder. None of them announced themselves before.
"""
from __future__ import annotations

import os

import numpy as np
import pytest

from shimmer import abtest


SR = 48000


def _tone(seconds: float = 3.0, gain: float = 0.3, sr: int = SR) -> np.ndarray:
    t = np.arange(int(seconds * sr)) / sr
    x = np.stack([np.sin(2 * np.pi * 220 * t), np.sin(2 * np.pi * 221 * t)], 1)
    rng = np.random.default_rng(0)
    return (x + rng.standard_normal(x.shape) * 0.01) * gain


@pytest.fixture()
def bench(tmp_path, monkeypatch):
    monkeypatch.setattr(abtest, "BENCH", str(tmp_path / "ab"))
    os.makedirs(abtest.BENCH, exist_ok=True)
    return abtest.BENCH


# ── the comparison itself ────────────────────────────────────────────────

def test_builds_a_normal_set(bench):
    m = abtest.build("t-ok", "T", [("a", _tone()), ("b", _tone(gain=0.15))], SR)
    assert len(m["arms"]) == 2
    assert m["matched_lufs"] < 0 and np.isfinite(m["matched_lufs"])
    assert {a["letter"] for a in m["arms"]} == {"A", "B"}
    for a in m["arms"]:
        assert os.path.isfile(os.path.join(bench, "t-ok", a["file"]))


def test_arm_at_another_sample_rate_is_refused(bench):
    """Written at the set's rate it would play at the wrong speed, and the
    pitch difference would swamp the thing being judged."""
    with pytest.raises(ValueError, match="wrong speed"):
        abtest.build("t-sr", "T",
                     [("a", _tone(), 48000), ("b", _tone(), 44100)], 48000)


def test_silent_arm_is_refused(bench):
    """A silent arm measures -inf LUFS, and matching to it multiplies every
    arm by zero — a set of silence that also cannot be sent as JSON."""
    with pytest.raises(ValueError, match="silent"):
        abtest.build("t-silent", "T",
                     [("a", _tone()), ("b", np.zeros((SR * 3, 2)))], SR)


def test_mismatched_channels_are_refused(bench):
    with pytest.raises(ValueError, match="channel count"):
        abtest.build("t-ch", "T",
                     [("a", _tone()), ("b", _tone()[:, 0])], SR)


def test_two_arms_with_one_label_are_refused(bench):
    with pytest.raises(ValueError, match="share a label"):
        abtest.build("t-dup", "T", [("a", _tone()), ("a", _tone())], SR)


def test_residual_naming_a_missing_arm_is_refused(bench):
    with pytest.raises(ValueError, match="residual asks for"):
        abtest.build("t-res", "T", [("a", _tone()), ("b", _tone())], SR,
                     residual_of=("a", "nope"))


def test_manifest_serialises_as_json(bench):
    import json
    m = abtest.build("t-json", "T", [("a", _tone()), ("b", _tone(gain=.1))], SR)
    json.dumps(m, allow_nan=False)          # what the API route has to do


# ── the bench folder is the only folder ──────────────────────────────────

@pytest.mark.parametrize("bad", ["..", ".", "", "....", "-x", "../t-ok",
                                 ".hidden", "a" * 90])
def test_bad_ids_reach_nothing(bench, bad):
    abtest.build("t-ok", "T", [("a", _tone()), ("b", _tone(gain=.1))], SR)
    assert abtest._safe(bad) == ""
    assert abtest.manifest(bad) is None
    assert abtest.reveal(bad) is None
    assert abtest.scores(bad) == {"rounds": []}
    assert abtest.audio_path(bad, "arm0.wav") is None
    assert abtest.score(bad, {"preferred": "A"})["ok"] is False


def test_a_bad_id_writes_nothing_outside_the_bench(bench):
    parent = os.path.dirname(os.path.abspath(bench))
    abtest.score("..", {"preferred": "A", "note": "should not land"})
    assert not os.path.exists(os.path.join(parent, "SCORES.json"))


@pytest.mark.parametrize("bad", ["../x.wav", "..\\x.wav", ".wav", "....wav",
                                 "arm0.txt", "arm0.wav\x00.txt",
                                 # The real name is a fingerprint: arm1 is the
                                 # same version in every set of a group, so
                                 # letter-to-file is letter-to-answer.
                                 "arm0.wav", "arm1.wav", "residual.wav"])
def test_bad_filenames_reach_nothing(bench, bad):
    abtest.build("t-ok", "T", [("a", _tone()), ("b", _tone(gain=.1))], SR)
    assert abtest.audio_path("t-ok", bad) is None


def test_a_letter_resolves(bench):
    abtest.build("t-ok", "T", [("a", _tone()), ("b", _tone(gain=.1))], SR)
    p = abtest.audio_path("t-ok", "A.wav")
    assert p and os.path.isfile(p)
    assert os.path.realpath(p).startswith(os.path.realpath(bench) + os.sep)


def test_the_served_manifest_names_no_file_and_no_loudness(bench):
    """Everything that identified an arm is gone from the wire."""
    abtest.build("t-ok", "T", [("a", _tone()), ("b", _tone(gain=.1))], SR)
    m = abtest.manifest("t-ok")
    for a in m["arms"]:
        assert a["file"] == a["letter"] + ".wav"
        assert "lufs_before" not in a and "gain_db" not in a
    # and the fairness claim survives without them
    assert m["fair"]["arms"] == 2
    assert m["fair"]["turned_up"] == 0
    assert m["fair"]["max_attenuation_db"] <= 0


def test_reveal_gives_back_the_rows_the_manifest_withheld(bench):
    abtest.build("t-ok", "T", [("a", _tone()), ("b", _tone(gain=.1))], SR)
    r = abtest.reveal("t-ok")
    assert {a["letter"] for a in r["arms"]} == {"A", "B"}
    assert all("lufs_before" in a and "gain_db" in a for a in r["arms"])


# ── verdicts ─────────────────────────────────────────────────────────────

def test_a_verdict_with_junk_numbers_is_still_kept(bench):
    """The words in the note are the valuable part. A bad number field must
    not throw away the whole judgement."""
    abtest.build("t-ok", "T", [("a", _tone()), ("b", _tone(gain=.1))], SR)
    r = abtest.score("t-ok", {"preferred": "A", "switches": "lots",
                              "seconds": None, "note": "B had more air"})
    assert r["ok"] is True
    row = abtest.scores("t-ok")["rounds"][-1]
    assert row["switches"] == 0 and row["seconds_listened"] == 0.0
    assert row["note"] == "B had more air"


def test_extra_fields_ride_along(bench):
    """The ABX result is stored beside the preference, not instead of it."""
    abtest.build("t-ok", "T", [("a", _tone()), ("b", _tone(gain=.1))], SR)
    abtest.score("t-ok", {"preferred": "A", "trials": 12, "correct": 11,
                          "p_value": 0.0032})
    row = abtest.scores("t-ok")["rounds"][-1]
    assert row["trials"] == 12 and row["correct"] == 11
    assert row["p_value"] == pytest.approx(0.0032)


def test_scores_are_appended_not_replaced(bench):
    abtest.build("t-ok", "T", [("a", _tone()), ("b", _tone(gain=.1))], SR)
    abtest.score("t-ok", {"preferred": "A"})
    abtest.score("t-ok", {"preferred": "B"})
    assert len(abtest.scores("t-ok")["rounds"]) == 2


# ── the real bench on disk still reads ───────────────────────────────────

def test_the_sets_already_on_disk_still_open():
    """Thirty-six sets exist. None of them may be rejected by the new rules."""
    if not os.path.isdir(abtest.BENCH):
        pytest.skip("no bench on this machine")
    listed = abtest.sets()
    for row in listed:
        m = abtest.manifest(row["id"])
        assert m is not None, row["id"]
        for a in m["arms"]:
            assert abtest.audio_path(row["id"], a["file"]), (row["id"], a["file"])
