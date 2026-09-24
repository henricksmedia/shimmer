"""Saved settings carry over from 1.x (docs/ARCHITECTURE.md §19.3).

An old preset turns on the card it maps to, a version-named preset gets its
current name, and card picks saved by 2.0 load as they were saved, so a
card turned off stays off.
"""
import json

import pytest

from shimmer import settings_store


@pytest.fixture()
def saved(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIMMER_CONFIG_DIR", str(tmp_path))

    def write(data):
        text = data if isinstance(data, str) else json.dumps(data)
        (tmp_path / "settings.json").write_text(text, encoding="utf-8")
        return settings_store.load_settings()
    return write


def test_an_old_preset_turns_on_its_card(saved):
    got = saved({"remember_settings": True, "preset": "suno_hash", "preset_strength": 0.8,
                 "mastering": {"enabled": True, "target": "cd"}})
    assert got["fixes"] == {"shimmer": 0.5}
    # Everything else as saved.
    assert got["mastering"] == {"enabled": True, "target": "cd"}
    assert got["preset"] == "suno_hash" and got["remember_settings"] is True


def test_a_version_named_preset_gets_its_current_name(saved):
    got = saved({"preset": "suno_v5_pro"})
    assert got["preset"] == "air_brittle"
    assert got["fixes"] == {"tones": 1.0}


def test_generic_turns_on_nothing(saved):
    assert saved({"preset": "generic"})["fixes"] == {}


def test_picks_saved_by_2_0_load_as_they_were(saved):
    # Turned off on purpose: the old preset does not bring its card back.
    assert saved({"preset": "suno_hash", "fixes": {}})["fixes"] == {}
    assert saved({"fixes": {"sibilance": 0.3}})["fixes"] == {"sibilance": 0.3}


def test_no_file_or_a_broken_one_is_empty(saved):
    assert settings_store.load_settings() == {}
    assert saved("{not json") == {}
    assert saved("[1, 2]") == {}


def test_an_unchosen_streaming_target_from_before_2_0_2_becomes_commercial(tmp_path, monkeypatch):
    # 1.x saved "streaming" as its default, and 2.0.0-2.0.1 kept it, so
    # upgraders mastered 5 dB under the Commercial default.
    monkeypatch.setenv("SHIMMER_CONFIG_DIR", str(tmp_path))
    old = {"fixes": {}, "mastering": {"enabled": True, "target": "streaming"}}
    (tmp_path / "settings.json").write_text(json.dumps(old), encoding="utf-8")
    assert settings_store.load_settings()["mastering"]["target"] == "cd"


def test_a_streaming_target_saved_from_2_0_2_on_is_kept(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIMMER_CONFIG_DIR", str(tmp_path))
    settings_store.save_settings({"fixes": {}, "mastering": {"enabled": True, "target": "streaming"}})
    loaded = settings_store.load_settings()
    assert loaded["mastering"]["target"] == "streaming"
    assert loaded["settings_version"] == settings_store.SETTINGS_VERSION
