"""Every EQ-type filter applies exactly the dB it is set to.

The old engine designed preset shelves and bells at full gain and then ran
them forward and backward, so every one landed at twice its setting
(ARCHITECTURE.md §10). One filter design serves the whole engine now, and
these tests hold it to "the dB you set is the dB you get".

Interface: shimmer.core.audio.filters
    design(kind, hz, sr, gain_db=0.0, q=0.707) -> sos
        kind in KINDS = ("bell", "low_shelf", "high_shelf",
                         "high_pass", "low_pass", "notch")
    apply(x, sr, sos) -> y        zero-phase
        A pass filter's cutoff is the -3 dB point of the response as
        applied (both directions together), with a slope of at least
        12 dB per octave.
"""
import numpy as np
import pytest

from _contract import needs

pytestmark = needs("shimmer.core.audio.filters")

SR = 48000
N = 1 << 16


def _impulse_response(sos):
    from shimmer.core.audio import filters
    imp = np.zeros((N, 1))
    imp[N // 2, 0] = 1.0
    return filters.apply(imp, SR, sos)[:, 0]


def _gain_db_at(sos, hz):
    h = np.abs(np.fft.rfft(_impulse_response(sos)))
    f = np.fft.rfftfreq(N, 1 / SR)
    return 20 * np.log10(h[np.argmin(np.abs(f - hz))])


@pytest.mark.parametrize("gain", [-6.0, -3.0, 3.0, 6.0])
@pytest.mark.parametrize("hz", [100.0, 1000.0, 8000.0])
def test_a_bell_lands_on_its_gain(gain, hz):
    from shimmer.core.audio import filters
    sos = filters.design("bell", hz, SR, gain_db=gain, q=1.0)
    assert abs(_gain_db_at(sos, hz) - gain) < 0.1


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
    sos = filters.design(kind, 1000.0, SR)
    assert abs(_gain_db_at(sos, 1000.0) + 3.01) < 0.1


@pytest.mark.parametrize("kind, stop, keep", [("high_pass", 500.0, 4000.0),
                                              ("low_pass", 2000.0, 250.0)])
def test_passes_cut_an_octave_out_and_leave_the_band_alone(kind, stop, keep):
    from shimmer.core.audio import filters
    sos = filters.design(kind, 1000.0, SR)
    assert _gain_db_at(sos, stop) <= -9.0        # at least 12 dB/octave, applied
    assert abs(_gain_db_at(sos, keep)) < 0.1     # two octaves inside: untouched


def test_a_notch_reaches_its_depth_and_leaves_an_octave_away_alone():
    from shimmer.core.audio import filters
    sos = filters.design("notch", 4000.0, SR, gain_db=-30.0, q=30.0)
    assert abs(_gain_db_at(sos, 4000.0) + 30.0) < 0.5
    assert abs(_gain_db_at(sos, 2000.0)) < 0.5
    assert abs(_gain_db_at(sos, 8000.0)) < 0.5


@pytest.mark.parametrize("kind", ["bell", "high_shelf", "high_pass"])
def test_filters_are_zero_phase(kind):
    from shimmer.core.audio import filters
    sos = filters.design(kind, 1000.0, SR, gain_db=6.0 if kind != "high_pass" else 0.0)
    y = _impulse_response(sos)
    left = y[N // 2 - 2000:N // 2][::-1]
    right = y[N // 2 + 1:N // 2 + 2001]
    assert np.max(np.abs(left - right)) < 1e-6 * max(np.max(np.abs(y)), 1e-12) + 1e-9


@pytest.mark.parametrize("kind", ["bell", "low_shelf", "high_shelf"])
def test_zero_gain_changes_nothing(kind):
    from shimmer.core.audio import filters
    x = np.random.default_rng(0).standard_normal((SR, 2)) * 0.1
    y = filters.apply(x, SR, filters.design(kind, 1000.0, SR, gain_db=0.0))
    assert np.allclose(y, x, atol=1e-7)
