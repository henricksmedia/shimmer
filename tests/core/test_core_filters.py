"""Every EQ-type filter applies exactly the dB it is set to, and none smears
a hit with pre-echo.

The old engine designed preset shelves and bells at full gain and then ran
them forward and backward, so every one landed at twice its setting
(ARCHITECTURE.md §10). One filter design serves the whole engine now, and
these tests hold it to "the dB you set is the dB you get".

Which way a filter runs is set by measurement (ARCHITECTURE §19.1 item 16):
zero-phase where its pre-echo stays within 20 ms of a hit (bells, shelves and
notches at normal settings), one way otherwise (every high-pass and low-pass,
and long-ringing bells).

Interface: shimmer.core.audio.filters
    design(kind, hz, sr, gain_db=0.0, q=0.707) -> a design (pass it to apply)
        kind in KINDS = ("bell", "low_shelf", "high_shelf",
                         "high_pass", "low_pass", "notch")
    apply(x, sr, design) -> y
        A pass filter's cutoff is the -3 dB point of the response as applied,
        with a slope of at least 12 dB per octave.
"""
import numpy as np
import pytest

from _contract import needs

pytestmark = needs("shimmer.core.audio.filters")

SR = 48000
N = 1 << 16


def _impulse_response(design):
    from shimmer.core.audio import filters
    imp = np.zeros((N, 1))
    imp[N // 2, 0] = 1.0
    return filters.apply(imp, SR, design)[:, 0]


def _gain_db_at(design, hz):
    h = np.abs(np.fft.rfft(_impulse_response(design)))
    f = np.fft.rfftfreq(N, 1 / SR)
    return 20 * np.log10(h[np.argmin(np.abs(f - hz))])


def _drum_hit(n, t0):
    """A kick drum and a noise burst starting together at sample t0, in
    silence: low and high content, both with a sharp onset."""
    x = np.zeros(n)
    hit = int(0.3 * SR)
    kt = np.arange(hit) / SR
    x[t0:t0 + hit] = np.sin(2 * np.pi * (50 * kt + 150 * (1 - np.exp(-kt * 30)) / 30)) * np.exp(-kt * 8)
    burst = int(0.15 * SR)
    x[t0:t0 + burst] += 0.5 * np.random.default_rng(1).standard_normal(burst) * np.exp(-np.arange(burst) / SR * 30)
    return x


@pytest.mark.parametrize("gain", [-6.0, -3.0, 3.0, 6.0])
@pytest.mark.parametrize("hz", [100.0, 1000.0, 8000.0])
def test_a_bell_lands_on_its_gain(gain, hz):
    from shimmer.core.audio import filters
    d = filters.design("bell", hz, SR, gain_db=gain, q=1.0)
    assert abs(_gain_db_at(d, hz) - gain) < 0.1


@pytest.mark.parametrize("gain", [-6.0, -3.0, 3.0])
def test_shelves_land_on_their_gain(gain):
    from shimmer.core.audio import filters
    high = filters.design("high_shelf", 2000.0, SR, gain_db=gain)
    low = filters.design("low_shelf", 200.0, SR, gain_db=gain)
    # Three octaves past the corner, a shelf has reached its full gain.
    assert abs(_gain_db_at(high, 16000.0) - gain) < 0.2
    assert abs(_gain_db_at(low, 25.0) - gain) < 0.2


@pytest.mark.parametrize("kind", ["high_pass", "low_pass"])
def test_passes_are_3_db_down_at_their_cutoff(kind):
    from shimmer.core.audio import filters
    d = filters.design(kind, 1000.0, SR)
    assert abs(_gain_db_at(d, 1000.0) + 3.01) < 0.1


@pytest.mark.parametrize("kind, stop, keep", [("high_pass", 500.0, 4000.0),
                                              ("low_pass", 2000.0, 250.0)])
def test_passes_cut_an_octave_out_and_leave_the_band_alone(kind, stop, keep):
    from shimmer.core.audio import filters
    d = filters.design(kind, 1000.0, SR)
    assert _gain_db_at(d, stop) <= -9.0        # at least 12 dB/octave, applied
    assert abs(_gain_db_at(d, keep)) < 0.1     # two octaves inside: untouched


def test_a_notch_reaches_its_depth_and_leaves_an_octave_away_alone():
    from shimmer.core.audio import filters
    d = filters.design("notch", 4000.0, SR, gain_db=-30.0, q=30.0)
    assert abs(_gain_db_at(d, 4000.0) + 30.0) < 0.5
    assert abs(_gain_db_at(d, 2000.0)) < 0.5
    assert abs(_gain_db_at(d, 8000.0)) < 0.5


@pytest.mark.parametrize("kind, hz, gain, q", [("bell", 1000.0, 6.0, 1.0),
                                               ("low_shelf", 1000.0, 6.0, 0.707),
                                               ("high_shelf", 1000.0, 6.0, 0.707),
                                               ("notch", 8000.0, -30.0, 30.0)])
def test_short_ringing_filters_are_zero_phase(kind, hz, gain, q):
    from shimmer.core.audio import filters
    y = _impulse_response(filters.design(kind, hz, SR, gain_db=gain, q=q))
    left = y[N // 2 - 2000:N // 2][::-1]
    right = y[N // 2 + 1:N // 2 + 2001]
    assert np.max(np.abs(left - right)) < 1e-6 * max(np.max(np.abs(y)), 1e-12) + 1e-9


@pytest.mark.parametrize("kind, hz, gain, q", [("high_pass", 30.0, 0.0, 0.707),
                                               ("low_pass", 1000.0, 0.0, 0.707),
                                               ("bell", 50.0, 6.0, 4.0)])
def test_long_ringing_filters_put_nothing_before_the_sound(kind, hz, gain, q):
    from shimmer.core.audio import filters
    y = _impulse_response(filters.design(kind, hz, SR, gain_db=gain, q=q))
    assert np.max(np.abs(y[:N // 2])) <= 1e-9


@pytest.mark.parametrize("kind, hz, gain, q", [
    ("high_pass", 30.0, 0.0, 0.707), ("low_pass", 16000.0, 0.0, 0.707),
    ("bell", 50.0, 6.0, 4.0), ("bell", 100.0, -6.0, 1.0), ("bell", 300.0, -3.0, 1.0),
    ("bell", 3000.0, -4.0, 2.0), ("low_shelf", 100.0, 3.0, 0.707),
    ("high_shelf", 10000.0, 3.0, 0.707), ("notch", 1000.0, -30.0, 30.0),
    ("notch", 3500.0, -30.0, 30.0), ("notch", 16000.0, -30.0, 30.0),
])
def test_no_filter_puts_sound_more_than_20_ms_before_a_hit(kind, hz, gain, q):
    from shimmer.core.audio import filters
    t0 = SR
    x = _drum_hit(2 * SR, t0)[:, None]
    y = filters.apply(x, SR, filters.design(kind, hz, SR, gain_db=gain, q=q))[:, 0]
    early = np.max(np.abs(y[:t0 - int(0.020 * SR)]))
    assert 20 * np.log10(early / np.max(np.abs(y)) + 1e-20) <= -60.0


@pytest.mark.parametrize("kind", ["bell", "low_shelf", "high_shelf"])
def test_zero_gain_changes_nothing(kind):
    from shimmer.core.audio import filters
    x = np.random.default_rng(0).standard_normal((SR, 2)) * 0.1
    y = filters.apply(x, SR, filters.design(kind, 1000.0, SR, gain_db=0.0))
    assert np.allclose(y, x, atol=1e-7)


def test_mono_and_stereo_are_filtered_alike():
    from shimmer.core.audio import filters
    d = filters.design("bell", 1000.0, SR, gain_db=4.0, q=1.0)
    x = np.random.default_rng(5).standard_normal(SR) * 0.1
    mono = filters.apply(x, SR, d)
    stereo = filters.apply(np.stack([x, x], axis=1), SR, d)
    assert mono.shape == x.shape
    assert np.allclose(stereo[:, 0], mono) and np.allclose(stereo[:, 1], mono)
