"""What the release check says each service does with the file's level
(docs/MASTERING-SOURCES.md §2, checked 2026-09-12).

Interface: shimmer.core.master.release
    platform_changes(lufs) -> [{name, target_lufs, change_db, note}]
"""
from _contract import needs

pytestmark = needs("shimmer.core.master.release")


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
