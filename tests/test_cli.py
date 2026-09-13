"""The command-line tool on the new engine: one file through render() and
export(), with the 1.x commands still working (shimmer/cli.py)."""
from __future__ import annotations

import numpy as np
import pytest

from shimmer import cli, core

SR = 48000


def _mix(seed=0, level=0.2, seconds=4.0):
    rng = np.random.default_rng(seed)
    n = int(SR * seconds)
    t = np.arange(n) / SR
    x = 0.5 * np.sin(2 * np.pi * 110 * t) + 0.3 * rng.standard_normal(n)
    y = np.stack([x, 0.9 * x + 0.1 * rng.standard_normal(n)], axis=1)
    return (level * y / np.max(np.abs(y))).astype(np.float32)


@pytest.fixture()
def song(tmp_path):
    soundfile = pytest.importorskip("soundfile")
    path = tmp_path / "song.wav"
    soundfile.write(str(path), _mix(), SR, subtype="PCM_24")
    return path


def _args(*argv):
    return cli._build_parser().parse_args(list(argv))


def test_the_file_is_the_engines_render(song, tmp_path):
    out = tmp_path / "out.wav"
    assert cli.main([str(song), str(out), "--target", "loud"]) == 0
    expected = core.render(core.Source.load(str(song)), core.Settings(loudness_target="loud"))
    got, sr = core.load_audio(str(out))
    assert sr == expected.sr
    assert float(np.max(np.abs(got - expected.audio))) < 2.0 ** -22


def test_a_plain_run_does_not_master(song, tmp_path):
    # As in 1.x: mastering only when --master or --target asks for it.
    s = cli.settings_from_args(_args(str(song), "out.wav"))
    assert s.mastering is False
    out = tmp_path / "plain.wav"
    assert cli.main([str(song), str(out)]) == 0
    before = core.meters.loudness(core.load_audio(str(song))[0], SR)
    after = core.meters.loudness(core.load_audio(str(out))[0], SR)
    assert abs(after - before) < 0.5


def test_master_alone_uses_the_apps_default_target():
    s = cli.settings_from_args(_args("a.wav", "b.wav", "--master"))
    assert s.mastering and s.loudness_target == core.catalog.DEFAULT_LOUDNESS
    assert cli.settings_from_args(_args("a.wav", "b.wav", "--target", "cd", "--no-master")).mastering is False


def test_the_format_and_its_ceiling_follow_the_extension():
    for ext, key in ((".wav", "wav"), (".flac", "flac"), (".mp3", "mp3"),
                     (".ogg", "ogg"), (".m4a", "m4a")):
        s = cli.settings_from_args(_args("a.wav", "b" + ext, "--master"))
        assert s.format == key
    assert core.catalog.output_format("mp3").ceiling_dbtp == -2.0
    assert cli.settings_from_args(_args("a.wav", "b.wav", "--release")).format == "wav16"
    with pytest.raises(SystemExit):
        cli.main(["a.wav", "b.mp3", "--release"])


def test_a_1_x_preset_turns_on_its_card():
    s = cli.settings_from_args(_args("a.wav", "b.wav", "--preset", "laser_whistle"))
    assert s.fixes == {"tones": 1.0}
    assert cli.settings_from_args(_args("a.wav", "b.wav", "--preset", "suno_v3")).fixes == {"tones": 1.0}
    with pytest.raises(SystemExit):
        cli.main(["a.wav", "b.wav", "--preset", "not_a_preset"])


def test_cards_and_amounts_from_the_command_line():
    s = cli.settings_from_args(_args("a.wav", "b.wav", "--fix", "tones=0.4", "--fix", "sibilance",
                                     "--no-auto"))
    assert s.fixes == {"tones": 0.4, "sibilance": core.catalog.card("sibilance").default_amount}
    assert s.auto is False
    s = cli.settings_from_args(_args("a.wav", "b.wav", "--fix", "tones", "--no-static-repair"))
    assert "tones" not in s.fixes and s.auto is False
    with pytest.raises(SystemExit):
        cli.main(["a.wav", "b.wav", "--fix", "nonsense"])


def test_cards_that_mastering_fixes_turn_mastering_on():
    for card in ("air", "loudness"):
        assert cli.settings_from_args(_args("a.wav", "b.wav", "--fix", card)).mastering is True
    assert cli.settings_from_args(_args("a.wav", "b.wav", "--fix", "air", "--no-master")).mastering is False


def test_the_report_does_not_call_mastering_cards_unbuilt():
    x = core.Source.from_array(_mix(seconds=2.0), SR)
    on = core.render(x, core.Settings(fixes={"air": 0.5, "sibilance": 0.5}))
    assert on.report["fixes"]["air"] == "with mastering"
    assert on.report["fixes"]["sibilance"] == "not built yet"
    off = core.render(x, core.Settings(fixes={"loudness": 0.5}, mastering=False))
    assert off.report["fixes"]["loudness"] == "needs mastering"


def test_retired_1_x_flags_are_ignored_with_a_note(song, tmp_path, capsys):
    out = tmp_path / "old.wav"
    code = cli.main([str(song), str(out), "--denoise", "0.5", "--slope", "0.8",
                     "--legacy-engine", "--ceiling", "-2"])
    assert code == 0 and out.is_file()
    said = capsys.readouterr().out
    for flag in ("--denoise", "--slope", "--legacy-engine", "--ceiling"):
        assert flag in said


def test_write_diff_writes_what_the_fixes_took(song, tmp_path):
    out, diff = tmp_path / "o.wav", tmp_path / "removed.flac"
    assert cli.main([str(song), str(out), "--write-diff", str(diff)]) == 0
    assert diff.is_file()


def test_list_names_every_card_and_target(capsys):
    assert cli.main(["--list"]) == 0
    said = capsys.readouterr().out
    for c in core.catalog.CARDS:
        assert c.key in said
    for t in core.catalog.LOUDNESS_TARGETS:
        assert t.key in said


def test_suggest_prints_findings(tmp_path, capsys):
    soundfile = pytest.importorskip("soundfile")
    quiet = tmp_path / "quiet.wav"
    soundfile.write(str(quiet), _mix(level=0.005), SR)
    assert cli.main(["--suggest", str(quiet)]) == 0
    assert "quieter than" in capsys.readouterr().out


def test_a_missing_input_is_an_error_not_a_crash(tmp_path, capsys):
    assert cli.main([str(tmp_path / "nope.wav"), str(tmp_path / "o.wav")]) == 1
