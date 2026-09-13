"""What the release check says each service does with the file's level
(docs/MASTERING-SOURCES.md §2, checked 2026-09-12), and whether the bass
holds up in mono (§5).

Interface: shimmer.core.master.release
    platform_changes(lufs) -> [{name, target_lufs, change_db, note}]
    low_end_check(y, sr) -> check dict, or None for a mono file
"""
import numpy as np

from _contract import needs

pytestmark = needs("shimmer.core.master.release")

SR = 48000


def _tone(hz, db=-12.0, seconds=6.0):
    t = np.arange(int(SR * seconds)) / SR
    return 10.0 ** (db / 20.0) * np.sin(2.0 * np.pi * hz * t)


def _stereo(left, right):
    return np.stack([left, right], axis=1).astype(np.float32)


def test_a_loud_master_is_turned_down_everywhere():
    from shimmer.core.master.release import platform_changes
    rows = {p["name"]: p for p in platform_changes(-9.0)}
    assert len(rows) == 6
    for p in rows.values():
        assert p["note"].startswith("turned down"), p


def test_only_the_services_that_turn_quiet_tracks_up_say_so():
    # Amazon, Tidal and Deezer do not turn a quiet track up; YouTube never did.
    from shimmer.core.master.release import platform_changes
    rows = {p["name"]: p for p in platform_changes(-18.0)}
    for name in ("YouTube", "Amazon Music", "Tidal", "Deezer"):
        assert rows[name]["note"] == "played as is (no boost)", rows[name]
    assert rows["Spotify"]["note"].startswith("turned up")


def test_centred_bass_passes():
    from shimmer.core.master.release import low_end_check
    mix = _tone(55.0) + _tone(2000.0, db=-18.0)
    c = low_end_check(_stereo(mix, mix), SR)
    assert c["key"] == "low_end" and c["status"] == "pass", c
    assert c["value"] == "0.0 dB in mono", c


def test_some_width_in_the_bass_still_passes():
    # Centre 55 Hz with a quieter 70 Hz in the sides: the bass drops about
    # 1 dB in mono, nothing cancels.
    from shimmer.core.master.release import low_end_check
    centre, side = _tone(55.0), _tone(70.0, db=-18.0)
    c = low_end_check(_stereo(centre + side, centre - side), SR)
    assert c["status"] == "pass", c


def test_out_of_phase_bass_warns_even_when_the_whole_mix_reads_fine():
    # The top is in phase and louder, so the whole-band correlation is
    # positive and the whole-band mono check passes; the bass alone cancels.
    from shimmer.core import stereo_correlation
    from shimmer.core.master.release import low_end_check, release_check
    bass, top = _tone(55.0, db=-14.0), _tone(2000.0, db=-8.0)
    y = _stereo(top + bass, top - bass)
    assert stereo_correlation(y) > 0.2
    c = low_end_check(y, SR)
    assert c["status"] == "warn", c
    assert c["value"] == "cancels in mono", c
    rows = {r["key"]: r for r in release_check(y, SR, correlation=stereo_correlation(y))["checks"]}
    assert rows["mono"]["status"] == "pass"
    assert rows["low_end"]["status"] == "warn"


def test_a_partly_out_of_phase_bass_says_how_much_it_drops():
    # Side louder than centre below 100 Hz: correlation there is negative.
    from shimmer.core.master.release import low_end_check
    centre, side = _tone(55.0, db=-20.0), _tone(55.0, db=-14.0)
    c = low_end_check(_stereo(centre + side, centre - side), SR)
    assert c["status"] == "warn", c
    # Mono keeps the centre only: 10*log10(c^2 / (c^2 + s^2)) = -7.0 dB.
    assert c["value"] == "−7.0 dB in mono", c


def test_no_bass_to_judge_is_noted_not_graded():
    from shimmer.core.master.release import low_end_check
    top = _tone(2000.0)
    c = low_end_check(_stereo(top, -top), SR)
    assert c["status"] == "info", c


def test_a_mono_file_has_no_low_end_row():
    from shimmer.core.master.release import low_end_check, release_check
    assert low_end_check(_tone(55.0).astype(np.float32), SR) is None
    keys = {r["key"] for r in release_check(_tone(55.0).astype(np.float32), SR)["checks"]}
    assert "low_end" not in keys
