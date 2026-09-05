"""
finepass.py — Fine-grid dynamic pass (1024/256) for the high band.

Runs inside the mid/side high-band path, per channel, BEFORE the coarse
4096/1024 pass (docs/PLAN.md Section 2, placement approved 2026-09-04).
Flicker and sibilant bursts are fast events. A 23 ms window (at 44.1 kHz)
catches them without smearing, and the coarse pass then sees a steadier
signal.

Stages, in order:

  1. Flicker Tamer.  The same sub-band fast/slow envelope compressor as
     engine.FlickerTamerStage, run on the fine grid so it can see the
     10–50 Hz modulation that defines AI hash. At 4096/1024 anything
     above ~23 Hz averaged out inside one frame, which is why the tamer
     did little on real hash. Gated by the fine transient detector: a
     drum attack raises the fast envelope the same way flicker does.

  2. De-esser (spectral).  New. On sibilant frames — the 4–10 kHz band
     far above its 1–4 kHz reference — the band is turned down like a
     de-esser, but per bin: bins standing above the band's own smoothed
     spectrum get more of the cut, bins below it get less. It is NOT
     gated by the transient detector; a sibilant burst is exactly the
     transient the old de-harsh backed off from.

Everything is vectorised over frames except the envelope followers,
which are cheap first-order filters. Long files are processed in
chunks with a lead-in so the followers settle before each chunk's
audible region.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import numpy as np
from scipy import signal
from scipy.ndimage import median_filter, uniform_filter1d
from scipy.signal import lfilter

from .dsp import as_2d, edge_taper, freq_bin_indices
from .params import Params

_EPS = 1e-12
_CHUNK_S = 90.0
_LEAD_S = 0.5


def fine_pass_active(p: Params) -> bool:
    return bool(p.fine_pass) and (float(p.flicker_tame) > 1e-6 or float(p.deess) > 1e-6)


def _ema_frames(E: np.ndarray, coeff: float) -> np.ndarray:
    """First-order envelope follower along axis 1, initialised to the
    first frame (no attack from zero)."""
    if E.shape[1] == 0:
        return E
    zi = (coeff * E[:, :1]).astype(np.float64)
    y, _ = lfilter([1.0 - coeff], [1.0, -coeff], E.astype(np.float64), axis=1, zi=zi)
    return y


def _frame_coeff(hop: int, sr: int, ms: float) -> float:
    if ms <= 0:
        return 0.0
    return float(np.exp(-hop / (sr * ms / 1000.0)))


def _transient_weight(full_db: np.ndarray, sr: int, hop: int,
                      flux_thr_db: float = 9.0,
                      hold_ms: float = 30.0, release_ms: float = 150.0) -> np.ndarray:
    """1 on steady frames, 0 during an attack and its hold, ramping back
    over the release. Fine-grid twin of the engine's transient hold."""
    n = full_db.shape[0]
    w = np.ones(n, dtype=np.float32)
    if n < 3:
        return w
    flux = np.diff(full_db, prepend=full_db[:1])
    hold = max(1, int(round(hold_ms * 1e-3 * sr / hop)))
    rel = max(1, int(round(release_ms * 1e-3 * sr / hop)))
    hits = np.where(flux > flux_thr_db)[0]
    ramp = np.linspace(0.0, 1.0, rel + 1, dtype=np.float32)[1:]
    for i in hits:
        w[i:min(n, i + hold + 1)] = 0.0
        s = i + hold + 1
        e = min(n, s + rel)
        if e > s:
            w[s:e] = np.minimum(w[s:e], ramp[: e - s])
    return w


def _fine_core(x1: np.ndarray, sr: int, p: Params,
               stats: Optional[Dict[str, Any]] = None) -> np.ndarray:
    """One chunk. `stats`, when given, receives gate and attenuation
    diagnostics (used by tests and the corpus checks)."""
    n_fft, hop = int(p.fine_n_fft), int(p.fine_hop)
    n = x1.shape[0]
    f, _, Z = signal.stft(x1.astype(np.float32), fs=sr, window="hann",
                          nperseg=n_fft, noverlap=n_fft - hop, nfft=n_fft,
                          boundary="zeros", padded=True)
    P = (np.abs(Z) ** 2).astype(np.float32)          # (bins, frames)
    n_frames = P.shape[1]
    nyq = float(f[-1])
    gains = np.ones_like(P)

    # Transient hold on the HIGH band, like the coarse engine's gate: a
    # hit shows up there as a big jump even when bass and chords keep the
    # full-band level steady. 20 Hz hash only moves the band by a few dB.
    hi_idx = freq_bin_indices(f, 2000.0, nyq)
    hi_db = 10.0 * np.log10(P[hi_idx].sum(axis=0) + _EPS) if hi_idx.size else \
        10.0 * np.log10(P.sum(axis=0) + _EPS)
    w_nontrans = _transient_weight(hi_db, sr, hop)
    if stats is not None:
        stats["frames"] = int(n_frames)
        stats["gate_held_frac"] = float(np.mean(w_nontrans < 0.999))

    # ── 1. Flicker Tamer on the fine grid ───────────────────────────────
    ft = float(np.clip(p.flicker_tame, 0.0, 1.0))
    if ft > 1e-6:
        lo, hi = float(max(0.0, p.ft_start_hz)), float(min(nyq, p.ft_end_hz))
        nb = int(max(1, p.ft_n_bands))
        if hi > lo:
            edges = np.linspace(lo, hi, nb + 1)
            E = np.full((nb, n_frames), _EPS, dtype=np.float64)
            bands = []
            for i in range(nb):
                idx = freq_bin_indices(f, float(edges[i]), float(edges[i + 1]))
                bands.append(idx)
                if idx.size:
                    E[i] = P[idx].mean(axis=0) + _EPS
            e_fast = _ema_frames(E, _frame_coeff(hop, sr, p.ft_attack_ms))
            e_db = 10.0 * np.log10(np.maximum(e_fast, _EPS))
            # Floor follower: drops at once, rises slowly. The on-phases of
            # flicker are measured against this, not the running mean (a
            # 50 % square wave sits only 3 dB above its own mean).
            up = float(p.ft_floor_up_db_s) * hop / float(sr)      # dB per frame
            floor = np.empty_like(e_db)
            cur = e_db[:, 0].copy()
            for i in range(n_frames):
                cur = np.minimum(e_db[:, i], cur + up)
                floor[:, i] = cur
            ratio_db = e_db - floor
            # Only where the band flickers: spread of the detrended dB
            # envelope over the slow window. Steady wash has a small spread.
            win = max(3, int(round(float(p.ft_release_ms) * 1e-3 * sr / hop)))
            trend = uniform_filter1d(e_db, size=win, axis=1, mode="nearest")
            d = e_db - trend
            # Hits are not flicker: leave them out of the spread so a drum
            # every quarter note does not switch the tamer on everywhere.
            d = d * (w_nontrans[None, :] >= 0.999)
            spread = np.sqrt(np.maximum(uniform_filter1d(d * d, size=win, axis=1, mode="nearest"), 0.0))
            lo_s, hi_s = float(p.ft_flicker_min_db), float(p.ft_flicker_full_db)
            w_flicker = np.clip((spread - lo_s) / max(1e-6, hi_s - lo_s), 0.0, 1.0)
            excess = np.maximum(0.0, ratio_db - float(p.ft_thr_db))
            att = np.minimum(float(p.ft_slope) * excess, float(p.ft_max_att_db))
            att *= ft * w_flicker * w_nontrans[None, :]
            if stats is not None:
                stats["flicker_att_mean_db"] = float(att.mean())
                stats["flicker_att_max_db"] = float(att.max())
                stats["flicker_ratio_p95_db"] = float(np.percentile(ratio_db, 95))
                stats["flicker_spread_p50_db"] = float(np.median(spread))
            for i, idx in enumerate(bands):
                if idx.size == 0:
                    continue
                taper = edge_taper(f, idx, float(edges[i]), float(edges[i + 1]),
                                   float(p.ft_edge_hz)).astype(np.float32)
                g = (10.0 ** (-(att[i][None, :] * taper[:, None]) / 20.0)).astype(np.float32)
                gains[idx] *= g

    # ── 2. Spectral de-esser ────────────────────────────────────────────
    de = float(np.clip(p.deess, 0.0, 1.0))
    if de > 1e-6:
        idx = freq_bin_indices(f, float(p.de_start_hz), float(min(nyq, p.de_end_hz)))
        ref = freq_bin_indices(f, float(p.de_ref_start_hz), float(p.de_ref_end_hz))
        if idx.size >= 4 and ref.size >= 2:
            band_db = 10.0 * np.log10(P[idx].mean(axis=0) + _EPS)
            ref_db = 10.0 * np.log10(P[ref].mean(axis=0) + _EPS)
            excess = band_db - ref_db - float(p.de_thr_db)
            excess[ref_db < -120.0] = 0.0
            att_inst = np.clip(float(p.de_slope) * excess, 0.0, float(p.de_max_att_db))
            # Attack/release on the attenuation (dB), asymmetric.
            a_att = _frame_coeff(hop, sr, p.de_attack_ms)
            a_rel = _frame_coeff(hop, sr, p.de_release_ms)
            att = np.empty(n_frames, dtype=np.float64)
            cur = 0.0
            for i in range(n_frames):
                target = float(att_inst[i])
                c = a_att if target > cur else a_rel
                cur = c * cur + (1.0 - c) * target
                att[i] = cur
            # Per-bin weighting: bins above the band's own smoothed
            # spectrum take more of the cut, bins below take less.
            L = 10.0 * np.log10(P[idx] + _EPS).astype(np.float32)
            k = int(max(3, p.de_bin_med_bins)) | 1
            env = median_filter(L, size=(k, 1), mode="nearest")
            R = L - env
            w = 0.5 + np.clip(R - float(p.de_bin_excess_db) + 6.0, -6.0, 12.0) / 12.0
            w = np.clip(w, 0.0, 1.5).astype(np.float32)
            taper = edge_taper(f, idx, float(p.de_start_hz), float(min(nyq, p.de_end_hz)),
                               float(p.de_edge_hz)).astype(np.float32)
            att_bin = (de * att[None, :]).astype(np.float32) * w * taper[:, None]
            gains[idx] *= (10.0 ** (-att_bin / 20.0)).astype(np.float32)
            if stats is not None:
                stats["deess_att_mean_db"] = float(att.mean())
                stats["deess_att_max_db"] = float(att.max())
                stats["deess_active_frac"] = float(np.mean(att > 0.5))

    Z = Z * gains
    _, y = signal.istft(Z, fs=sr, window="hann", nperseg=n_fft, noverlap=n_fft - hop,
                        nfft=n_fft, input_onesided=True, boundary=True)
    y = np.asarray(y, dtype=np.float32)
    if y.shape[0] < n:
        y = np.pad(y, (0, n - y.shape[0]))
    return y[:n]


def fine_pass(x: np.ndarray, sr: int, p: Params,
              stats: Optional[Dict[str, Any]] = None) -> np.ndarray:
    """Run the fine-grid pass on a mono channel. Returns the same shape.
    Identity when the pass is off or both stages are at zero."""
    x2 = as_2d(np.asarray(x, dtype=np.float32))
    if not fine_pass_active(p) or x2.shape[0] < int(p.fine_n_fft) * 2:
        return x2
    x1 = x2[:, 0]
    n = x1.shape[0]
    chunk = int(_CHUNK_S * sr)
    lead = int(_LEAD_S * sr)
    if n <= chunk + lead:
        y1 = _fine_core(x1, sr, p, stats)
    else:
        y1 = np.zeros(n, dtype=np.float32)
        pos = 0
        while pos < n:
            a = max(0, pos - lead)
            b = min(n, pos + chunk)
            yc = _fine_core(x1[a:b], sr, p)
            y1[pos:b] = yc[pos - a:pos - a + (b - pos)]
            pos = b
    out = x2.copy()
    out[:, 0] = y1
    return out
