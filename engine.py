"""
engine.py — Core STFT processing loop for shimmer removal.

Architecture:
  process(x, sr, p) is the single entry point. It:
    1. Resolves band indices + tapers from Params.
    2. Instantiates a list of Stage objects (see STAGE_REGISTRY).
    3. Calls stage.init(...) once.
    4. For each STFT frame: computes shared gates, then calls stage.apply(...)
       for every enabled stage in order.
    5. Overlap-adds, unpads, mixes wet/dry, runs post-STFT filters, fades.

Stages are small callables with two methods:
  - init(p, sr, hop, freqs, nyq) -> None
  - apply(spec, ctx) -> spec

`ctx` is a dict carrying per-frame shared values (psd, w_noise, w_nontrans,
band_db, rng, eps) plus mutable per-stage state.

Adding a new stage = new Stage subclass + one entry in STAGE_REGISTRY.
No changes to the frame loop.
"""

from __future__ import annotations

import _winfix  # noqa: F401  # must precede scipy import on Windows

import math
from typing import Optional, Callable, List, Dict, Any

import numpy as np
from scipy.ndimage import median_filter, uniform_filter1d

from dsp import (
    as_2d, edge_taper, freq_bin_indices, frame_coeff,
    spectral_flatness, apply_high_shelf, apply_highpass,
)
from params import Params


# ═══════════════════════════════════════════════════════════════════════════
# Stage base class
# ═══════════════════════════════════════════════════════════════════════════

class Stage:
    """Base class for a per-frame STFT processing stage.

    Subclasses override:
      - enabled(p): whether this stage should run given current Params
      - init(p, sr, hop, freqs, nyq): allocate band indices, tapers, state
      - apply(spec, ctx): mutate and return spec for the current frame
    """

    name: str = "stage"

    def enabled(self, p: Params) -> bool:
        return True

    def init(self, p: Params, sr: int, hop: int,
             freqs: np.ndarray, nyq: float) -> None:
        pass

    def apply(self, spec: np.ndarray, ctx: Dict[str, Any]) -> np.ndarray:
        return spec


# ═══════════════════════════════════════════════════════════════════════════
# Stage: Downward expander  (was _stage_expander)
# ═══════════════════════════════════════════════════════════════════════════

class ExpanderStage(Stage):
    name = "expander"

    def enabled(self, p: Params) -> bool:
        return bool(p.expander)

    def init(self, p, sr, hop, freqs, nyq):
        self.idx = freq_bin_indices(freqs, p.exp_start_hz, p.exp_end_hz)
        self.threshold_db = float(p.exp_threshold_db)
        self.ratio = float(p.exp_ratio)
        self.att = frame_coeff(hop, sr, p.exp_attack_ms)
        self.rel = frame_coeff(hop, sr, p.exp_release_ms)
        self.g_sm = 1.0

    def apply(self, spec, ctx):
        if self.idx.size == 0:
            return spec
        eps = ctx["eps"]
        band_p = float(np.mean(ctx["psd"][self.idx]))
        band_db = 10.0 * math.log10(max(band_p, eps))
        if band_db < self.threshold_db:
            diff = self.threshold_db - band_db
            g_inst = float(10.0 ** (-(diff * (self.ratio - 1.0)) / 20.0))
        else:
            g_inst = 1.0
        if g_inst < self.g_sm:
            self.g_sm = self.att * self.g_sm + (1.0 - self.att) * g_inst
        else:
            self.g_sm = self.rel * self.g_sm + (1.0 - self.rel) * g_inst
        spec[self.idx, :] *= float(self.g_sm)
        return spec


# ═══════════════════════════════════════════════════════════════════════════
# Stage: Spectral denoise  (was _stage_denoise)
# ═══════════════════════════════════════════════════════════════════════════

class DenoiseStage(Stage):
    name = "denoise"

    def enabled(self, p: Params) -> bool:
        return float(p.denoise) > 1e-6

    def init(self, p, sr, hop, freqs, nyq):
        self.strength = float(np.clip(p.denoise, 0.0, 1.0))
        self.idx = freq_bin_indices(freqs, p.dn_start_hz, p.dn_end_hz)
        self.taper = edge_taper(
            freqs, self.idx,
            max(0.0, p.dn_start_hz), min(nyq, p.dn_end_hz), p.dn_edge_hz)

        self.minwin_frames = max(4, int((sr * (p.dn_minwin_ms / 1000.0)) / hop))
        block_sec = float(self.minwin_frames) * float(hop) / float(sr)

        self.a_psd = frame_coeff(hop, sr, p.dn_psd_smooth_ms)
        self.a_att = frame_coeff(hop, sr, p.dn_attack_ms)
        self.a_rel = frame_coeff(hop, sr, p.dn_release_ms)
        self.floor = float(10.0 ** (float(p.dn_floor_db) / 20.0))
        self.freq_smooth = int(max(1, p.dn_freq_smooth_bins))
        self.up_lin = float(10.0 ** ((float(p.dn_up_db_per_s) * block_sec) / 10.0))

        self.psd_sm: Optional[np.ndarray] = None
        self.noise_psd: Optional[np.ndarray] = None
        self.block_min: Optional[np.ndarray] = None
        self.block_ctr = 0
        self.gain_sm: Optional[np.ndarray] = (
            np.ones(self.idx.size, dtype=np.float32) if self.idx.size else None)
        self.steady_state = bool(p.steady_state_mode)

    def apply(self, spec, ctx):
        if self.idx.size == 0:
            return spec
        eps = ctx["eps"]
        psd = ctx["psd"]

        if self.psd_sm is None:
            self.psd_sm = psd.copy()
            self.noise_psd = psd.copy()
            self.block_min = psd.copy()
            self.block_ctr = 1
        else:
            self.psd_sm = self.a_psd * self.psd_sm + (1.0 - self.a_psd) * psd
            self.block_min = np.minimum(self.block_min, self.psd_sm)
            self.block_ctr += 1
            if self.block_ctr >= self.minwin_frames:
                self.noise_psd = np.minimum(
                    self.noise_psd * self.up_lin, self.block_min
                ).astype(np.float32)
                self.block_min.fill(np.inf)
                self.block_ctr = 0

        snr = self.psd_sm[self.idx] / (self.noise_psd[self.idx] + eps)
        k = 1.0 + 3.0 * self.strength
        g_inst = np.clip(
            self.floor + (1.0 - self.floor) * snr / (snr + k),
            self.floor, 1.0
        ).astype(np.float32)

        gsm = self.gain_sm
        down = g_inst < gsm
        gsm[down] = self.a_att * gsm[down] + (1.0 - self.a_att) * g_inst[down]
        gsm[~down] = self.a_rel * gsm[~down] + (1.0 - self.a_rel) * g_inst[~down]

        g_dn = uniform_filter1d(
            gsm, size=self.freq_smooth, mode="nearest").astype(np.float32)

        nt = 1.0 if self.steady_state else ctx["w_nontrans"]
        depth = self.strength * (0.5 + 0.5 * ctx["w_noise"]) * nt
        g_eff = 1.0 - (depth * self.taper) * (1.0 - g_dn)
        spec[self.idx, :] *= g_eff[:, None]
        return spec


# ═══════════════════════════════════════════════════════════════════════════
# Stage: De-resonator  (was _stage_deresonator)
# ═══════════════════════════════════════════════════════════════════════════

class DeResonatorStage(Stage):
    name = "deresonator"

    def enabled(self, p: Params) -> bool:
        return float(p.deres) > 1e-6

    def init(self, p, sr, hop, freqs, nyq):
        self.strength = float(np.clip(p.deres, 0.0, 1.0))
        self.idx = freq_bin_indices(freqs, p.deq_start_hz, p.deq_end_hz)
        self.taper = edge_taper(
            freqs, self.idx,
            max(0.0, p.deq_start_hz), min(nyq, p.deq_end_hz), p.deq_edge_hz)

        fm = int(max(3, p.deq_freq_med_bins))
        if fm % 2 == 0:
            fm += 1
        self.freq_med = fm
        self.freq_smooth = int(max(1, p.deq_freq_smooth_bins))
        self.thr_db = float(p.deq_thr_db)
        self.tonal_boost_db = float(p.deq_tonal_boost_db)
        self.slope = float(p.deq_slope)
        self.max_att_db = float(p.deq_max_att_db)
        self.density_lo = float(p.deq_density_lo)
        self.density_hi = float(p.deq_density_hi)
        self.persist_thr_db = float(p.deq_persist_thr_db)
        self.a_persist = frame_coeff(hop, sr, p.deq_persist_ms)

        self.persist = (
            np.zeros(self.idx.size, dtype=np.float32) if self.idx.size else None)
        self.steady_state = bool(p.steady_state_mode)
        self.density_floor = float(np.clip(p.deq_density_floor, 0.0, 1.0))

    def apply(self, spec, ctx):
        if self.idx.size == 0:
            return spec
        eps = ctx["eps"]
        mag = np.mean(np.abs(spec[self.idx, :]), axis=1).astype(np.float32) + eps
        L = np.log(mag)
        L_med = median_filter(L, size=self.freq_med, mode="nearest")
        residual = (L - L_med) * (20.0 / np.log(10.0))

        thr_eff = self.thr_db + self.tonal_boost_db * (1.0 - ctx["w_noise"])
        over = np.maximum(0.0, residual - thr_eff).astype(np.float32)

        mask = over > 0.0
        density = float(np.mean(mask)) if mask.size else 0.0
        w_narrow = 1.0 - float(np.clip(
            (density - self.density_lo) / max(1e-6, self.density_hi - self.density_lo),
            0.0, 1.0))
        if self.density_floor > 0.0 and self.density_floor > w_narrow:
            w_narrow = self.density_floor

        self.persist[:] = (
            self.a_persist * self.persist + (1.0 - self.a_persist) * over)
        gate = np.clip(self.persist / max(1e-6, self.persist_thr_db), 0.0, 1.0)

        att_db = np.minimum(
            self.slope * over * gate, self.max_att_db).astype(np.float32)
        gain = (10.0 ** (-att_db / 20.0)).astype(np.float32)

        nt = 1.0 if self.steady_state else ctx["w_nontrans"]
        depth = self.strength * nt * w_narrow
        g_eff = 1.0 - (depth * self.taper) * (1.0 - gain)
        if self.freq_smooth > 1:
            g_eff = uniform_filter1d(
                g_eff, size=self.freq_smooth, mode="nearest").astype(np.float32)
        spec[self.idx, :] *= g_eff[:, None]
        return spec


# ═══════════════════════════════════════════════════════════════════════════
# Stage: Shimmer suppression  (was _stage_shimmer)
# ═══════════════════════════════════════════════════════════════════════════

class ShimmerStage(Stage):
    name = "shimmer"

    def enabled(self, p: Params) -> bool:
        return True

    def init(self, p, sr, hop, freqs, nyq):
        start_hz = float(max(0.0, p.start_hz))
        end_hz = float(min(nyq, p.end_hz))
        if end_hz <= start_hz:
            raise ValueError("end_hz must be > start_hz")
        self.idx = freq_bin_indices(freqs, start_hz, end_hz)
        if self.idx.size < 8:
            raise ValueError(
                "Shimmer band too narrow; increase n_fft or widen band.")
        self.taper = edge_taper(freqs, self.idx, start_hz, end_hz, p.edge_hz)
        k = int(max(3, p.freq_med_bins))
        if k % 2 == 0:
            k += 1
        self.freq_med = k
        self.thr_db = float(p.thr_db)
        self.slope = float(p.slope)
        self.density_lo = float(p.density_lo)
        self.density_hi = float(p.density_hi)
        self.flat_start = float(p.flat_start)
        self.flat_end = float(p.flat_end)
        self.steady_state = bool(p.steady_state_mode)
        self.density_floor = float(np.clip(p.density_floor, 0.0, 1.0))

    def apply(self, spec, ctx):
        eps = ctx["eps"]
        mag = np.mean(np.abs(spec[self.idx, :]), axis=1).astype(np.float32) + eps
        P = mag ** 2
        flat_sh = spectral_flatness(P, eps)
        w_noise_sh = float(np.clip(
            (flat_sh - self.flat_start) / max(1e-6, self.flat_end - self.flat_start),
            0.0, 1.0))

        L = np.log(mag)
        L_med = median_filter(L, size=self.freq_med, mode="nearest")
        residual = (L - L_med) * (20.0 / np.log(10.0))

        over = residual - self.thr_db
        mask = over > 0.0
        density = float(np.mean(mask)) if mask.size else 0.0
        w_narrow = 1.0 - float(np.clip(
            (density - self.density_lo) / max(1e-6, self.density_hi - self.density_lo),
            0.0, 1.0))
        if self.density_floor > 0.0 and self.density_floor > w_narrow:
            w_narrow = self.density_floor

        nt = 1.0 if self.steady_state else ctx["w_nontrans"]
        depth = w_noise_sh * nt * w_narrow
        att_db = np.zeros_like(over, dtype=np.float32)
        att_db[mask] = (self.slope * over[mask]).astype(np.float32)
        gain = (10.0 ** (-att_db / 20.0)).astype(np.float32)
        g_eff = 1.0 - (depth * self.taper) * (1.0 - gain)
        spec[self.idx, :] *= g_eff[:, None]
        return spec


# ═══════════════════════════════════════════════════════════════════════════
# Stage: De-harsh (NEW)  — spectral de-esser for v5 "metallic fizz"
# ═══════════════════════════════════════════════════════════════════════════

class DeHarshStage(Stage):
    """Dynamic high-band tamer.

    Compares band energy in [dh_start_hz, dh_end_hz] against a mid-band
    reference in [dh_ref_start_hz, dh_ref_end_hz]. When the ratio exceeds
    `dh_thr_db`, applies a soft-knee gain reduction `dh_slope` dB/dB capped
    at `dh_max_att_db`. Attack/release smoothing uses frame-rate EMA.
    Runs after shimmer suppression — chases residual sibilance.
    """
    name = "deharsh"

    def enabled(self, p: Params) -> bool:
        return float(p.deharsh) > 1e-6

    def init(self, p, sr, hop, freqs, nyq):
        self.strength = float(np.clip(p.deharsh, 0.0, 1.0))
        self.idx = freq_bin_indices(freqs, p.dh_start_hz, p.dh_end_hz)
        self.taper = edge_taper(
            freqs, self.idx,
            max(0.0, p.dh_start_hz), min(nyq, p.dh_end_hz), p.dh_edge_hz)
        self.ref_idx = freq_bin_indices(freqs, p.dh_ref_start_hz, p.dh_ref_end_hz)
        self.thr_db = float(p.dh_thr_db)
        self.slope = float(p.dh_slope)
        self.max_att_db = float(p.dh_max_att_db)
        self.a_att = frame_coeff(hop, sr, p.dh_attack_ms)
        self.a_rel = frame_coeff(hop, sr, p.dh_release_ms)
        self.g_sm = 1.0
        self.steady_state = bool(p.steady_state_mode)

    def apply(self, spec, ctx):
        if self.idx.size == 0 or self.ref_idx.size == 0:
            return spec
        eps = ctx["eps"]
        psd = ctx["psd"]
        band_p = float(np.mean(psd[self.idx]))
        ref_p = float(np.mean(psd[self.ref_idx]))
        band_db = 10.0 * math.log10(max(band_p, eps))
        ref_db = 10.0 * math.log10(max(ref_p, eps))
        excess = band_db - ref_db - self.thr_db
        if excess > 0.0:
            att_db = min(self.slope * excess, self.max_att_db)
            g_inst = float(10.0 ** (-att_db / 20.0))
        else:
            g_inst = 1.0

        if g_inst < self.g_sm:
            self.g_sm = self.a_att * self.g_sm + (1.0 - self.a_att) * g_inst
        else:
            self.g_sm = self.a_rel * self.g_sm + (1.0 - self.a_rel) * g_inst

        nt = 1.0 if self.steady_state else ctx["w_nontrans"]
        depth = self.strength * nt
        g_eff = 1.0 - (depth * self.taper) * (1.0 - float(self.g_sm))
        spec[self.idx, :] *= g_eff[:, None]
        return spec


# ═══════════════════════════════════════════════════════════════════════════
# Stage: Flicker tamer (NEW) — sub-band AM compressor for Suno hash
# ═══════════════════════════════════════════════════════════════════════════

class FlickerTamerStage(Stage):
    """Sub-band amplitude-modulation compressor.

    The "metallic flickering hiss" Suno residual is amplitude-modulated
    narrowband noise in 5-8 kHz. Every other stage acts on instantaneous
    magnitude/spectrum; this stage explicitly compresses the AM envelope
    inside the band, which is the perceptually defining feature of the
    artifact ("flicker / shimmer").

    Operation per frame:
      1. Split [ft_start_hz, ft_end_hz] into `ft_n_bands` contiguous
         sub-bands with cosine tapers between them.
      2. For each sub-band, compute current band power E(t).
      3. Maintain per-sub-band fast EMA (~ft_attack_ms) and slow EMA
         (~ft_release_ms) of E.
      4. The "flicker amount" is the dB ratio E_fast / E_slow. When it
         exceeds `ft_thr_db`, attenuate the sub-band by
         `ft_slope * (excess - thr)` dB, capped at `ft_max_att_db`.
      5. Smooth the resulting per-bin gain across sub-band boundaries
         via the precomputed taper weights so the per-frame spec gets
         a smooth gain curve rather than discrete steps.

    Crucially does NOT multiply depth by `w_nontrans` -- the flicker IS
    the modulation, gating it off transients defeats the stage.
    """
    name = "flicker_tame"

    def enabled(self, p: Params) -> bool:
        return float(p.flicker_tame) > 1e-6

    def init(self, p, sr, hop, freqs, nyq):
        self.strength = float(np.clip(p.flicker_tame, 0.0, 1.0))
        start = float(max(0.0, p.ft_start_hz))
        end = float(min(nyq, p.ft_end_hz))
        if end <= start:
            self.bands: List[np.ndarray] = []
            self.weights: List[np.ndarray] = []
            self.global_idx = np.array([], dtype=np.int64)
            self.bin_band: np.ndarray = np.array([], dtype=np.int64)
            return

        n_bands = int(max(1, p.ft_n_bands))
        edges = np.linspace(start, end, n_bands + 1, dtype=np.float64)

        self.bands: List[np.ndarray] = []
        self.weights: List[np.ndarray] = []
        for i in range(n_bands):
            lo, hi = float(edges[i]), float(edges[i + 1])
            sub_idx = freq_bin_indices(freqs, lo, hi)
            if sub_idx.size == 0:
                self.bands.append(sub_idx)
                self.weights.append(np.zeros(0, dtype=np.float32))
                continue
            taper = edge_taper(freqs, sub_idx, lo, hi, float(p.ft_edge_hz))
            self.bands.append(sub_idx)
            self.weights.append(taper.astype(np.float32))

        # Pre-build a flat "global" index spanning the full ft band so we
        # can apply per-bin gain in one shot per frame.  bin_band[k]
        # holds the sub-band index for the k-th bin in global_idx.
        flat_idx_list = []
        flat_band_list = []
        flat_weight_list = []
        for bi, (sub_idx, w) in enumerate(zip(self.bands, self.weights)):
            if sub_idx.size == 0:
                continue
            flat_idx_list.append(sub_idx)
            flat_band_list.append(np.full(sub_idx.size, bi, dtype=np.int64))
            flat_weight_list.append(w)
        if flat_idx_list:
            self.global_idx = np.concatenate(flat_idx_list)
            self.bin_band = np.concatenate(flat_band_list)
            self.bin_weight = np.concatenate(flat_weight_list)
        else:
            self.global_idx = np.array([], dtype=np.int64)
            self.bin_band = np.array([], dtype=np.int64)
            self.bin_weight = np.array([], dtype=np.float32)

        self.thr_db = float(p.ft_thr_db)
        self.slope = float(p.ft_slope)
        self.max_att_db = float(p.ft_max_att_db)
        self.a_fast = frame_coeff(hop, sr, p.ft_attack_ms)
        self.a_slow = frame_coeff(hop, sr, p.ft_release_ms)

        self.E_fast = np.zeros(n_bands, dtype=np.float64)
        self.E_slow = np.zeros(n_bands, dtype=np.float64)
        self.first_frame = True

    def apply(self, spec, ctx):
        if self.global_idx.size == 0:
            return spec
        eps = ctx["eps"]
        psd = ctx["psd"]

        # Per-sub-band energy.
        n_bands = len(self.bands)
        E = np.empty(n_bands, dtype=np.float64)
        for bi, sub_idx in enumerate(self.bands):
            if sub_idx.size == 0:
                E[bi] = eps
            else:
                E[bi] = float(np.mean(psd[sub_idx])) + eps

        if self.first_frame:
            self.E_fast[:] = E
            self.E_slow[:] = E
            self.first_frame = False
        else:
            self.E_fast = self.a_fast * self.E_fast + (1.0 - self.a_fast) * E
            self.E_slow = self.a_slow * self.E_slow + (1.0 - self.a_slow) * E

        # Per-sub-band excess in dB.  Positive means E_fast > E_slow ->
        # AM "spike" -> compress.
        ratio_db = 10.0 * np.log10(
            np.maximum(self.E_fast, eps) / np.maximum(self.E_slow, eps))
        excess_db = np.maximum(0.0, ratio_db - self.thr_db)
        att_db_band = np.minimum(self.slope * excess_db, self.max_att_db)
        att_db_band *= self.strength

        # Map per-band attenuation to per-bin attenuation, weighted by
        # the inter-band taper so adjacent sub-bands smoothly blend.
        per_bin_att_db = att_db_band[self.bin_band] * self.bin_weight
        gain = (10.0 ** (-per_bin_att_db / 20.0)).astype(np.float32)
        spec[self.global_idx, :] *= gain[:, None]
        return spec


# ═══════════════════════════════════════════════════════════════════════════
# Stage: Narrow-tone killer (NEW) — steady-state Suno "whistle" notcher
# ═══════════════════════════════════════════════════════════════════════════

class NarrowToneStage(Stage):
    """Long-term per-bin tone notcher.

    Tracks a long-time-constant EMA of per-bin log magnitude across the
    band [tk_start_hz, tk_end_hz]. Compares each bin's EMA to a wide
    local-frequency median (the spectral envelope). Bins that sit
    persistently more than `tk_thr_db` above the envelope get notched
    by `tk_slope * (excess - thr)` dB, capped at `tk_max_att_db`.

    Unlike DeResonatorStage, this stage uses **no** per-frame density
    or transient gating — those gates were the reason DeResonator could
    not catch fixed Suno whistle tones (e.g. 16 kHz / 17.8 kHz) inside
    busy brilliance bands. Tones are defined here by their LONG-TERM
    excess, which is intrinsically robust to instantaneous spectral
    content.

    Warmup: depth ramps from 0 to 1 over `tk_warmup_ms` so the EMA has
    time to populate from the first frame's magnitude (which is used
    as initialization) before applying notches.
    """
    name = "tone_kill"

    def enabled(self, p: Params) -> bool:
        return float(p.tone_kill) > 1e-6

    def init(self, p, sr, hop, freqs, nyq):
        self.strength = float(np.clip(p.tone_kill, 0.0, 1.0))
        self.idx = freq_bin_indices(freqs, p.tk_start_hz, min(nyq, p.tk_end_hz))
        fm = int(max(3, p.tk_freq_med_bins))
        if fm % 2 == 0:
            fm += 1
        self.freq_med = fm
        self.thr_db = float(p.tk_thr_db)
        self.slope = float(p.tk_slope)
        self.max_att_db = float(p.tk_max_att_db)
        self.freq_smooth = int(max(1, p.tk_freq_smooth_bins))
        self.a_long = frame_coeff(hop, sr, p.tk_long_ms)
        self.warmup_frames = max(1, int((float(p.tk_warmup_ms) / 1000.0)
                                        * sr / hop))
        self.frame_i = 0
        self.long_log: Optional[np.ndarray] = None  # populated on first frame

    def apply(self, spec, ctx):
        if self.idx.size == 0:
            return spec
        eps = ctx["eps"]
        mag = np.mean(np.abs(spec), axis=1).astype(np.float32) + eps
        log_mag = np.log(mag)

        if self.long_log is None:
            self.long_log = log_mag.copy()
        else:
            self.long_log = (self.a_long * self.long_log
                             + (1.0 - self.a_long) * log_mag)

        env_log = median_filter(self.long_log, size=self.freq_med, mode="nearest")
        excess_db = (self.long_log - env_log) * (20.0 / np.log(10.0))

        ex = np.maximum(0.0, excess_db[self.idx] - self.thr_db)
        notch_db = np.minimum(self.slope * ex, self.max_att_db).astype(np.float32)

        warmup_w = float(min(1.0, self.frame_i / max(1, self.warmup_frames)))
        depth = self.strength * warmup_w
        eff_db = depth * notch_db

        if self.freq_smooth > 1:
            eff_db = uniform_filter1d(
                eff_db, size=self.freq_smooth, mode="nearest").astype(np.float32)

        gain = (10.0 ** (-eff_db / 20.0)).astype(np.float32)
        spec[self.idx, :] *= gain[:, None]

        self.frame_i += 1
        return spec


# ═══════════════════════════════════════════════════════════════════════════
# Stage: De-checkerboard (NEW) — periodic deconvolution-grid suppressor
# ═══════════════════════════════════════════════════════════════════════════

class DeCheckerStage(Stage):
    """Detect and attenuate periodic spectral peaks from deconvolution
    upsampling layers ("checkerboard" artifacts).

    Per frame, on log magnitude within [cb_start_hz, cb_end_hz]:
      1. Subtract local median to expose peaks.
      2. Autocorrelate along frequency axis.
      3. Find dominant lag in the allowed spacing range.
      4. EMA-track peak strength at that lag; only act when persistent.
      5. Attenuate bins whose residual-above-median matches the spacing.

    Guard by w_nontrans so transients are spared. Natural harmonics have
    pitch-dependent (not fixed-Hz) spacing so they don't persist at a
    constant lag for long; the EMA persistence gate filters them out.
    """
    name = "decheck"

    def enabled(self, p: Params) -> bool:
        return float(p.decheck) > 1e-6

    def init(self, p, sr, hop, freqs, nyq):
        self.strength = float(np.clip(p.decheck, 0.0, 1.0))
        self.idx = freq_bin_indices(freqs, p.cb_start_hz, p.cb_end_hz)
        self.freqs_in_band = freqs[self.idx] if self.idx.size else np.array([])
        self.bin_hz = float(freqs[1] - freqs[0]) if freqs.size > 1 else 1.0

        self.min_lag = max(2, int(round(p.cb_min_spacing_hz / self.bin_hz)))
        self.max_lag = max(
            self.min_lag + 1,
            int(round(p.cb_max_spacing_hz / self.bin_hz)))

        self.peak_thr_db = float(p.cb_peak_thr_db)
        self.max_att_db = float(p.cb_max_att_db)
        self.a_persist = frame_coeff(hop, sr, p.cb_persist_ms)
        self.persist_score = 0.0
        self.persist_lag = 0
        self.med_size = 7  # narrow median for peak exposure
        self.steady_state = bool(p.steady_state_mode)

    def apply(self, spec, ctx):
        n = self.idx.size
        if n < 2 * self.min_lag:
            return spec
        eps = ctx["eps"]
        mag = np.mean(np.abs(spec[self.idx, :]), axis=1).astype(np.float32) + eps
        L = np.log(mag)
        L_med = median_filter(L, size=self.med_size, mode="nearest")
        residual_db = (L - L_med) * (20.0 / np.log(10.0))

        peaks = np.maximum(residual_db - self.peak_thr_db, 0.0).astype(np.float32)
        if not np.any(peaks):
            self.persist_score *= self.a_persist
            return spec

        p_mean = float(np.mean(peaks))
        p_centered = peaks - p_mean
        norm = float(np.dot(p_centered, p_centered)) + eps

        max_lag = min(self.max_lag, n - 1)
        if max_lag <= self.min_lag:
            return spec

        best_lag = self.min_lag
        best_score = 0.0
        for lag in range(self.min_lag, max_lag + 1):
            s = float(np.dot(p_centered[:n - lag], p_centered[lag:])) / norm
            if s > best_score:
                best_score = s
                best_lag = lag

        # Persistence: require the same lag to score well across frames
        if best_lag == self.persist_lag:
            self.persist_score = (
                self.a_persist * self.persist_score
                + (1.0 - self.a_persist) * best_score)
        else:
            # Decay and migrate if new lag is clearly better
            self.persist_score *= self.a_persist
            if best_score > self.persist_score + 0.05:
                self.persist_lag = best_lag
                self.persist_score = (1.0 - self.a_persist) * best_score

        gate = float(np.clip(self.persist_score * 2.0, 0.0, 1.0))
        if gate < 1e-3 or self.persist_lag < self.min_lag:
            return spec

        # Build attenuation mask: attenuate peaks that align with a comb at
        # the persistent lag. For each bin, look at whether it's a local peak
        # AND has a matching peak `persist_lag` bins away.
        lag = self.persist_lag
        match = np.zeros(n, dtype=np.float32)
        left = peaks[:n - lag]
        right = peaks[lag:]
        pair_strength = np.minimum(left, right)
        match[:n - lag] += pair_strength
        match[lag:] += pair_strength

        att_db = np.minimum(self.strength * match * gate, self.max_att_db)
        gain = (10.0 ** (-att_db / 20.0)).astype(np.float32)
        depth = 1.0 if self.steady_state else ctx["w_nontrans"]
        g_eff = 1.0 - depth * (1.0 - gain)
        spec[self.idx, :] *= g_eff[:, None]
        return spec


# ═══════════════════════════════════════════════════════════════════════════
# Stage: Noise resynth  (was _stage_noise_resynth)
# ═══════════════════════════════════════════════════════════════════════════

class NoiseResynthStage(Stage):
    name = "noise_resynth"

    def enabled(self, p: Params) -> bool:
        return float(p.noise_resynth) > 1e-6

    def init(self, p, sr, hop, freqs, nyq):
        self.depth = float(np.clip(p.noise_resynth, 0.0, 1.0))
        start_hz = float(max(0.0, p.start_hz))
        end_hz = float(min(nyq, p.end_hz))
        self.idx = freq_bin_indices(freqs, start_hz, end_hz)
        self.taper = edge_taper(freqs, self.idx, start_hz, end_hz, p.edge_hz)
        self.flat_start = float(p.flat_start)
        self.flat_end = float(p.flat_end)

    def apply(self, spec, ctx):
        if self.idx.size == 0:
            return spec
        eps = ctx["eps"]
        mag = np.mean(np.abs(spec[self.idx, :]), axis=1).astype(np.float32) + eps
        P = mag ** 2
        flat = spectral_flatness(P, eps)
        w_noise = float(np.clip(
            (flat - self.flat_start) / max(1e-6, self.flat_end - self.flat_start),
            0.0, 1.0))
        if w_noise < 1e-3:
            return spec

        depth = (self.depth * w_noise) * self.taper
        phi = ctx["rng"].uniform(0.0, 2.0 * np.pi, size=self.idx.size).astype(np.float32)
        zph = (np.cos(phi) + 1j * np.sin(phi)).astype(np.complex64)

        for ch in range(spec.shape[1]):
            Zb = spec[self.idx, ch]
            Zrand = np.abs(Zb).astype(np.float32) * zph
            spec[self.idx, ch] = (1.0 - depth) * Zb + depth * Zrand
        return spec


# ═══════════════════════════════════════════════════════════════════════════
# Stage registry — ordering matters (see plan diagram)
# ═══════════════════════════════════════════════════════════════════════════

STAGE_REGISTRY: List[type] = [
    ExpanderStage,
    DenoiseStage,
    DeResonatorStage,
    ShimmerStage,
    DeHarshStage,
    FlickerTamerStage,  # AM compressor in 5-8 kHz (Suno hash flicker)
    DeCheckerStage,
    NarrowToneStage,    # after broadband suppression, before resynth
    NoiseResynthStage,
]


def _build_stages(p: Params, sr: int, hop: int,
                  freqs: np.ndarray, nyq: float) -> List[Stage]:
    """Instantiate and init enabled stages for this run."""
    stages: List[Stage] = []
    for cls in STAGE_REGISTRY:
        s = cls()
        if s.enabled(p):
            s.init(p, sr, hop, freqs, nyq)
            stages.append(s)
    return stages


# ═══════════════════════════════════════════════════════════════════════════
# Shared per-frame gates
# ═══════════════════════════════════════════════════════════════════════════

def _compute_noise_gate(spec, psd, dn_idx, p, eps):
    """Spectral flatness -> noise-likeness weight (0=tonal, 1=noise)."""
    if dn_idx.size:
        mag = np.mean(np.abs(spec[dn_idx, :]), axis=1).astype(np.float32) + eps
        P = mag ** 2
        flat = spectral_flatness(P, eps)
        band_db = 10.0 * math.log10(float(np.mean(P)) + eps)
    else:
        flat = spectral_flatness(psd, eps)
        band_db = 10.0 * math.log10(float(np.mean(psd)) + eps)

    w_noise = float(np.clip(
        (flat - p.flat_start) / max(1e-6, p.flat_end - p.flat_start), 0.0, 1.0))
    return w_noise, band_db


def _compute_transient_gate(band_db, p, prev_band_db):
    """Energy flux -> transient weight (1=steady, 0=transient)."""
    flux = max(0.0, band_db - prev_band_db) if prev_band_db is not None else 0.0
    w_trans = float(np.clip(
        (flux - p.flux_thr_db) / max(1e-6, p.flux_range_db), 0.0, 1.0))
    return 1.0 - w_trans


# ═══════════════════════════════════════════════════════════════════════════
# Post-STFT time-domain filters
# ═══════════════════════════════════════════════════════════════════════════

def apply_post_filters(y: np.ndarray, sr: int, p: Params) -> np.ndarray:
    """Apply sub-sonic HP, high-shelf, and presence shelf after STFT.

    Public so callers (e.g. the diff/Removed renderer in server.py) can
    pre-filter the dry reference signal with the same chain before
    subtracting. Otherwise even a tiny shelf/HP cut creates audible
    bass / shelf imprint in the diff that has nothing to do with what
    the STFT stages removed.
    """
    if p.subsonic_hz > 0:
        y = apply_highpass(y, sr, p.subsonic_hz)
    if abs(p.high_shelf_db) > 0.1 and p.high_shelf_hz > 0:
        y = apply_high_shelf(y, sr, p.high_shelf_hz, p.high_shelf_db)
    if abs(p.presence_db) > 0.1 and p.presence_hz > 0:
        y = apply_high_shelf(y, sr, p.presence_hz, p.presence_db)
    return y


# Back-compat alias (older internal callers used the underscore name).
_post_filters = apply_post_filters


# ═══════════════════════════════════════════════════════════════════════════
# Pre-analyze pass (Tier C: full-file two-pass detection)
# ═══════════════════════════════════════════════════════════════════════════

def _build_premask(x: np.ndarray, sr: int, p: Params,
                   freqs_main: np.ndarray) -> Optional[np.ndarray]:
    """Walk the file once at low cost, return a per-bin attenuation gain
    aligned with the main-pass `freqs_main` grid.

    Score per bin (in `pa_start_hz` .. `pa_end_hz`):
        excess_db = (long_term_log_mag - local_envelope) * 20/ln10
        am_depth  = std(mag) / mean(mag)             (over time)
        score     = max(0, excess_db - pa_thr_db) * (1 + pa_am_weight*am_depth)
        att_db    = min(score, pa_max_att_db)

    Returns None if the analysis cannot run (file too short, band empty).
    The mask is multiplicative gain in linear units (<=1.0).
    """
    if not p.pre_analyze:
        return None

    pa_n_fft = max(64, int(p.pa_n_fft))
    pa_hop = max(1, int(p.pa_hop))

    if x.shape[0] < pa_n_fft:
        return None

    max_n = int(max(0.0, p.pa_max_seconds) * sr)
    x_pa = x if (max_n <= 0 or x.shape[0] <= max_n) else x[:max_n, :]
    x_mono = np.mean(x_pa, axis=1) if x_pa.ndim > 1 else x_pa

    pa_win = np.hanning(pa_n_fft).astype(np.float32)
    pa_freqs = np.fft.rfftfreq(pa_n_fft, d=1.0 / sr)

    band_idx = freq_bin_indices(pa_freqs, p.pa_start_hz, p.pa_end_hz)
    if band_idx.size < 8:
        return None

    n_samples = int(x_mono.shape[0])
    sum_log = np.zeros(pa_freqs.size, dtype=np.float64)
    sum_lin = np.zeros(pa_freqs.size, dtype=np.float64)
    sum_lin_sq = np.zeros(pa_freqs.size, dtype=np.float64)
    cnt = 0

    for s in range(0, n_samples - pa_n_fft + 1, pa_hop):
        chunk = x_mono[s:s + pa_n_fft] * pa_win
        spec = np.fft.rfft(chunk, n=pa_n_fft)
        mag = np.abs(spec).astype(np.float64) + 1e-12
        sum_log += np.log(mag)
        sum_lin += mag
        sum_lin_sq += mag * mag
        cnt += 1

    if cnt < 4:
        return None

    mean_log = sum_log / cnt
    mean_lin = sum_lin / cnt
    var_lin = np.maximum(0.0, sum_lin_sq / cnt - mean_lin * mean_lin)
    am_depth = np.sqrt(var_lin) / np.maximum(mean_lin, 1e-12)

    fm = max(3, int(p.pa_freq_med_bins))
    if fm % 2 == 0:
        fm += 1
    env_log = median_filter(mean_log, size=fm, mode="nearest")
    excess_db = (mean_log - env_log) * (20.0 / np.log(10.0))

    score = np.zeros_like(excess_db)
    score[band_idx] = (
        np.maximum(0.0, excess_db[band_idx] - float(p.pa_thr_db))
        * (1.0 + float(p.pa_am_weight) * am_depth[band_idx])
    )
    att_db_pa = np.minimum(score, float(p.pa_max_att_db))

    # Resample mask onto the main-pass freqs grid via linear interp.
    mask_db_main = np.interp(freqs_main, pa_freqs, att_db_pa,
                             left=0.0, right=0.0)
    mask_gain = (10.0 ** (-mask_db_main / 20.0)).astype(np.float32)
    return mask_gain


# ═══════════════════════════════════════════════════════════════════════════
# Diagnostic readout (Tier C: 5-8 kHz energy + AM depth + top peaks)
# ═══════════════════════════════════════════════════════════════════════════

def _compute_diagnostic(x: np.ndarray, sr: int) -> Dict[str, Any]:
    """Return {band_5_8k_rms_db, band_5_8k_am_depth, top_peaks: [...]}.

    Computed at n_fft=4096, hop=2048, on up to 60 s of audio (mono mix).
    `top_peaks` is the strongest 5 narrow peaks above local envelope in
    4-14 kHz, each `{hz, excess_db}`.
    """
    empty = {
        "band_5_8k_rms_db": None,
        "band_5_8k_am_depth": None,
        "top_peaks": [],
    }
    x_mono = np.mean(x, axis=1) if x.ndim > 1 else x
    n_fft = 4096
    hop = 2048
    if x_mono.shape[0] < n_fft:
        return empty

    max_n = int(60.0 * sr)
    if x_mono.shape[0] > max_n:
        x_mono = x_mono[:max_n]

    win = np.hanning(n_fft).astype(np.float32)
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / sr)
    band_idx = freq_bin_indices(freqs, 5000.0, 8000.0)
    peak_band_idx = freq_bin_indices(freqs, 4000.0, 14000.0)
    if band_idx.size == 0:
        return empty

    n_samples = int(x_mono.shape[0])
    sum_log = np.zeros(freqs.size, dtype=np.float64)
    band_envelope = []
    cnt = 0

    for s in range(0, n_samples - n_fft + 1, hop):
        chunk = x_mono[s:s + n_fft] * win
        spec = np.fft.rfft(chunk, n=n_fft)
        mag = np.abs(spec).astype(np.float64) + 1e-12
        sum_log += np.log(mag)
        band_envelope.append(float(np.mean(mag[band_idx] ** 2)))
        cnt += 1

    if cnt < 4:
        return empty

    env = np.array(band_envelope, dtype=np.float64)
    band_rms = float(np.sqrt(np.mean(env)))
    band_rms_db = 20.0 * math.log10(max(band_rms, 1e-12))
    am_depth = float(np.std(env) / max(np.mean(env), 1e-12))

    mean_log = sum_log / cnt
    fm = 51
    env_log = median_filter(mean_log, size=fm, mode="nearest")
    excess_db = (mean_log - env_log) * (20.0 / np.log(10.0))

    if peak_band_idx.size:
        excess_in_band = excess_db[peak_band_idx]
        freqs_in_band = freqs[peak_band_idx]
        order = np.argsort(-excess_in_band)
        top_peaks = []
        for i in order:
            if excess_in_band[i] <= 1.0 or len(top_peaks) >= 5:
                break
            top_peaks.append({
                "hz": float(freqs_in_band[i]),
                "excess_db": float(excess_in_band[i]),
            })
    else:
        top_peaks = []

    return {
        "band_5_8k_rms_db": band_rms_db,
        "band_5_8k_am_depth": am_depth,
        "top_peaks": top_peaks,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Inner STFT pass (one iteration of the chain)
# ═══════════════════════════════════════════════════════════════════════════

def _run_stft_pass(x: np.ndarray, sr: int, p: Params,
                   premask: Optional[np.ndarray],
                   frame_cb: Optional[Callable[[float], None]]) -> np.ndarray:
    """One full STFT analysis -> stages -> overlap-add resynthesis pass.

    Returns audio of shape (samples, channels) trimmed to the original
    input length (i.e. padding is removed).
    """
    x = as_2d(x)
    n_fft, hop = int(p.n_fft), int(p.hop)
    if hop <= 0 or n_fft <= 0 or hop > n_fft:
        raise ValueError("Invalid n_fft/hop")

    x0 = np.pad(x, ((n_fft, n_fft), (0, 0)), mode="constant") if p.pad else x
    n_samples, n_ch = x0.shape
    win = np.hanning(n_fft).astype(np.float32)
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / sr)
    nyq = float(freqs[-1])
    eps = 1e-12

    dn_idx = freq_bin_indices(freqs, p.dn_start_hz, p.dn_end_hz)
    stages = _build_stages(p, sr, hop, freqs, nyq)

    rng = np.random.default_rng(int(p.seed))
    y = np.zeros((n_samples + n_fft, n_ch), dtype=np.float32)
    wsum = np.zeros(n_samples + n_fft, dtype=np.float32)
    total_frames = max(1, (n_samples + hop - 1) // hop)

    prev_band_db: Optional[float] = None

    for frame_i, s in enumerate(range(0, n_samples, hop)):
        if frame_cb and frame_i % 50 == 0:
            frame_cb(frame_i / total_frames)

        frame = np.zeros((n_fft, n_ch), dtype=np.float32)
        chunk = x0[s:s + n_fft, :]
        frame[:chunk.shape[0], :] = chunk
        spec = np.fft.rfft(frame * win[:, None], n=n_fft, axis=0)

        if premask is not None:
            spec *= premask[:, None]

        psd = np.mean(np.abs(spec) ** 2, axis=1).astype(np.float32) + eps

        w_noise, band_db = _compute_noise_gate(spec, psd, dn_idx, p, eps)
        w_nontrans = _compute_transient_gate(band_db, p, prev_band_db)
        prev_band_db = band_db

        ctx: Dict[str, Any] = {
            "psd": psd,
            "w_noise": w_noise,
            "w_nontrans": w_nontrans,
            "band_db": band_db,
            "rng": rng,
            "eps": eps,
        }

        for stage in stages:
            spec = stage.apply(spec, ctx)

        out = np.fft.irfft(spec, n=n_fft, axis=0).astype(np.float32) * win[:, None]
        y[s:s + n_fft, :] += out
        wsum[s:s + n_fft] += win ** 2

    wsum = np.maximum(wsum, 1e-12)
    y = y[:n_samples, :] / wsum[:n_samples, None]

    if p.pad:
        y = y[n_fft:-n_fft, :]

    return y


# ═══════════════════════════════════════════════════════════════════════════
# Main entry point
# ═══════════════════════════════════════════════════════════════════════════

def process(x: np.ndarray, sr: int, p: Params,
            progress_callback: Optional[Callable[[float], None]] = None,
            diagnostic_out: Optional[Dict[str, Any]] = None
            ) -> np.ndarray:
    """Run the full shimmer-removal pipeline on audio samples.

    Args:
        x: Audio, shape (samples,) or (samples, channels), float32.
        sr: Sample rate in Hz.
        p: Processing parameters.
        progress_callback: Optional callable(fraction: 0..1) for progress.
        diagnostic_out: Optional dict that, if provided, will be populated
            with `{"before": {...}, "after": {...}}` diagnostic readouts
            (5-8 kHz energy + AM depth + top narrow peaks).  Set
            `p.diagnostic = True` to force collection without passing
            this dict explicitly.

    Returns:
        Processed audio, same shape as input.
    """
    x_in = as_2d(np.asarray(x, dtype=np.float32))

    n_iter = int(p.iterations)
    if n_iter < 1:
        n_iter = 1
    if n_iter > 3:
        n_iter = 3

    want_diag = bool(p.diagnostic) or (diagnostic_out is not None)
    diag_before = _compute_diagnostic(x_in, sr) if want_diag else None

    # Pre-analyze: build a per-bin mask once, applied every frame of every
    # iteration as a pre-filter on the spec before any stage runs.
    n_fft = int(p.n_fft)
    freqs_main = np.fft.rfftfreq(n_fft, d=1.0 / sr)
    premask = _build_premask(x_in, sr, p, freqs_main)

    audio = x_in
    iter_frac = 1.0 / float(n_iter)
    for it in range(n_iter):
        def _cb(frac: float, _it: int = it) -> None:
            if progress_callback:
                progress_callback((float(_it) + frac) * iter_frac)
        audio = _run_stft_pass(audio, sr, p, premask, _cb)

    n = min(x_in.shape[0], audio.shape[0])
    audio = audio[:n, :]
    x_ref = x_in[:n, :]
    mix_val = float(np.clip(p.mix, 0.0, 1.0))
    y = mix_val * audio + (1.0 - mix_val) * x_ref

    y = _post_filters(y, sr, p)

    fade = int(sr * (float(p.fade_ms) / 1000.0))
    if fade > 1 and y.shape[0] > 2 * fade:
        ramp = np.linspace(0.0, 1.0, fade, dtype=np.float32)[:, None]
        y[:fade, :] *= ramp
        y[-fade:, :] *= ramp[::-1]

    if progress_callback:
        progress_callback(1.0)

    if want_diag and diagnostic_out is not None:
        diag_after = _compute_diagnostic(y, sr)
        diagnostic_out["before"] = diag_before
        diagnostic_out["after"] = diag_after

    return y.squeeze()
