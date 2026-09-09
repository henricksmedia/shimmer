"""
Export tags (tags.py) test suite.

Covers:
  1. Filename stems: Shimmer's export suffixes strip cleanly, even chained.
  2. Building: the file's own tags win in "fill" mode, defaults fill the
     blanks, a typed title always wins, the note lands once in the comment.
  3. Round trips: WAV (RIFF INFO + ID3 chunk), FLAC and OGG (Vorbis
     comments) write and read back; audio data is untouched.

Run:  .venv\\Scripts\\python.exe -m pytest tests/test_tags.py -q
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pytest
import soundfile as sf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shimmer import tags as T

SR = 44100


def _tone(dur: float = 0.5) -> np.ndarray:
    t = np.arange(int(SR * dur)) / SR
    x = 0.3 * np.sin(2 * np.pi * 440 * t)
    return np.stack([x, x], axis=1).astype(np.float32)


def test_strip_shimmer_suffix_and_title():
    assert T.strip_shimmer_suffix("song_vocal_glaze_plus_processed_db7f2d83") == "song"
    chained = "Alive_Again__LYRICS_vocal_glaze_plus_processed_db7f2d83_sibilance_rattle_processed_e3ec48de"
    assert T.strip_shimmer_suffix(chained) == "Alive_Again__LYRICS"
    assert T.strip_shimmer_suffix("plain_name") == "plain_name"
    assert T.strip_shimmer_suffix("song_generic_trimmed_0123abcd") == "song"
    assert T.title_from_stem(chained) == "Alive Again LYRICS"


def test_build_fill_mode_keeps_source_and_fills_blanks():
    src = {"title": "Alive Again", "artist": "Someone Else", "comment": "take 3"}
    d = {"artist": "The Treq", "album": "Leave The World Behind", "year": "2026",
         "genre": "Electronic"}
    out = T.build_tags(src, d, title_hint="ignored_stem", note="Shimmer 1: pass 1")
    assert out["title"] == "Alive Again"
    assert out["artist"] == "Someone Else"          # the file's own tag wins
    assert out["album_artist"] == "Someone Else"    # falls back to artist
    assert out["album"] == "Leave The World Behind"
    assert out["year"] == "2026"
    assert out["copyright"] == "© 2026 Someone Else"
    assert out["comment"] == "take 3\nShimmer 1: pass 1"
    assert out["software"] == "Shimmer"


def test_build_overwrite_mode_typed_title_and_single_note():
    src = {"title": "Old", "artist": "Old Artist", "comment": "Shimmer 1: pass 1"}
    d = {"mode": "overwrite", "artist": "The Treq", "title": "New Title"}
    out = T.build_tags(src, d, note="Shimmer 1: pass 1")
    assert out["title"] == "New Title"
    assert out["artist"] == "The Treq"
    assert out["comment"].count("Shimmer 1: pass 1") == 1
    # No note when notes are off; title from the stem when nothing else.
    out2 = T.build_tags({}, {"notes": False}, title_hint="my_song_generic_processed_deadbeef",
                        note="Shimmer 1: pass 1")
    assert out2["title"] == "my song"
    assert "comment" not in out2


def test_note_text():
    n = T.shimmer_note("Shimmer 1.4", "pass 2", "Sibilance rattle", 0.8, True, -14.0, -1.0, eq_bands=3)
    assert n == "Shimmer 1.4: pass 2, Sibilance rattle 80%, EQ 3 bands, mastered -14 LUFS / -1 dBTP"
    assert T.shimmer_note("Shimmer", "pass 1", "Vocal glaze", 1.0, False, None, None) == \
        "Shimmer: pass 1, Vocal glaze 100%, cleaning only"


@pytest.mark.parametrize("ext", [".wav", ".flac", ".ogg"])
def test_round_trip(tmp_path, ext):
    path = str(tmp_path / f"t{ext}")
    x = _tone()
    sf.write(path, x, SR, subtype="PCM_16" if ext != ".ogg" else None)
    tags = {"title": "Alive Again", "artist": "The Treq", "album_artist": "The Treq",
            "album": "Leave The World Behind", "genre": "Electronic", "year": "2026",
            "track": "3", "comment": "line one\nShimmer 1.4: pass 2, mastered",
            "copyright": "© 2026 The Treq", "isrc": "USABC2600001",
            "software": "Shimmer 1.4"}
    rep = T.write_tags(path, tags)
    assert rep["written"], rep
    back = T.read_tags(path)
    for k in ("title", "artist", "album", "genre", "year", "copyright"):
        assert back.get(k) == tags[k], (k, back)
    assert back.get("comment", "").startswith("line one")
    # Audio is untouched.
    y, sr2 = sf.read(path, dtype="float32", always_2d=True)
    assert sr2 == SR and y.shape[0] == x.shape[0]
    if ext != ".ogg":
        assert np.allclose(y, x, atol=1e-3)
    # Writing again replaces, never duplicates.
    tags["title"] = "Alive Again (master)"
    T.write_tags(path, tags)
    assert T.read_tags(path)["title"] == "Alive Again (master)"


def test_wav_has_both_riff_info_and_id3(tmp_path):
    path = str(tmp_path / "both.wav")
    sf.write(path, _tone(), SR, subtype="PCM_24")
    T.write_tags(path, {"title": "Both", "artist": "The Treq", "software": "Shimmer"})
    with sf.SoundFile(path) as f:
        assert f.title == "Both"
        assert f.artist == "The Treq"
    from mutagen.wave import WAVE
    w = WAVE(path)
    assert str(w.tags["TIT2"]) == "Both"
    assert str(w.tags["TPE1"]) == "The Treq"
    y, _ = sf.read(path, dtype="float32", always_2d=True)
    assert y.shape[0] == _tone().shape[0]


def test_read_unknown_or_missing_never_raises(tmp_path):
    assert T.read_tags(str(tmp_path / "nope.wav")) == {}
    p = tmp_path / "junk.mp3"
    p.write_bytes(b"not audio at all")
    assert T.read_tags(str(p)) == {}
    assert T.write_tags(str(tmp_path / "x.aac"), {"title": "t"})["written"] is False


class TestExportNoteTruthfulness:
    """The note is written permanently into files handed to other people, so a
    false entry is worse than a missing one. Both cases below shipped once."""

    def test_server_set_analysis_fields_are_not_reported_as_tweaks(self):
        """`cutoff_hz` is set per file by the server from bandwidth analysis,
        not by any control. Every bandlimited source produced a note reading
        `tweaks cutoff_hz 16193`, advertising a knob that does not exist and
        eating one of the note's limited slots."""
        from shimmer.params import preset_overrides
        from shimmer.presets import get_preset
        p = get_preset("generic")
        assert preset_overrides(p, "generic", 1.0) == []
        p.cutoff_hz = 16193.0
        assert preset_overrides(p, "generic", 1.0) == []

    def test_a_real_tweak_still_shows_next_to_an_analysis_field(self):
        from shimmer.params import preset_overrides
        from shimmer.presets import get_preset
        p = get_preset("suno_hash")
        p.deharsh = 0.66
        p.cutoff_hz = 16193.0
        assert preset_overrides(p, "suno_hash", 1.0) == ["deharsh 0.66"]

    def test_diffing_against_a_rounded_strength_fabricates_tweaks(self):
        """Guards the shape of the bug, so the fix cannot be undone quietly:
        scaling by an exact strength and rebuilding the baseline from a
        2-decimal copy makes every scaled field differ. Batch and album mode
        both did this, listing the whole preset recipe as user edits."""
        from shimmer.params import preset_overrides, apply_preset_strength
        from shimmer.presets import get_preset
        exact = 1.0625
        p = get_preset("vocal_glaze_plus")
        apply_preset_strength(p, exact)
        assert preset_overrides(p, "vocal_glaze_plus", exact) == []
        assert len(preset_overrides(p, "vocal_glaze_plus", round(exact, 2))) > 5
