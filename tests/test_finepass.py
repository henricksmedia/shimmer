"""
Phase 2: the fine-grid dynamic pass (finepass.py) and per-bin De-harsh.

  * With both stages at zero the pass is an exact bypass.
  * Flicker Tamer on the fine grid actually reduces 20-40 Hz hash
    (the coarse grid could not see it) and leaves steady texture alone.
  * The spectral de-esser cuts sibilant bursts, is not switched off by
    the transient hold, and leaves drum attacks alone.
  * Per-bin De-harsh takes more off the glazed peaks than off the band.
  * The chain shows the fine pass before the coarse engine and marks
    the coarse Flicker Tamer as moved.

Run:  .venv\\Scripts\\python.exe -m pytest tests/test_finepass.py -q
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pytest
from scipy import signal as ss

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from shimmer import detect, finepass  # noqa: E402
from shimmer.chain import build_chain  # noqa: E402
from shimmer.engine import process  # noqa: E402
from shimmer.mastering import master_params_from_json  # noqa: E402
from shimmer.params import Params  # noqa: E402
from shimmer.pipeline import clean_and_master  # noqa: E402
from shimmer.presets import get_preset  # noqa: E402
from test_detect import SR, _hash, _music  # noqa: E402


def _band_energy_db(x: np.ndarray, sr: int, lo: float, hi: float) -> float:
    mono = x.mean(axis=1) if x.ndim > 1 else x
    f, P = ss.welch(mono, fs=sr, nperseg=2048)
    m = (f >= lo) & (f < hi)
    return float(10 * np.log10(P[m].mean() + 1e-18))


def _flicker_depth_db(x: np.ndarray, lo: float = 5000.0, hi: float = 9000.0) -> float:
    """Modulation depth of the band on the fine grid: std of the
    detrended dB envelope over a 250 ms window. A square-wave flicker
    reads as a large depth; steady texture as a small one."""
    from scipy.ndimage import uniform_filter1d
    from shimmer.dsp import freq_bin_indices
    mono = x[:, 0] if x.ndim > 1 else x
    f, _, Z = ss.stft(mono, fs=SR, nperseg=1024, noverlap=768, boundary="zeros", padded=True)
    P = np.abs(Z) ** 2
    idx = freq_bin_indices(f, lo, hi)
    e = 10 * np.log10(P[idx].mean(axis=0) + 1e-18)
    win = int(round(0.25 * SR / 256))
    d = e - uniform_filter1d(e, size=win, mode="nearest")
    return float(np.std(d))


@pytest.fixture(scope="module")
def bed():
    return _music(6.0)


@pytest.fixture(scope="module")
def bed_nohits():
    # A hit-free bed: the drum hits every 250 ms would dominate any
    # envelope-depth measure (and are gated out of the tamer anyway).
    return _music(6.0, hits=False)


class TestBypass:
    def test_zero_amounts_are_exact_bypass(self, bed):
        p = Params(flicker_tame=0.0, deess=0.0)
        y = finepass.fine_pass(bed[:, :1], SR, p)
        assert np.array_equal(y, bed[:, :1])

    def test_reconstruction_is_transparent_with_no_gain(self, bed):
        # A pass whose stages never trigger must reconstruct the input
        # (STFT / ISTFT round trip) to well under -60 dB error.
        p = Params(flicker_tame=1.0, ft_thr_db=200.0, deess=0.0)
        x = bed[:, :1]
        y = finepass.fine_pass(x, SR, p)
        err = np.sqrt(np.mean((y - x) ** 2)) / (np.sqrt(np.mean(x ** 2)) + 1e-12)
        assert 20 * np.log10(err + 1e-12) < -60.0
        assert y.shape == x.shape


class TestFlicker:
    def test_fine_pass_reduces_hash_that_coarse_pass_could_not(self, bed_nohits):
        bed = bed_nohits
        hsh = _hash(6.0, 0.09)                   # 20 Hz flicker, 5-9 kHz
        x = (bed + hsh).astype(np.float32)
        p = Params(flicker_tame=1.0, ft_start_hz=4500.0, ft_end_hz=12000.0, deess=0.0)
        stats = {}
        y = finepass.fine_pass(x[:, :1], SR, p, stats=stats)
        # The flicker itself gets flatter (a 20 Hz square wave: the on
        # frames are cut 6-8 dB, and the overlap-add smears each cut
        # across the on/off edge, so the depth falls by about 40 %)...
        assert _flicker_depth_db(y) <= _flicker_depth_db(x[:, :1]) - 1.2
        # ...and the hash band loses energy while the mids do not move.
        drop = _band_energy_db(x[:, :1], SR, 5000, 9000) - _band_energy_db(y, SR, 5000, 9000)
        assert drop >= 3.0
        assert stats["flicker_att_max_db"] >= 6.0
        mids = _band_energy_db(x[:, :1], SR, 300, 2000) - _band_energy_db(y, SR, 300, 2000)
        assert abs(mids) < 0.3
        # For contrast: the coarse engine alone barely touches it.
        pc = Params(flicker_tame=1.0, ft_start_hz=4500.0, ft_end_hz=12000.0,
                    fine_pass=False, start_hz=4500.0, end_hz=12000.0)
        yc = process(x[:, :1], SR, pc)
        drop_c = _band_energy_db(x[:, :1], SR, 5000, 9000) - _band_energy_db(yc, SR, 5000, 9000)
        assert drop >= drop_c + 1.5

    def test_steady_texture_is_left_alone(self, bed_nohits):
        p = Params(flicker_tame=1.0, ft_start_hz=4500.0, ft_end_hz=12000.0, deess=0.0)
        stats = {}
        y = finepass.fine_pass(bed_nohits[:, :1], SR, p, stats=stats)
        change = _band_energy_db(bed_nohits[:, :1], SR, 5000, 9000) - _band_energy_db(y, SR, 5000, 9000)
        assert abs(change) < 1.0
        assert stats["flicker_att_mean_db"] < 0.3

    def test_hits_are_not_eaten(self, bed):
        # With hits present the tamer must leave the attacks alone.
        p = Params(flicker_tame=1.0, ft_start_hz=4500.0, ft_end_hz=12000.0, deess=0.0)
        y = finepass.fine_pass(bed[:, :1], SR, p)
        hits = [int(i * SR / 4) for i in range(1, 20)]
        hx = sum(float(np.sum(bed[h:h + int(0.01 * SR), 0] ** 2)) for h in hits)
        hy = sum(float(np.sum(y[h:h + int(0.01 * SR), 0] ** 2)) for h in hits)
        assert abs(10 * np.log10(hx / hy)) < 0.5


def _sibilant_bursts(seconds: float, level: float, seed: int = 5) -> np.ndarray:
    """80 ms noise bursts in 5-9 kHz every 400 ms: a razor 'sss'."""
    rng = np.random.default_rng(seed)
    n = int(SR * seconds)
    sos = ss.butter(4, [5000.0, 9000.0], btype="bandpass", fs=SR, output="sos")
    nz = ss.sosfilt(sos, rng.standard_normal(n))
    env = np.zeros(n)
    for s0 in range(int(0.3 * SR), n - int(0.1 * SR), int(0.4 * SR)):
        L = int(0.08 * SR)
        env[s0:s0 + L] = np.hanning(L)
    y = (level * nz * env).astype(np.float32)
    return np.stack([y, y], axis=1)


class TestDeesser:
    def test_bursts_are_cut_and_attacks_kept(self, bed):
        # 0.6 puts the burst about 10 dB above the 1-4 kHz reference,
        # where a razor "sss" sits; at 0.25 it would not clear the 6 dB
        # threshold and the stage would rightly stay quiet.
        bursts = _sibilant_bursts(6.0, 0.6)
        x = (bed + bursts).astype(np.float32)
        p = Params(deess=1.0, de_start_hz=4500.0, de_end_hz=10500.0, flicker_tame=0.0)
        y = finepass.fine_pass(x[:, :1], SR, p)
        # Energy in 5-9 kHz during the bursts drops. With the default
        # 6 dB threshold and 0.6 dB/dB slope a burst 10 dB over the mids
        # gets about 3 dB, on purpose: a de-esser that takes more than
        # that by default lisps.
        env = bursts[:, 0] != 0
        sos = ss.butter(4, [5000.0, 9000.0], btype="bandpass", fs=SR, output="sos")
        bx = ss.sosfiltfilt(sos, x[:, 0])[env]
        by = ss.sosfiltfilt(sos, y[:, 0])[env]
        drop = 10 * np.log10(np.mean(bx ** 2) / (np.mean(by ** 2) + 1e-18))
        assert drop >= 2.5
        # The bed's drum hits keep their attack energy (first 10 ms of each).
        hits = [int(i * SR / 4) for i in range(1, 20)]
        hx = sum(float(np.sum(x[h:h + int(0.01 * SR), 0] ** 2)) for h in hits)
        hy = sum(float(np.sum(y[h:h + int(0.01 * SR), 0] ** 2)) for h in hits)
        assert abs(10 * np.log10(hx / hy)) < 0.5

    def test_pipeline_runs_fine_pass_and_removed_carries_it(self, bed):
        bursts = _sibilant_bursts(6.0, 0.6)
        x = (bed + bursts).astype(np.float32)
        p = get_preset("sibilance_rattle")
        y, removed, rep = clean_and_master(x, SR, p, master_params=None)
        assert y.shape == x.shape and removed.shape == x.shape
        env = bursts[:, 0] != 0
        sos = ss.butter(4, [5000.0, 9000.0], btype="bandpass", fs=SR, output="sos")
        rb = ss.sosfiltfilt(sos, removed[:, 0])[env]
        rq = ss.sosfiltfilt(sos, removed[:, 0])[~env]
        # Removed holds more burst energy than quiet-time energy.
        assert np.mean(rb ** 2) > 3.0 * np.mean(rq ** 2)


class TestPerBinDeHarsh:
    def test_peaks_take_more_of_the_cut(self, bed):
        # Glazed overtones: four steady peaks 3-6 kHz riding on the bed.
        n = bed.shape[0]
        t = np.arange(n) / SR
        glaze = sum(0.02 * np.sin(2 * np.pi * f0 * t) for f0 in (3300.0, 4100.0, 4900.0, 5700.0))
        x = (bed + np.stack([glaze, glaze], axis=1)).astype(np.float32)
        # Threshold far below the signal so the stage is always cutting
        # hard; the question is only where the cut lands.
        base = dict(deharsh=0.8, dh_start_hz=2000.0, dh_end_hz=8000.0,
                    dh_ref_start_hz=300.0, dh_ref_end_hz=1500.0, dh_thr_db=-20.0,
                    dh_slope=1.0, dh_max_att_db=12.0, start_hz=2000.0, end_hz=8000.0,
                    fine_pass=False, flicker_tame=0.0)
        y_flat = process(x[:, :1], SR, Params(dh_per_bin=0.0, **base))
        y_bin = process(x[:, :1], SR, Params(dh_per_bin=1.0, **base))

        def peak_and_floor(sig):
            mono = sig[:, 0] if sig.ndim > 1 else sig
            f, P = ss.welch(mono, fs=SR, nperseg=4096)
            L = 10 * np.log10(P + 1e-18)
            peaks = np.mean([L[int(np.argmin(np.abs(f - f0)))] for f0 in (3300, 4100, 4900, 5700)])
            band = (f >= 2500) & (f <= 7500)
            return peaks, float(np.median(L[band]))

        px, fx = peak_and_floor(x)
        pf, ff = peak_and_floor(y_flat)
        pb, fb = peak_and_floor(y_bin)
        # Per-bin: peaks drop more than the band median; flat: about the same.
        assert (px - pb) - (fx - fb) > (px - pf) - (fx - ff) + 1.0
        assert (fx - fb) < (fx - ff)      # less broadband loss per-bin


class TestChain:
    def test_fine_pass_shown_before_engine_and_flicker_moved(self):
        mp = master_params_from_json({"enabled": True})
        chain = build_chain(get_preset("suno_hash"), mp)
        ids = [m["id"] for m in chain["modules"]]
        assert ids.index("fine-flicker") < ids.index("fine-deess") < ids.index("premask")
        mods = {m["id"]: m for m in chain["modules"]}
        assert mods["fine-flicker"]["active"] is True
        assert mods["flicker"]["active"] is False
        assert "fine pass" in mods["flicker"]["off_reason"]
        assert chain["summary"]["fine_pass"] is True
        chain2 = build_chain(get_preset("sibilance_rattle"), mp)
        m2 = {m["id"]: m for m in chain2["modules"]}
        assert m2["fine-deess"]["active"] is True
