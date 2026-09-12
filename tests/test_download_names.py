"""Re-processing an export never chains a second suffix on, for 1.x names
and 2.0 names alike, and without the old presets module
(docs/ARCHITECTURE.md §19.1 item 11, docs/API.md §4)."""
import inspect

from shimmer import tags as T


def test_2_0_names_lose_their_suffix():
    assert T.strip_shimmer_suffix("song_processed_ab12cd34") == "song"
    assert T.strip_shimmer_suffix("song_removed_ab12cd34") == "song"
    assert T.strip_shimmer_suffix("song_trimmed_ab12cd34") == "song"


def test_1x_names_still_lose_their_whole_suffix():
    assert T.strip_shimmer_suffix("my_song_generic_processed_deadbeef") == "my_song"
    assert T.strip_shimmer_suffix("my_song_suno_v5.5_processed_ab12cd34") == "my_song"
    assert T.strip_shimmer_suffix("song_vocal_glaze_plus_removed_ab12cd34") == "song"


def test_mixed_chains_unwind_completely():
    assert T.strip_shimmer_suffix("song_deep_scrub_processed_ab12cd34_processed_0123abcd") == "song"


def test_a_song_that_merely_ends_in_a_word_is_left_alone():
    assert T.strip_shimmer_suffix("the_processed_heart") == "the_processed_heart"
    assert T.strip_shimmer_suffix("song_processed_ABCDEF12") == "song_processed_ABCDEF12"


def test_the_old_preset_keys_are_frozen_not_imported():
    assert "from .presets" not in inspect.getsource(T)
    assert len(T.LEGACY_PRESET_KEYS) == 27
