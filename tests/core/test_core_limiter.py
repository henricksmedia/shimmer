"""The peak shaper (shimmer/core/master/limiter.py): a soft clipper at 4x.

What it must do (docs/CHAIN-AUDIT.md section 4, plan A item 2): round off
peaks without folding new, off-key tones back into the audible range, give
both channels the same gain, leave the signal alone below its knee, and
shape a preview window exactly as the same span of a full song.
"""
import numpy as np

from shimmer.core.master import limiter

SR = 48000


def _tone(hz, seconds=1.0, peak_db=-1.0 + 3.0):
    t = np.arange(int(seconds * SR)) / SR
    return (10 ** (peak_db / 20) * np.sin(2 * np.pi * hz * t))[:, None].repeat(2, axis=1)


def _level_at(y, hz):
    """Level (dB) of the strongest bin within 30 Hz of `hz`."""
    w = np.hanning(len(y))
    spec = np.abs(np.fft.rfft(y * w))
    f = np.fft.rfftfreq(len(y), 1 / SR)
    return 20 * np.log10(spec[np.abs(f - hz) < 30].max() + 1e-30)


def test_below_the_knee_nothing_changes():
    x = 0.5 * _tone(1000, peak_db=0.0)             # -6 dBFS, under a -3 dBFS knee
    y, rep = limiter.soft_peak_shaper(x, -1.0)
    assert np.array_equal(y, x.astype(np.float32)) and rep["shaped_ratio"] == 0.0


def test_no_off_key_tones_fold_back():
    """A 9 kHz tone pushed 3 dB over the ceiling. Its 3rd and 5th harmonics
    (27 and 45 kHz) are above the audible range; at the base rate they would
    fold back to 21 and 3 kHz, about 20 dB under the tone. At 4x they are
    filtered out, and what is left (a far harmonic folding at 4x) sits more
    than 60 dB under it."""
    x = _tone(9000)
    y, _ = limiter.soft_peak_shaper(x, -1.0)
    main = _level_at(y[:, 0], 9000)
    for folded in (3000, 21000):
        assert _level_at(y[:, 0], folded) < main - 60.0, folded


def test_both_channels_get_the_same_gain():
    x = _tone(200)
    x[:, 1] *= 0.3                                  # the right is quiet, under the knee
    y, _ = limiter.soft_peak_shaper(x, -1.0)
    # The loud left decides: the right is turned down by the same share.
    np.testing.assert_allclose(y[:, 1], 0.3 * y[:, 0], atol=1e-6)


def test_peaks_stay_near_the_ceiling():
    x = _tone(200, peak_db=-1.0 + 8.0)              # 8 dB over
    y, _ = limiter.soft_peak_shaper(x, -1.0)
    assert np.max(np.abs(y)) < 10 ** ((-1.0 + 1.0) / 20)


def test_a_window_matches_the_full_signal():
    rng = np.random.default_rng(2)
    x = np.cumsum(rng.standard_normal((SR * 3, 2)), axis=0)
    x = 1.4 * x / np.max(np.abs(x))                 # well over the ceiling in places
    full, _ = limiter.soft_peak_shaper(x, -1.0)
    a, b, lead = SR, 2 * SR, SR // 2
    part, _ = limiter.soft_peak_shaper(x[a - lead:b + lead], -1.0)
    assert np.max(np.abs(part[lead:lead + b - a] - full[a:b])) < 1e-5
