"""The rules the screens show come from one place, and old settings carry over.

Interface: shimmer.core.catalog
    CARDS              the "What do you hear?" cards (ARCHITECTURE §19.3):
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
import pytest

from _contract import needs

catalog_ = needs("shimmer.core.catalog")
settings_ = needs("shimmer.core.settings")

CARD_KEYS = {"shimmer", "tones", "sibilance", "clicks", "harshness", "phasiness",
             "mud", "air", "loudness"}
# STYLE.md: never name a third-party service in anything the user reads.
SERVICE_NAMES = ("suno", "udio", "spotify", "distrokid", "landr", "apple music",
                 "youtube", "tidal", "soundcloud", "deezer")

# Every 1.x preset and version-named alias, and the card it becomes
# (ARCHITECTURE §19.3). Copied out by hand from shimmer/presets.py, not
# imported, so the old module can be deleted in Step 7.
OLD_PRESETS = {
    "cymbal_sheen": "tones", "laser_whistle": "tones", "air_brittle": "tones",
    "checkerboard_grid": "tones",
    "suno_hash": "shimmer", "broadband_fizz": "shimmer", "presence_haze": "shimmer",
    "echo_sheen": "shimmer", "cymbal_chatter": "shimmer", "phantom_cymbal": "shimmer",
    "vocal_glaze_plus": "shimmer", "deep_scrub": "shimmer",
    "sibilance_rattle": "sibilance", "vocal_glaze": "sibilance",
    "harsh_veil": "harshness",
    "muddy_boxy": "mud",
    "dark_mix_rescue": "air",
    "reverb_flutter": "phasiness",
}
OLD_ALIASES = {
    "suno_v3": "tones", "suno_v3.5": "tones", "suno_v4": "shimmer",
    "suno_v4.5": "shimmer", "suno_v5": "tones", "suno_v5_pro": "tones",
    "suno_v5.5": "phasiness", "suno_cymbal": "tones",
}


@catalog_
def test_the_nine_cards_are_there():
    from shimmer.core import catalog
    keys = [c.key for c in catalog.CARDS]
    assert len(keys) == len(set(keys))
    assert set(keys) == CARD_KEYS


@catalog_
def test_every_card_is_complete_and_points_at_a_real_tool():
    from shimmer.core import catalog
    for c in catalog.CARDS:
        assert c.label and c.descriptor and c.icon, c.key
        assert c.group in ("artifacts", "tone_level"), c.key
        assert c.tool is None or c.tool in catalog.TOOLS, c.key


@catalog_
def test_no_service_names_in_anything_the_user_reads():
    from shimmer.core import catalog
    text = [c.label + " " + c.descriptor for c in catalog.CARDS]
    text += [t.label + " " + t.sublabel for t in catalog.LOUDNESS_TARGETS]
    for line in text:
        for name in SERVICE_NAMES:
            assert name not in line.lower(), line


@catalog_
def test_the_loudness_choices_stay_as_they_are():
    from shimmer.core import catalog
    assert {t.key: t.lufs for t in catalog.LOUDNESS_TARGETS} == {
        "streaming": -14.0, "loud": -11.0, "cd": -9.0}
    assert sum(1 for t in catalog.LOUDNESS_TARGETS if t.default) == 1


@catalog_
def test_commercial_is_the_default():
    # Decided by the author, 2026-09-12 (ARCHITECTURE §19.2 D1): master at
    # the level most released songs sit at.
    from shimmer.core import catalog
    default = [t for t in catalog.LOUDNESS_TARGETS if t.default]
    assert [t.key for t in default] == ["cd"]
    assert "commercial" in default[0].label.lower()


@catalog_
def test_formats_carry_codec_aware_ceilings():
    from shimmer.core import catalog
    ceilings = {f.key: f.ceiling_dbtp for f in catalog.FORMATS}
    assert set(ceilings) == {"wav", "wav16", "flac", "mp3", "ogg", "m4a"}
    assert {f.key for f in catalog.FORMATS if f.lossy} == {"mp3", "ogg", "m4a"}
    for key in ("wav", "wav16", "flac"):
        assert ceilings[key] == -1.0
    # Lossy ceilings are set from each codec's measured overshoot
    # (ARCHITECTURE §19.1 item 12); the export tests hold the decoded file
    # to -1.0 dBTP. Here: never looser than -1.5.
    for key in ("mp3", "ogg", "m4a"):
        assert ceilings[key] <= -1.5


@catalog_
def test_eq_limits_are_stated_once():
    from shimmer.core import catalog
    assert catalog.EQ_LIMITS["max_bands"] >= 1
    assert catalog.EQ_LIMITS["gain_limit_db"] > 0


@settings_
def test_settings_survive_a_round_trip():
    from shimmer.core.settings import Settings
    s = Settings()
    assert Settings.from_dict(s.to_dict()) == s


@settings_
@pytest.mark.parametrize("old, card", sorted({**OLD_PRESETS, **OLD_ALIASES}.items()))
def test_old_presets_carry_over_to_the_right_card(old, card):
    from shimmer.core.settings import migrate
    assert set(migrate({"preset": old}).fixes) == {card}


@settings_
def test_generic_carries_over_as_no_fix():
    from shimmer.core.settings import migrate
    assert migrate({"preset": "generic"}).fixes == {}


@settings_
def test_a_remix_projects_cleanup_carries_over():
    from shimmer.core.settings import migrate
    assert set(migrate({"cleaning": {"preset": "muddy_boxy"}}).fixes) == {"mud"}


@settings_
def test_migration_keeps_the_loudness_choice():
    from shimmer.core.settings import migrate
    assert migrate({"preset": "generic", "mastering": {"target": "cd"}}).loudness_target == "cd"


@settings_
def test_an_unknown_preset_migrates_without_error():
    from shimmer.core.settings import Settings, migrate
    s = migrate({"preset": "no_such_preset"})
    assert isinstance(s, Settings)
    assert set(s.fixes) <= CARD_KEYS
