"""Standard mastering (shimmer.core.master.standard): the chain online
mastering services run, and how render() runs it.

Interface: shimmer.core.master.standard
    split_bands(x, sr), plan(x, sr), plan_and_run(x, sr), apply(x, sr, plan, offset)
    Settings.tone_target ("standard" by default, "builtin", "reference")
"""
import numpy as np

import conftest
from _contract import needs

pytestmark = needs("shimmer.core.master.standard", "shimmer.core.render")

SR = 48000


def _song(seconds=12.0):
    x = conftest._clean(seconds=seconds).astype(np.float64)
    # A little stereo: the sides carry a quieter, delayed copy.
    side = 0.15 * np.roll(x[:, 0], 240)
    return np.stack([x[:, 0] + side, x[:, 1] - side], axis=1).astype(np.float32)


def _rms_db(a):
    return 10.0 * np.log10(np.mean(np.asarray(a, dtype=np.float64) ** 2) + 1e-30)


def test_the_bands_add_back_to_the_same_level_everywhere():
    from scipy.signal import welch
    from shimmer.core.master import standard
    rng = np.random.default_rng(0)
    x = rng.standard_normal((SR * 4, 1)) * 0.1
    y = sum(standard.split_bands(x, SR))
    f, px = welch(x[:, 0], SR, nperseg=4096)
    _, py = welch(y[:, 0], SR, nperseg=4096)
    band = (f > 30) & (f < 18000)
    assert np.max(np.abs(10 * np.log10(py[band] / px[band]))) < 0.3


def test_a_window_gets_the_same_gains_as_the_whole_song():
    from shimmer.core.master import standard
    x = _song()
    p, whole = standard.plan_and_run(x, SR)
    assert np.allclose(standard.apply(x, SR, p), whole, atol=1e-6)
    a, b, lead = 5 * SR, 7 * SR, SR
    w = standard.apply(x[a - lead:b], SR, p, offset=a - lead)[lead:]
    diff = _rms_db(w - whole[a:b]) - _rms_db(whole[a:b])
    assert diff < -60.0


def test_the_compressors_keep_the_tone_and_hold_the_loud_parts():
    from shimmer.core.master import standard
    x = _song()
    p, y = standard.plan_and_run(x, SR)
    s = p.summary
    # Each band is turned down somewhere, never past the limit.
    assert all(-standard._MAX_GR_DB <= v < 0.0 for v in s["band_most_db"])
    assert -standard._MAX_GR_DB <= s["glue_most_db"] < 0.0
    # The tone stays put: each band's level against the whole moves little.
    xb, yb = standard.split_bands(np.asarray(x, np.float64), SR), standard.split_bands(y, SR)
    shift = [(_rms_db(b2) - _rms_db(y)) - (_rms_db(b1) - _rms_db(x)) for b1, b2 in zip(xb, yb)]
    assert max(abs(v) for v in shift) < 1.5


def test_mono_bass_takes_the_side_out_of_the_low_end():
    from shimmer.core.master import standard
    t = np.arange(SR * 4) / SR
    bass = 0.3 * np.sin(2 * np.pi * 50 * t)
    x = np.stack([bass, -bass], axis=1)            # all side, at 50 Hz
    y = standard.stereo(x, SR, 0.0)
    side = (y[:, 0] - y[:, 1]) / 2
    assert _rms_db(side[SR:]) - _rms_db(x[SR:, 0]) < -15.0


def test_silence_and_mono_pass_through():
    from shimmer.core.master import standard
    z = np.zeros((SR, 2), dtype=np.float32)
    p, y = standard.plan_and_run(z, SR)
    assert np.max(np.abs(y)) == 0.0
    m = _song()[:, :1]
    p, y = standard.plan_and_run(m, SR)
    assert y.shape == m.shape and np.all(np.isfinite(y))
    assert p.summary["mono_bass_hz"] is None


def test_render_runs_standard_by_default_and_lands_on_target():
    from shimmer.core import Settings, Source, render
    from shimmer.core.audio import meters
    src = Source.from_array(_song(), SR)
    r = render(src, Settings())
    m = r.report["mastering"]
    assert Settings().tone_target == "standard"
    assert m["tone_target"] == "standard" and "standard" in m
    # This test song is all sharp hits (about 5 dB of limiting at -9 LUFS),
    # so the one-pass loudness check lands within a few tenths, as it does
    # for Built-in (0.33 LU here); real songs land within 0.05.
    assert abs(meters.loudness(r.audio, SR) - m["target_lufs"]) < 0.4
    assert meters.true_peak_db(r.audio, SR) <= m["ceiling_dbtp"] + 0.05
    # The preview window matches the export.
    w = render(src, Settings(), window=(4.0, 6.0))
    a, b = 4 * SR, 6 * SR
    assert _rms_db(w.audio - r.audio[a:b]) - _rms_db(r.audio[a:b]) < -60.0


def test_built_in_and_mastering_off_skip_the_chain():
    from shimmer.core import Settings, Source, render
    src = Source.from_array(_song(), SR)
    assert "standard" not in render(src, Settings(tone_target="builtin")).report["mastering"]
    assert "standard" not in render(src, Settings(mastering=False)).report["mastering"]


def test_old_saved_settings_and_requests_carry_the_choice():
    from shimmer.core import Settings, migrate
    assert migrate({"mastering": {"enabled": True, "tone_target": "builtin"}}).tone_target == "builtin"
    assert migrate({"mastering": {"enabled": True}}).tone_target == "standard"
    assert Settings(tone_target="nonsense").tone_target == "standard"
    assert Settings.from_dict(Settings(tone_target="builtin").to_dict()).tone_target == "builtin"
