"""The rules the screens show come from one place, and old settings carry over.

Interface: shimmer.core.catalog
    CARDS              the "What do you hear?" cards (ARCHITECTURE §13.2a):
                       .key .label .descriptor .icon .group .tool .band_hz
    TOOLS              names of the tools a card may turn on
    LOUDNESS_TARGETS   .key .lufs .label .sublabel .default
    FORMATS            .key .ext .ceiling_dbtp .lossy
    EQ_LIMITS          {"max_bands": int, "gain_limit_db": float}
Interface: shimmer.core.settings
    Settings           dataclass; .fixes {card key: amount}, .auto,
                       .mastering, .loudness_target, .format
    Settings.to_dict() / Settings.from_dict(d) / Settings.bypass()
    Settings.replace(**changes) -> a copy with those fields changed
    migrate(old_saved_settings: dict) -> Settings
"""
import importlib.util

import pytest

pytestmark = pytest.mark.xfail(importlib.util.find_spec("shimmer.core") is None,
                               reason="shimmer.core is not built yet (rebuild Step 4)",
                               strict=True)

CARD_KEYS = {"shimmer", "tones", "sibilance", "clicks", "harshness", "phasiness",
             "mud", "air", "loudness"}
# STYLE.md: never name a third-party service in anything the user reads.
SERVICE_NAMES = ("suno", "udio", "spotify", "distrokid", "landr", "apple music",
                 "youtube", "tidal", "soundcloud", "deezer")


def test_the_nine_cards_are_there():
    from shimmer.core import catalog
    keys = [c.key for c in catalog.CARDS]
    assert len(keys) == len(set(keys))
    assert set(keys) == CARD_KEYS


def test_every_card_is_complete_and_points_at_a_real_tool():
    from shimmer.core import catalog
    for c in catalog.CARDS:
        assert c.label and c.descriptor and c.icon, c.key
        assert c.group in ("artifacts", "tone_level"), c.key
        assert c.tool is None or c.tool in catalog.TOOLS, c.key


def test_no_service_names_in_anything_the_user_reads():
    from shimmer.core import catalog
    text = [c.label + " " + c.descriptor for c in catalog.CARDS]
    text += [t.label + " " + t.sublabel for t in catalog.LOUDNESS_TARGETS]
    for line in text:
        for name in SERVICE_NAMES:
            assert name not in line.lower(), line


def test_the_loudness_choices_stay_as_they_are():
    from shimmer.core import catalog
    assert {t.key: t.lufs for t in catalog.LOUDNESS_TARGETS} == {
        "streaming": -14.0, "loud": -11.0, "cd": -9.0}
    assert sum(1 for t in catalog.LOUDNESS_TARGETS if t.default) == 1


def test_formats_carry_codec_aware_ceilings():
    from shimmer.core import catalog
    assert {f.key: f.ceiling_dbtp for f in catalog.FORMATS} == {
        "wav": -1.0, "wav16": -1.0, "flac": -1.0,
        "mp3": -1.5, "ogg": -1.5, "m4a": -1.5}
    assert {f.key for f in catalog.FORMATS if f.lossy} == {"mp3", "ogg", "m4a"}


def test_eq_limits_are_stated_once():
    from shimmer.core import catalog
    assert catalog.EQ_LIMITS["max_bands"] >= 1
    assert catalog.EQ_LIMITS["gain_limit_db"] > 0


def test_settings_survive_a_round_trip():
    from shimmer.core.settings import Settings
    s = Settings()
    assert Settings.from_dict(s.to_dict()) == s


@pytest.mark.parametrize("old, card", [
    ("generic", "tones"), ("cymbal_sheen", "tones"), ("laser_whistle", "tones"),
    ("air_brittle", "tones"), ("checkerboard_grid", "tones"),
    ("suno_hash", "shimmer"), ("broadband_fizz", "shimmer"), ("deep_scrub", "shimmer"),
    ("sibilance_rattle", "sibilance"), ("vocal_glaze", "sibilance"),
    ("harsh_veil", "sibilance"), ("muddy_boxy", "mud"), ("dark_mix_rescue", "air"),
    ("reverb_flutter", "phasiness"),
])
def test_old_presets_carry_over_to_the_right_card(old, card):
    from shimmer.core.settings import migrate
    assert card in migrate({"preset": old}).fixes


def test_migration_keeps_the_loudness_choice():
    from shimmer.core.settings import migrate
    assert migrate({"preset": "generic", "mastering": {"target": "cd"}}).loudness_target == "cd"


def test_an_unknown_preset_migrates_without_error():
    from shimmer.core.settings import Settings, migrate
    s = migrate({"preset": "no_such_preset"})
    assert isinstance(s, Settings)
    assert set(s.fixes) <= CARD_KEYS
