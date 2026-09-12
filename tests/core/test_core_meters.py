"""One loudness meter and one true-peak meter, both right.

The old engine had seven spectrum measures and a true-peak meter that read a
mono mix, so it under-read peaks whenever the channels differed (ARCHITECTURE
§10). The release check, the report and the limiter all read from these now.

Interface: shimmer.core.audio.meters
    loudness(x, sr) -> float          integrated LUFS, ITU-R BS.1770
    true_peak_db(x, sr) -> float      the louder channel, oversampled
"""
import importlib.util

import numpy as np
import pytest

pytestmark = pytest.mark.xfail(importlib.util.find_spec("shimmer.core") is None,
                               reason="shimmer.core is not built yet (rebuild Step 4)",
                               strict=True)

SR = 48000


def test_loudness_matches_the_bs1770_reference():
    import pyloudnorm as pyln
    from shimmer.core.audio import meters
    x = np.random.default_rng(1).standard_normal((5 * SR, 2)) * 0.1
    assert abs(meters.loudness(x, SR) - pyln.Meter(SR).integrated_loudness(x)) < 0.01


def test_true_peak_reads_the_louder_channel():
    from shimmer.core.audio import meters
    t = np.arange(SR) / SR
    s = np.sin(2 * np.pi * 1000.0 * t)
    x = np.stack([0.1 * s, 0.9 * s], axis=1)
    assert abs(meters.true_peak_db(x, SR) - 20 * np.log10(0.9)) < 0.1


def test_true_peak_catches_peaks_between_samples():
    from shimmer.core.audio import meters
    # A sine at a quarter of the sample rate, phase-shifted 45 degrees:
    # every sample lands at 0.707, the wave itself reaches 1.0.
    n = np.arange(SR)
    s = np.sin(2 * np.pi * n / 4 + np.pi / 4)
    x = np.stack([s, s], axis=1)
    assert np.max(np.abs(x)) < 0.71
    assert abs(meters.true_peak_db(x, SR)) < 0.3


def test_true_peak_never_reads_below_the_sample_peak():
    from shimmer.core.audio import meters
    x = np.random.default_rng(2).standard_normal((SR, 2)) * 0.2
    sample_peak = 20 * np.log10(np.max(np.abs(x)))
    assert meters.true_peak_db(x, SR) >= sample_peak - 0.01
