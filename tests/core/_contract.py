"""Helpers shared by the contract tests: the per-module gate, and meters
written independently of the engine they check.

A test here is expected to fail, strictly, until every module it imports
exists (ARCHITECTURE §19.1 item 3). Only a failed import counts as that
expected failure. Any other error fails the run, and so does a test that
passes while one of its modules is still missing.
"""
import importlib.util

import numpy as np
import pytest
from scipy.signal import resample_poly


def _missing(name):
    try:
        return importlib.util.find_spec(name) is None
    except ModuleNotFoundError:          # a parent package is missing
        return True


def needs(*modules):
    """Mark a test as waiting for these modules."""
    gone = [m for m in modules if _missing(m)]
    return pytest.mark.xfail(bool(gone), reason="not built yet: " + ", ".join(gone),
                             raises=ImportError, strict=True)


def true_peak_16x_db(x):
    """True peak of the louder channel at 16x oversampling.

    Deliberately not the engine's meter: the old limiter's -1.0 dBTP read
    -0.78 at 16x (ARCHITECTURE §19.1 item 13).
    """
    x = np.asarray(x, dtype=np.float64)
    if x.ndim == 1:
        x = x[:, None]
    peak = max(float(np.max(np.abs(resample_poly(x[:, c], 16, 1)))) for c in range(x.shape[1]))
    return 20 * np.log10(peak + 1e-20)


def lufs(x, sr):
    """Integrated loudness by the BS.1770 reference implementation."""
    import pyloudnorm as pyln
    return pyln.Meter(sr).integrated_loudness(np.asarray(x, dtype=np.float64))
