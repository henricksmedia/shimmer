"""
perceptual.py — How much of what we removed could a listener actually hear?

Shimmer used to answer that with `purity` (detect.py): the share of removed
energy that landed outside a mask of transient frames and narrow partials.
That number is not a measurement. On three finished commercial masters the
mask covers 84-95 % of all energy above 2 kHz and 98-100 % above 10 kHz, so
any preset confined to the sustained top end scores ~1.0 whether it removed
hiss or a cymbal. See docs/BRIGHTNESS-ASSESSMENT.md §2.5.

This module replaces it with the auditory model from **ITU-R BS.1387**
(PEAQ; first published 1998, revised BS.1387-2 in 2023), implemented from
Peter Kabal's reference interpretation and MATLAB (McGill University, 2002,
"An Examination and Interpretation of ITU-R BS.1387"), which is the canonical
open description of the standard. Equation and function names below match his
report so the two can be read side by side.

Why this standard and not a home-grown flatness or tonality test: it works in
the *partial loudness* domain of a hearing model, so a change is scored by how
audible it is against the masking the rest of the music provides — which is
the actual question ("would anyone hear what we took?"), and the one a
mask-location ratio cannot ask.

Three measures come out, and they answer different questions:

  * `lin_dist`      Linear (spectral-tilt) distortion. Broadband tilt is never
                    an artifact, so this is unambiguous damage no matter what
                    the reference contains. It is Shimmer's actual failure
                    mode, and for MUSIC it is the strongest single predictor
                    of perceived degradation in the literature (Delgado &
                    Herre, arXiv:2212.01467 — PEAQ's individual MOVs predict
                    well even where its composite ODG does not).
  * `missing`       Loudness of components present in the reference and gone
                    from the test. Note the caveat: Shimmer's "reference" is
                    an artifact-laden AI render, so removing the artifact also
                    registers here. Read it with the artifact evidence, never
                    alone.
  * `added`         Loudness of components the processing introduced. A
                    subtractive cleaner should sit near zero; anything else
                    means a stage is generating signal.

Units are sones (partial loudness), not dB, and not a ratio. Zero means "no
audible difference". Nothing here is normalised by where the change happened,
so it cannot become a tautology the way `purity` did.

Deliberate scope: the FFT-based (Basic) ear model, not the Advanced filter
bank. Both are defined by the same recommendation; the disturbance formulae
are identical given excitation patterns, the FFT model is fully specified in
Kabal with reference code to check against, and Shimmer is an STFT pipeline
throughout. The MOV-mapping stage that turns these into a single ODG grade is
deliberately NOT implemented: it is trained on 1998 codec data and is the part
the 2022 analysis found wanting. We use the model outputs directly.
"""

from __future__ import annotations

from . import _winfix  # noqa: F401  # must precede scipy import on Windows

import math
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import numpy as np
from scipy.signal import resample_poly

# ── Model constants (BS.1387 / Kabal) ──────────────────────────────────
SR_MODEL = 48000          # the standard is defined at 48 kHz
NF = 2048                 # frame length, samples
NADV = NF // 2            # 50 % overlap
FSS = SR_MODEL / NADV     # frame rate, Hz (46.875)
LP_SPL = 92.0             # dB SPL for a full-scale 1019.5 Hz sine
FCAL = 1019.5             # calibration tone, Hz

F_LO, F_HI = 80.0, 18000.0
DZ_BASIC = 0.25           # Bark resolution, Basic version
E_MIN = 1e-12

TAU_MIN = 0.008           # excitation time smearing
TAU_100_EXC = 0.030
TAU_100_ADAPT = 0.050     # adaptation and modulation stages
M1_BASIC, M2_BASIC = 3, 4

E0 = 1e4                  # loudness scaling
C_FFT = 1.07664           # loudness calibration, FFT model
E_LOUD = 0.23

# Distortion-loudness parameters (Kabal §5.3; MATLAB PQmovNLoudB).
ALPHA = 1.5
TF0 = 0.15
S0_ADDED = 0.5            # RmsNoiseLoud
S0_MISSING = 1.0          # RmsMissingComponents
S0_LINDIST = 1.0          # AvgLinDist: Kabal eq. 105-106, p. 39 (alpha 1.5,
                          # T0 0.15, S0 1). The Basic-model MATLAB's S0 = 0.5
                          # belongs to RmsNoiseLoud only (Kabal H.2).

DELAY_S = 0.5             # delayed averaging (Kabal §5.2.1)
N_THRES_SONE = 0.1        # loudness gate (Kabal §5.3.1)
GATE_DELAY_S = 0.05


def _bark(f: np.ndarray | float) -> np.ndarray:
    return 7.0 * np.arcsinh(np.asarray(f, dtype=np.float64) / 650.0)


def _bark_inv(z: np.ndarray | float) -> np.ndarray:
    return 650.0 * np.sinh(np.asarray(z, dtype=np.float64) / 7.0)


@dataclass(frozen=True)
class _Bands:
    """Critical-band table and the DFT-bin mapping onto it."""
    n: int
    fc: np.ndarray
    fl: np.ndarray
    fu: np.ndarray
    dz: float
    kl: np.ndarray      # first DFT bin of each band
    ku: np.ndarray      # last DFT bin
    ul: np.ndarray      # fractional weight of the first bin
    uu: np.ndarray      # fractional weight of the last bin


def _critical_bands(dz: float = DZ_BASIC) -> _Bands:
    """PQCB + PQ_CBMapping. Bands are `dz` Bark wide from 80 Hz to 18 kHz."""
    z_lo, z_hi = float(_bark(F_LO)), float(_bark(F_HI))
    n = int(math.ceil((z_hi - z_lo) / dz))
    zl = z_lo + np.arange(n) * dz
    zu = np.minimum(z_lo + np.arange(1, n + 1) * dz, z_hi)
    zc = 0.5 * (zl + zu)
    fl, fc, fu = _bark_inv(zl), _bark_inv(zc), _bark_inv(zu)

    df = SR_MODEL / NF
    n_bins = NF // 2
    kl = np.zeros(n, dtype=int)
    ku = np.zeros(n, dtype=int)
    ul = np.zeros(n)
    uu = np.zeros(n)
    for i in range(n):
        for k in range(n_bins + 1):
            if (k + 0.5) * df > fl[i]:
                kl[i] = k
                ul[i] = (min(fu[i], (k + 0.5) * df)
                         - max(fl[i], (k - 0.5) * df)) / df
                break
        for k in range(n_bins, -1, -1):
            if (k - 0.5) * df < fu[i]:
                ku[i] = k
                uu[i] = 0.0 if kl[i] == k else (
                    min(fu[i], (k + 0.5) * df)
                    - max(fl[i], (k - 0.5) * df)) / df
                break
    return _Bands(n=n, fc=fc, fl=fl, fu=fu, dz=dz,
                  kl=kl, ku=ku, ul=ul, uu=uu)


_BANDS: Optional[_Bands] = None


def bands() -> _Bands:
    global _BANDS
    if _BANDS is None:
        _BANDS = _critical_bands()
    return _BANDS


def _hann_gain() -> float:
    """PQ_GL: window gain putting a full-scale FCAL sine at LP_SPL dB.

    Kabal writes Amax = 32768 for 16-bit input; Shimmer carries float audio
    normalised to +/-1, so Amax = 1 here. Same calibration, different unit.
    """
    w = NF - 1
    df = 1.0 / NF
    fc_n = FCAL / SR_MODEL
    k = math.floor(fc_n / df)
    dfn = min((k + 1) * df - fc_n, fc_n - k * df)
    dfw = dfn * w
    gp = math.sin(math.pi * dfw) / (math.pi * dfw * (1.0 - dfw ** 2))
    return 10.0 ** (LP_SPL / 20.0) / (gp * (1.0 / 4.0) * w)


def _ear_weight(freqs: np.ndarray) -> np.ndarray:
    """Outer- and middle-ear response, linear (Kabal eq. 6).

    A(f) dB = -2.184 (f/1k)^-0.8 + 6.5 exp(-0.6 (f/1k - 3.3)^2)
              - 0.001 (f/1k)^3.6
    Zero at DC, about -1.9 dB at 1 kHz, peaking near +5.6 dB at 3.3 kHz.
    """
    fk = np.asarray(freqs, dtype=np.float64) / 1000.0
    w = np.zeros_like(fk)
    nz = fk > 0
    a_db = (-2.184 * fk[nz] ** -0.8
            + 6.5 * np.exp(-0.6 * (fk[nz] - 3.3) ** 2)
            - 0.001 * fk[nz] ** 3.6)
    w[nz] = 10.0 ** (a_db / 20.0)
    return w


def _internal_noise(fc: np.ndarray) -> np.ndarray:
    """Ear's own noise floor, band energies (Kabal eq. 18):
    E_IN dB = 1.456 (f/1k)^-0.8."""
    return 10.0 ** ((1.456 * (np.asarray(fc) / 1000.0) ** -0.8) / 10.0)


def _excitation_index(fc: np.ndarray) -> np.ndarray:
    """PQ_exIndex: s(f), how much of the excitation contributes to loudness."""
    f = np.asarray(fc, dtype=np.float64)
    s_db = (-2.0 - 2.05 * np.arctan(f / 4000.0)
            - 0.75 * np.arctan((f / 1600.0) ** 2))
    return 10.0 ** (s_db / 10.0)


def _energy_threshold(fc: np.ndarray) -> np.ndarray:
    """PQ_enThresh: threshold in quiet, 3.64 (f/1k)^-0.8 dB."""
    return 10.0 ** ((3.64 * (np.asarray(fc) / 1000.0) ** -0.8) / 10.0)


def _time_constants(fc: np.ndarray, tau_100: float) -> np.ndarray:
    """PQtConst: per-band smoothing coefficient a = exp(-1/(Fss*tau))."""
    tau = TAU_MIN + (100.0 / np.asarray(fc)) * (tau_100 - TAU_MIN)
    return np.exp(-1.0 / (FSS * tau))


def _spread_norm(b: _Bands) -> np.ndarray:
    """Spreading applied to unit energy, used to normalise the real thing."""
    return _spread(np.ones(b.n), b, norm=None)


_LOWER: Dict[int, np.ndarray] = {}


def _lower_matrix(b: _Bands) -> np.ndarray:
    """Level-independent lower skirt as a matrix: es[i] = sum_{k>=i}
    a_le^(k-i) ene[k], the closed form of the downward recursion."""
    key = id(b)
    if key not in _LOWER:
        a_le = (10.0 ** (-2.7 * b.dz)) ** 0.4
        m = np.arange(b.n)
        d = m[:, None] - m[None, :]              # d[k, i] = k - i
        _LOWER[key] = np.where(d >= 0, a_le ** np.maximum(d, 0), 0.0)
    return _LOWER[key]


def _spread_frames(E: np.ndarray, b: _Bands,
                   norm: Optional[np.ndarray]) -> np.ndarray:
    """PQ_SpreadCB for a block of frames at once, [frames, bands].

    Lower skirt is fixed at -27 dB/Bark; the upper skirt flattens as level
    rises (-24 - 230/fc + level dependence), which is what makes loud content
    mask more of its neighbourhood. Powers combine with exponent 0.4.

    The per-band loops of the reference implementation are the two matrix
    products below: the lower skirt does not depend on level, so it is one
    constant matrix; the upper skirt does, so its matrix is built per frame
    from a_uce^(j - i). Results match the loop form to rounding.
    """
    n, dz = b.n, b.dz
    e_pow = 0.4
    E = np.asarray(E, dtype=np.float64)
    a_l = 10.0 ** (-2.7 * dz)
    a_uc = 10.0 ** ((-2.4 - 23.0 / b.fc) * dz)
    a_uce = a_uc[None, :] * np.power(np.maximum(E, E_MIN), 0.2 * dz)

    m = np.arange(n)
    g_il = (1.0 - a_l ** (m + 1)) / (1.0 - a_l)
    nm = (n - m).astype(np.float64)
    with np.errstate(divide="ignore", invalid="ignore"):
        g_iu = np.where(np.abs(a_uce - 1.0) < 1e-12, nm[None, :],
                        (1.0 - a_uce ** nm[None, :]) / (1.0 - a_uce))
    en = E / (g_il[None, :] + g_iu - 1.0)
    ene = np.power(np.maximum(en, 0.0), e_pow)
    a_uce_e = np.power(a_uce, e_pow)

    d = m[None, :] - m[:, None]                  # d[i, j] = j - i
    upper = np.where((d > 0)[None, :, :],
                     np.power(a_uce_e[:, :, None], np.maximum(d, 0)[None, :, :]),
                     0.0)
    es = ene @ _lower_matrix(b) + np.einsum("fi,fij->fj", ene, upper)
    es = np.power(es, 1.0 / e_pow)
    return es if norm is None else es / norm[None, :]


def _spread(e: np.ndarray, b: _Bands, norm: Optional[np.ndarray]) -> np.ndarray:
    """One frame of `_spread_frames`."""
    return _spread_frames(np.asarray(e, dtype=np.float64)[None, :], b, norm)[0]


_GROUP: Dict[Tuple[int, int], np.ndarray] = {}


def _band_matrix(b: _Bands, n_bins: int) -> np.ndarray:
    """PQ_CBMapping as one [bins, bands] matrix: the two edge bins of each
    band weighted fractionally, the interior bins fully."""
    key = (id(b), n_bins)
    if key not in _GROUP:
        W = np.zeros((n_bins, b.n))
        for i in range(b.n):
            lo, hi = int(b.kl[i]), int(b.ku[i])
            W[lo, i] = b.ul[i]
            if hi > lo:
                W[lo + 1:hi, i] = 1.0
                W[hi, i] = b.uu[i]
        _GROUP[key] = W
    return _GROUP[key]


_CHUNK_FRAMES = 256


def excitation_patterns(x: np.ndarray, sr: int) -> Tuple[np.ndarray, np.ndarray]:
    """Run the ear model. Returns (unsmeared, smeared) excitation patterns,
    each [frames, bands], in the model's energy units."""
    b = bands()
    mono = np.asarray(x, dtype=np.float64)
    if mono.ndim > 1:
        mono = mono.mean(axis=1)
    if sr != SR_MODEL:
        g = math.gcd(int(sr), SR_MODEL)
        mono = resample_poly(mono, SR_MODEL // g, int(sr) // g)

    win = _hann_gain() * (0.5 - 0.5 * np.cos(
        2.0 * np.pi * np.arange(NF) / (NF - 1)))
    freqs = np.fft.rfftfreq(NF, 1.0 / SR_MODEL)
    w2 = _ear_weight(freqs) ** 2

    n_frames = max(0, 1 + (len(mono) - NF) // NADV)
    if n_frames == 0:
        return np.zeros((0, b.n)), np.zeros((0, b.n))

    e_int = _internal_noise(b.fc)
    norm = _spread_norm(b)
    a_exc = _time_constants(b.fc, TAU_100_EXC)
    W = _band_matrix(b, freqs.size)

    # Frames in blocks: FFT, ear weighting, band grouping and spreading are
    # all frame-independent, so they run as matrix operations per block.
    e_unsmeared = np.zeros((n_frames, b.n))
    for t0 in range(0, n_frames, _CHUNK_FRAMES):
        t1 = min(n_frames, t0 + _CHUNK_FRAMES)
        idx = t0 * NADV + np.arange(t1 - t0)[:, None] * NADV + np.arange(NF)[None, :]
        seg = mono[idx] * win[None, :]
        x2 = np.abs(np.fft.rfft(seg, axis=1)) ** 2 * w2[None, :]
        eb = np.maximum(x2 @ W, E_MIN)
        e_unsmeared[t0:t1] = _spread_frames(eb + e_int[None, :], b, norm)

    # Forward masking: decay is smoothed, onsets are instantaneous.
    e_smeared = np.zeros((n_frames, b.n))
    prev = np.zeros(b.n)
    one_minus = 1.0 - a_exc
    for t in range(n_frames):
        es = e_unsmeared[t]
        prev = a_exc * prev + one_minus * es
        e_smeared[t] = np.maximum(prev, es)
    return e_unsmeared, e_smeared


def loudness(e_smeared: np.ndarray) -> np.ndarray:
    """PQloud: total loudness per frame, in sones."""
    b = bands()
    et = _energy_threshold(b.fc)
    s = _excitation_index(b.fc)
    ets = C_FFT * np.power(et / (s * E0), E_LOUD)
    n = ets * (np.power(np.maximum(
        1.0 - s + s * e_smeared / et, 0.0), E_LOUD) - 1.0)
    return (24.0 / b.n) * np.maximum(n, 0.0).sum(axis=1)


def _adapt(e_ref: np.ndarray, e_test: np.ndarray
           ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """PQadapt: level and pattern adaptation.

    Removes the part of the difference that is a slow level or spectral
    offset rather than a distortion, so a track that is merely quieter or
    gently tilted is not scored as damaged twice. Returns the adapted
    patterns for both signals plus the *unadapted* reference, which
    AvgLinDist compares against.
    """
    b = bands()
    a = _time_constants(b.fc, TAU_100_ADAPT)
    one_minus = 1.0 - a
    n_frames = e_ref.shape[0]

    p_ref = np.zeros(b.n)
    p_test = np.zeros(b.n)
    rn = np.zeros(b.n)
    rd = np.zeros(b.n)
    pc_ref = np.zeros(b.n)
    pc_test = np.zeros(b.n)

    ep_ref = np.zeros_like(e_ref)
    ep_test = np.zeros_like(e_test)

    idx = np.arange(b.n)
    lo = np.maximum(idx - M1_BASIC, 0)
    hi = np.minimum(idx + M2_BASIC, b.n - 1)
    cnt = (hi - lo + 1).astype(np.float64)

    def _neighbour_mean(r: np.ndarray) -> np.ndarray:
        cs = np.concatenate(([0.0], np.cumsum(r)))
        return (cs[hi + 1] - cs[lo]) / cnt

    for t in range(n_frames):
        p_ref = a * p_ref + one_minus * e_ref[t]
        p_test = a * p_test + one_minus * e_test[t]
        sd = p_test.sum()
        sn = np.sqrt(np.maximum(p_test * p_ref, 0.0)).sum()
        cl = (sn / sd) ** 2 if sd > 0 else 1.0

        if cl > 1.0:
            er, et_ = e_ref[t] / cl, e_test[t]
        else:
            er, et_ = e_ref[t], e_test[t] * cl

        rn = a * rn + et_ * er
        rd = a * rd + er * er
        safe = (rd > 0) & (rn > 0)
        r1 = np.ones(b.n)
        r2 = np.ones(b.n)
        ge = safe & (rn >= rd)
        lt = safe & (rn < rd)
        r2[ge] = rd[ge] / rn[ge]
        r1[lt] = rn[lt] / rd[lt]

        # Average the correction over neighbouring bands, then smooth in time.
        c1 = _neighbour_mean(r1)
        c2 = _neighbour_mean(r2)
        pc_ref = a * pc_ref + one_minus * c1
        pc_test = a * pc_test + one_minus * c2
        ep_ref[t] = er * pc_ref
        ep_test[t] = et_ * pc_test
    return ep_ref, ep_test, e_ref, e_test


def _modulation(e_unsmeared: np.ndarray) -> np.ndarray:
    """PQmodPatt: how strongly each band is modulating, per frame."""
    b = bands()
    a = _time_constants(b.fc, TAU_100_ADAPT)
    one_minus = 1.0 - a
    e_pow = 0.3
    n_frames = e_unsmeared.shape[0]
    m = np.zeros_like(e_unsmeared)
    de = np.zeros(b.n)
    eavg = np.zeros(b.n)
    prev = np.zeros(b.n)
    for t in range(n_frames):
        ee = np.power(np.maximum(e_unsmeared[t], 0.0), e_pow)
        de = a * de + one_minus * FSS * np.abs(ee - prev)
        eavg = a * eavg + one_minus * ee
        prev = ee
        m[t] = de / (1.0 + eavg / 0.3)
    return m


def _disturbance(ep_a: np.ndarray, ep_b: np.ndarray,
                 mod_a: np.ndarray, mod_b: np.ndarray,
                 s0_a: float, s0_b: float) -> np.ndarray:
    """Partial loudness of what B has that A does not (Kabal eq. 87).

    Swapping the arguments turns "added" into "missing" — that is exactly how
    the standard defines RmsMissingComponents, with a different S0.
    """
    b = bands()
    et = _internal_noise(b.fc)[None, :]
    s_a = TF0 * mod_a + s0_a
    s_b = TF0 * mod_b + s0_b
    beta = np.exp(-ALPHA * (ep_b - ep_a) / np.maximum(ep_a, 1e-30))
    num = np.maximum(s_b * ep_b - s_a * ep_a, 0.0)
    den = et + s_a * ep_a * beta
    nl = (np.power(et / s_b, E_LOUD)
          * (np.power(1.0 + num / np.maximum(den, 1e-30), E_LOUD) - 1.0))
    return (24.0 / b.n) * np.maximum(nl.sum(axis=1), 0.0)


@dataclass
class Damage:
    """What the processing did, in sones of partial loudness. Zero is
    inaudible. See the module docstring for how to read each field."""
    lin_dist: float
    missing: float
    added: float
    asym: float          # added + 0.5 * missing (the standard's combination)
    frames: int
    gated_frames: int

    def as_dict(self) -> Dict[str, float]:
        return {"lin_dist": round(self.lin_dist, 4),
                "missing": round(self.missing, 4),
                "added": round(self.added, 4),
                "asym": round(self.asym, 4),
                "frames": self.frames,
                "gated_frames": self.gated_frames}


def measure_damage(reference: np.ndarray, test: np.ndarray,
                   sr: int) -> Damage:
    """Compare a processed signal against what went in.

    `reference` is the audio before processing, `test` after. Both must be the
    same length and sample rate. Returns audible-difference measures in sones.
    """
    ref = np.asarray(reference, dtype=np.float64)
    tst = np.asarray(test, dtype=np.float64)
    n = min(ref.shape[0], tst.shape[0])
    ref, tst = ref[:n], tst[:n]

    eu_r, es_r = excitation_patterns(ref, sr)
    eu_t, es_t = excitation_patterns(tst, sr)
    frames = min(es_r.shape[0], es_t.shape[0])
    if frames == 0:
        return Damage(0.0, 0.0, 0.0, 0.0, 0, 0)
    eu_r, es_r = eu_r[:frames], es_r[:frames]
    eu_t, es_t = eu_t[:frames], es_t[:frames]

    ep_r, ep_t, raw_r, _ = _adapt(es_r, es_t)
    mod_r = _modulation(eu_r)
    mod_t = _modulation(eu_t)

    added = _disturbance(ep_r, ep_t, mod_r, mod_t, S0_ADDED, S0_ADDED)
    missing = _disturbance(ep_t, ep_r, mod_t, mod_r, S0_MISSING, S0_MISSING)
    # AvgLinDist: the adapted reference judged against the unadapted one, so
    # what the adaptation absorbed as "a tilt" is counted as its own loudness.
    lin = _disturbance(ep_r, raw_r, mod_r, mod_r, S0_LINDIST, S0_LINDIST)

    # Gate: skip the first half second, then wait for the music to get going
    # (Kabal 5.2.1 and 5.3.1) so a quiet intro cannot dominate the average.
    loud_r = loudness(es_r)
    loud_t = loudness(es_t)
    start = int(math.ceil(DELAY_S * FSS))
    audible = np.where((loud_r > N_THRES_SONE) & (loud_t > N_THRES_SONE))[0]
    if audible.size:
        start = max(start, int(audible[0] + math.ceil(GATE_DELAY_S * FSS)))
    if start >= frames:
        start = 0
    sl = slice(start, frames)
    kept = frames - start

    def _rms(v: np.ndarray) -> float:
        return float(np.sqrt(np.mean(np.square(v[sl])))) if kept else 0.0

    rms_added = _rms(added)
    rms_missing = _rms(missing)
    return Damage(
        lin_dist=float(np.mean(lin[sl])) if kept else 0.0,
        missing=rms_missing,
        added=rms_added,
        asym=rms_added + 0.5 * rms_missing,
        frames=frames,
        gated_frames=kept,
    )
