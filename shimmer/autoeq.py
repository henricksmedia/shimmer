"""
autoeq.py — Tone step: a per-track corrective EQ plan.

Where it sits: the plan is measured at Analyze time and, when applied,
lands in the user EQ stage of the chain (after cleaning and post filters,
before mastering) — the same place a hand-made EQ goes. Analysis only
measures. Nothing here alters the track; the verification run works on a
copy of the loudest excerpt and is thrown away.

How a producer decides, and what this mirrors:
  1. Judge the loud parts. The loudest windows define the track's sound;
     a quiet intro does not.
  2. Judge what the EQ will actually hear. The EQ runs after cleaning, so
     the caller can pass a `cleaner` that runs the cleaning stage on the
     loudest excerpt; the balance is then judged after that change (and
     after the mastering tone curve, when mastering is on) so nothing is
     corrected twice.
  3. Fix first, shape second. Real problems (a ringing tone, a mud stack,
     a harsh band) get narrow subtractive moves. Tonal balance gets at
     most three broad, gentle moves.
  4. Cuts before boosts, and boosts stay small. Every plan is checked on
     the loudest 20 seconds: if peaks rise more than loudness, the limiter
     would work harder, so boosts are halved, then dropped.
  5. Genre is a tolerance, not a target. A family sets how far from
     neutral the balance may sit before a move is worth making. There is
     no reference track and no genre guessing: Neutral is the default and
     the family is the user's call.

Numbers are 1/3-octave band POWER (what a 1/3-octave analyzer shows),
relative to the median of the 200 Hz - 2 kHz bands, on the same scale as
the mastering tone-match reference (mastering._REF_DB).
"""

from __future__ import annotations

from . import _winfix  # noqa: F401  # must precede scipy import on Windows

import math
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
from scipy.ndimage import median_filter
from scipy.signal import find_peaks, welch

from .dsp import as_2d
from .eq import EqBand, EqParams, apply_eq
from .mastering import (
    _REF_DB, _REF_FREQS, measure_loudness, relative_band_levels,
)

# ── Measurement ─────────────────────────────────────────────────────────
WIN_S = 3.0               # analysis window
N_FFT = 8192
MAX_WINDOWS = 96          # long tracks are sampled evenly
LOUD_WINDOW_DB = 6.0      # "loud" = within 6 dB of the 90th-percentile window
MIN_LOUD_WINDOWS = 4
PERSIST = 0.6             # a problem must show in 60 % of the loud windows

# ── Producer guards ─────────────────────────────────────────────────────
MAX_MOVES = 4
MAX_SHAPE_MOVES = 3
SHAPE_MAX_DB = 2.0        # broad balance moves never exceed 2 dB
BOOST_MAX_DB = 1.5
BOOST_MAX_HIGH_DB = 1.0   # 5 - 12 kHz: the band AI fizz lives in
MIN_MOVE_DB = 0.5
NOTCH_MIN_HZ = 120.0      # no notch under 120 Hz: bass notes, not ringing
RES_LO_HZ, RES_HI_HZ = 120.0, 5000.0
RES_PROM_DB = 8.0         # a ringing tone stands 8 dB above its neighbours
RES_PERSIST_DB = 5.0
RES_MAX_WIDTH_OCT = 1.0 / 8.0
RES_MAX_CUT_DB = 4.0
RES_FLOOR_DB = 40.0       # ignore peaks more than 40 dB under the loudest region
RES_MAX_MOVES = 2
MUD_LO_HZ, MUD_HI_HZ = 200.0, 500.0
MUD_EXCESS_DB = 2.0
MUD_MAX_CUT_DB = 2.5
HARSH_LO_HZ, HARSH_HI_HZ = 2000.0, 5000.0
HARSH_EXCESS_DB = 2.5
HARSH_MAX_CUT_DB = 1.5    # a static presence cut stays gentle
VERIFY_S = 20.0
LIMITER_RISK_DB = 1.0     # peaks rising 1 dB more than loudness = limiter works harder

# ── Regions (display and the Shape layer) ───────────────────────────────
REGIONS: List[Tuple[str, str, float, float]] = [
    ("sub", "Sub", 20.0, 60.0),
    ("bass", "Bass", 60.0, 150.0),
    ("lowmid", "Low mids", 150.0, 500.0),
    ("mid", "Mids", 500.0, 2000.0),
    ("presence", "Presence", 2000.0, 6000.0),
    ("air", "Air", 6000.0, 20000.0),
]
_REGION_KEYS = [r[0] for r in REGIONS]
_REGION_LABEL = {r[0]: r[1] for r in REGIONS}

# The broad filter a producer would reach for in each region.
_SHAPE_FILTERS: Dict[str, Tuple[str, float, float]] = {
    "sub": ("bell", 40.0, 0.9),
    "bass": ("low_shelf", 100.0, 0.7),
    "lowmid": ("bell", 300.0, 0.8),
    "mid": ("bell", 1000.0, 0.7),
    "presence": ("bell", 3500.0, 0.9),
    "air": ("high_shelf", 8000.0, 0.7),
}
_LOW_END_SHELF = ("low_shelf", 90.0, 0.7)   # sub + bass moving the same way

# ── Genre families: offset from neutral (dB) and tolerance (± dB) ───────
# Offsets say where a family usually sits against released-music neutral;
# tolerances say how far a track may stray before a move is worth making.
# Wide on purpose: the Shape layer acts only on clear, broad deviations.
FAMILIES: Dict[str, Dict[str, Any]] = {
    "neutral": {
        "label": "Neutral",
        "blurb": "Balanced like most released music. The default.",
        "offset": {"sub": 0, "bass": 0, "lowmid": 0, "mid": 0, "presence": 0, "air": 0},
        "tol": {"sub": 4, "bass": 3, "lowmid": 2.5, "mid": 2, "presence": 2.5, "air": 3},
    },
    "pop": {
        "label": "Pop",
        "blurb": "Clean lows, forward vocal, a little more top.",
        "offset": {"sub": 0, "bass": 1, "lowmid": -0.5, "mid": 0, "presence": 1, "air": 1.5},
        "tol": {"sub": 4, "bass": 3, "lowmid": 2.5, "mid": 2, "presence": 2.5, "air": 3},
    },
    "hiphop": {
        "label": "Hip-hop / Trap",
        "blurb": "Big sub and bass, calmer top end.",
        "offset": {"sub": 4, "bass": 3, "lowmid": 0, "mid": -1, "presence": -0.5, "air": -1},
        "tol": {"sub": 5, "bass": 4, "lowmid": 3, "mid": 2.5, "presence": 3, "air": 3.5},
    },
    "edm": {
        "label": "EDM / Dance",
        "blurb": "Strong sub, scooped low mids, bright top.",
        "offset": {"sub": 3, "bass": 2, "lowmid": -1, "mid": -0.5, "presence": 0.5, "air": 1.5},
        "tol": {"sub": 5, "bass": 3.5, "lowmid": 3, "mid": 2.5, "presence": 3, "air": 3.5},
    },
    "rock": {
        "label": "Rock / Metal",
        "blurb": "Guitars in the mids and presence, less sub.",
        "offset": {"sub": -2, "bass": 0, "lowmid": 0.5, "mid": 1, "presence": 1.5, "air": 0.5},
        "tol": {"sub": 4, "bass": 3, "lowmid": 3, "mid": 2.5, "presence": 3, "air": 3},
    },
    "rnb": {
        "label": "R&B / Soul",
        "blurb": "Warm and full, smooth top.",
        "offset": {"sub": 2, "bass": 2, "lowmid": 0, "mid": 0, "presence": 0, "air": 0.5},
        "tol": {"sub": 4.5, "bass": 3.5, "lowmid": 3, "mid": 2.5, "presence": 3, "air": 3},
    },
    "acoustic": {
        "label": "Acoustic / Folk",
        "blurb": "Natural balance, little sub, open mids.",
        "offset": {"sub": -3, "bass": -1, "lowmid": 0.5, "mid": 0.5, "presence": 0, "air": 0},
        "tol": {"sub": 5, "bass": 3.5, "lowmid": 3, "mid": 2.5, "presence": 3, "air": 3.5},
    },
    "lofi": {
        "label": "Lo-fi / Ambient",
        "blurb": "Soft top end by design. Warm lows.",
        "offset": {"sub": 0, "bass": 1, "lowmid": 1, "mid": 0, "presence": -2, "air": -3},
        "tol": {"sub": 5, "bass": 4, "lowmid": 3.5, "mid": 3, "presence": 4, "air": 5},
    },
    "cinematic": {
        "label": "Cinematic / Orchestral",
        "blurb": "Wide dynamics, natural top, room for swells.",
        "offset": {"sub": 1, "bass": 0, "lowmid": 0.5, "mid": 0, "presence": -1, "air": -1},
        "tol": {"sub": 5, "bass": 4, "lowmid": 3.5, "mid": 3, "presence": 4, "air": 4},
    },
}
FAMILY_ORDER = ["neutral", "pop", "hiphop", "edm", "rock", "rnb",
                "acoustic", "lofi", "cinematic"]
DEFAULT_FAMILY = "neutral"


def family_list() -> List[Dict[str, str]]:
    """Families for a picker, in display order."""
    return [{"key": k, "label": FAMILIES[k]["label"], "blurb": FAMILIES[k]["blurb"]}
            for k in FAMILY_ORDER]


def normalize_family(key: Optional[str]) -> str:
    k = (key or "").strip().lower()
    return k if k in FAMILIES else DEFAULT_FAMILY


# ═══════════════════════════════════════════════════════════════════════
# Measurement
# ═══════════════════════════════════════════════════════════════════════

def _region_of(freq_hz: float) -> str:
    for key, _label, lo, hi in REGIONS:
        if lo <= freq_hz < hi:
            return key
    return "air" if freq_hz >= 6000.0 else "sub"


_BAND_REGION = [_region_of(float(f)) for f in _REF_FREQS]


def _mono(x: np.ndarray) -> np.ndarray:
    x2 = as_2d(np.asarray(x, dtype=np.float32))
    return x2.mean(axis=1).astype(np.float64)


def _window_spans(n: int, sr: int) -> Tuple[List[Tuple[int, int]], bool]:
    """(start, end) sample spans. `contiguous` is False when the track was
    sampled evenly because it is long."""
    win = max(1, int(WIN_S * sr))
    count = n // win
    if count == 0:
        return [(0, n)], True
    if count <= MAX_WINDOWS:
        return [(i * win, (i + 1) * win) for i in range(count)], True
    picks = np.linspace(0, count - 1, MAX_WINDOWS).round().astype(int)
    return [(int(i) * win, (int(i) + 1) * win) for i in picks], False


def _psd_windows(mono: np.ndarray, sr: int,
                 spans: List[Tuple[int, int]]) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Welch power density per window. Returns (freqs, psd[W, F], rms_db[W])."""
    psds = []
    rms = []
    freqs = None
    for a, b in spans:
        seg = mono[a:b]
        nper = min(N_FFT, len(seg))
        if nper < 64:
            continue
        f, p = welch(seg, fs=sr, window="hann", nperseg=nper,
                     noverlap=nper // 2, scaling="density")
        if freqs is None or len(f) == len(freqs):
            freqs = f
            psds.append(p)
            rms.append(10.0 * math.log10(float(np.mean(seg * seg)) + 1e-20))
    if not psds:
        raise ValueError("track too short to analyze")
    return freqs, np.vstack(psds), np.asarray(rms)


def _loud_mask(rms_db: np.ndarray) -> np.ndarray:
    thr = float(np.percentile(rms_db, 90)) - LOUD_WINDOW_DB
    mask = rms_db >= thr
    if int(mask.sum()) < min(MIN_LOUD_WINDOWS, len(rms_db)):
        k = min(MIN_LOUD_WINDOWS, len(rms_db))
        mask = np.zeros_like(mask)
        mask[np.argsort(rms_db)[-k:]] = True
    return mask


def _band_index(freqs: np.ndarray) -> List[np.ndarray]:
    out = []
    for cf in _REF_FREQS:
        lo = cf / (2 ** (1 / 6))
        hi = cf * (2 ** (1 / 6))
        out.append(np.where((freqs >= lo) & (freqs <= hi))[0])
    return out


def _band_power_db(psd: np.ndarray, freqs: np.ndarray,
                   idx: List[np.ndarray]) -> np.ndarray:
    """1/3-octave band power (dB) for each window row of `psd`."""
    df = float(freqs[1] - freqs[0]) if len(freqs) > 1 else 1.0
    out = np.full((psd.shape[0], len(_REF_FREQS)), -120.0)
    for j, ix in enumerate(idx):
        if ix.size:
            out[:, j] = 10.0 * np.log10(psd[:, ix].sum(axis=1) * df + 1e-20)
    return out


def _shape_of(x: np.ndarray, sr: int) -> np.ndarray:
    """Median relative band shape of a short clip (all windows count)."""
    spans, _ = _window_spans(x.shape[0], sr)
    f, p, _r = _psd_windows(_mono(x), sr, spans)
    bp = _band_power_db(p, f, _band_index(f))
    return np.median(np.vstack([relative_band_levels(row) for row in bp]), axis=0)


def _fit_residual(rel: np.ndarray, fit_lo: float, fit_hi: float,
                  test_lo: float, test_hi: float) -> Tuple[np.ndarray, np.ndarray]:
    """Residual of each band in [test_lo, test_hi] against a straight line
    fitted (in log-frequency) through the bands in [fit_lo, fit_hi]."""
    lf = np.log2(_REF_FREQS)
    fit = (_REF_FREQS >= fit_lo) & (_REF_FREQS <= fit_hi)
    test = (_REF_FREQS >= test_lo) & (_REF_FREQS <= test_hi)
    slope, icpt = np.polyfit(lf[fit], rel[fit], 1)
    resid = rel - (slope * lf + icpt)
    return resid[test], np.where(test)[0]


# ── High-resolution prominence grid (ringing tones, tonal checks) ───────
_PPO = 96                 # grid points per octave
_GRID_LO, _GRID_HI = 100.0, 6000.0


class _Prominence:
    """Spectrum minus its own ±1/6-octave median: what stands out."""

    def __init__(self, psd_loud: np.ndarray, freqs: np.ndarray):
        n_pts = int(round(math.log2(_GRID_HI / _GRID_LO) * _PPO)) + 1
        self.grid = _GRID_LO * 2.0 ** (np.arange(n_pts) / _PPO)
        self.n = n_pts
        lf = np.log2(np.maximum(freqs, 1e-6))
        lg = np.log2(self.grid)
        kernel = int(_PPO / 3) + 1
        to_grid = lambda p_db: np.interp(lg, lf, p_db)  # noqa: E731
        self.s_avg = to_grid(10.0 * np.log10(psd_loud.mean(axis=0) + 1e-20))
        self.prom = self.s_avg - median_filter(self.s_avg, size=kernel, mode="nearest")
        rows = []
        for w in range(psd_loud.shape[0]):
            s_w = to_grid(10.0 * np.log10(psd_loud[w] + 1e-20))
            rows.append(s_w - median_filter(s_w, size=kernel, mode="nearest"))
        self.per_win = np.vstack(rows)

    def index_of(self, freq_hz: float) -> int:
        return int(np.clip(round(math.log2(freq_hz / _GRID_LO) * _PPO), 0, self.n - 1))

    def max_in(self, lo_hz: float, hi_hz: float) -> float:
        a = self.index_of(max(lo_hz, _GRID_LO))
        b = self.index_of(min(hi_hz, _GRID_HI))
        return float(self.prom[a:b + 1].max()) if b >= a else 0.0


def _find_resonances(pg: _Prominence,
                     notches: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Narrow, stationary peaks that stand well above their neighbours in
    most loud windows and are not part of a harmonic series."""
    grid, prom, per_win, n_pts = pg.grid, pg.prom, pg.per_win, pg.n
    floor = float(pg.s_avg.max()) - RES_FLOOR_DB
    peaks, _props = find_peaks(prom, height=RES_PROM_DB, distance=_PPO // 12)
    # A played note has partners at simple ratios; a ringing tone does not.
    partner_shifts = [int(round(math.log2(r) * _PPO))
                      for r in (1 / 3, 1 / 2, 2 / 3, 3 / 2, 2.0, 3.0)]
    found = []
    for pk in peaks:
        f = float(grid[pk])
        if f < RES_LO_HZ or f > RES_HI_HZ or pg.s_avg[pk] < floor:
            continue
        p_db = float(prom[pk])
        left = pk
        while left > 0 and prom[left - 1] > p_db - 3.0:
            left -= 1
        right = pk
        while right < n_pts - 1 and prom[right + 1] > p_db - 3.0:
            right += 1
        width_oct = (right - left) / _PPO
        if width_oct > RES_MAX_WIDTH_OCT:
            continue
        a, b = max(0, pk - 2), min(n_pts, pk + 3)
        persist = float(np.mean(per_win[:, a:b].max(axis=1) >= RES_PERSIST_DB))
        if persist < PERSIST:
            continue
        partner = False
        for shift in partner_shifts:
            j = pk + shift
            if 0 <= j < n_pts:
                a2, b2 = max(0, j - 4), min(n_pts, j + 5)
                if prom[a2:b2].max() >= 6.0:
                    partner = True
                    break
        if partner:
            continue
        if notches and any(abs(f - float(n.get("hz", 0))) / f < 0.03 for n in notches):
            continue
        bw_hz = f * (2 ** (width_oct / 2) - 2 ** (-width_oct / 2)) if width_oct > 0 else f / 10.0
        q = float(np.clip(f / max(bw_hz, 1e-6), 4.0, 10.0))
        found.append({
            "freq_hz": round(f, 1),
            "prominence_db": round(p_db, 1),
            "persist": round(persist, 2),
            "q": round(q, 2),
            "gain_db": -round(min(RES_MAX_CUT_DB, 0.5 * p_db), 2),
        })
    found.sort(key=lambda r: -r["prominence_db"])
    return found[:RES_MAX_MOVES]


# ═══════════════════════════════════════════════════════════════════════
# Planning
# ═══════════════════════════════════════════════════════════════════════

def _family_bands(family: str) -> Tuple[np.ndarray, np.ndarray]:
    fam = FAMILIES[family]
    center = np.array([_REF_DB[i] + fam["offset"][_BAND_REGION[i]]
                       for i in range(len(_REF_FREQS))])
    tol = np.array([fam["tol"][_BAND_REGION[i]] for i in range(len(_REF_FREQS))])
    return center, tol


def _usable_bands(cutoff_hz: Optional[float]) -> np.ndarray:
    """Bands that carry real program: below the render's cutoff, and never
    the 20 kHz band (nothing lives there in a 44.1 k render)."""
    ok = _REF_FREQS < 20000.0
    if cutoff_hz and cutoff_hz > 0:
        ok &= _REF_FREQS < 0.9 * float(cutoff_hz)
    return ok


def _region_devs(measured: np.ndarray, center: np.ndarray, tol: np.ndarray,
                 usable: np.ndarray) -> Dict[str, Dict[str, float]]:
    out: Dict[str, Dict[str, float]] = {}
    for key, _label, _lo, _hi in REGIONS:
        in_region = np.array([r == key for r in _BAND_REGION])
        sel = in_region & usable
        if not sel.any():
            out[key] = {"dev": 0.0, "tol": float(tol[in_region].mean()),
                        "outside": 0.0, "measured": False}
            continue
        dev = float(np.mean(measured[sel] - center[sel]))
        t = float(tol[sel].mean())
        out[key] = {"dev": dev, "tol": t, "outside": max(0.0, abs(dev) - t),
                    "measured": True}
    return out


def _fmt_hz(f: float) -> str:
    if f >= 1000:
        s = f"{f / 1000:.1f}".rstrip("0").rstrip(".")
        return f"{s} kHz"
    return f"{f:.0f} Hz"


def _move(kind: str, layer: str, region: str, ftype: str, freq: float,
          gain: float, q: float, reason: str) -> Dict[str, Any]:
    return {
        "kind": kind, "layer": layer, "region": region,
        "type": ftype, "freq_hz": round(float(freq), 1),
        "gain_db": round(float(gain), 2), "q": round(float(q), 3),
        "enabled": True, "reason": reason,
    }


def _bands_from_moves(moves: List[Dict[str, Any]]) -> List[EqBand]:
    return [EqBand(type=m["type"], freq_hz=float(m["freq_hz"]),
                   gain_db=float(m["gain_db"]), q=float(m["q"]),
                   enabled=bool(m.get("enabled", True)))
            for m in moves]


def moves_to_eq_payload(moves: List[Dict[str, Any]], amount: float = 1.0) -> Dict[str, Any]:
    """The plan as an `eq` payload (eq_params_from_json shape)."""
    amt = float(np.clip(amount, 0.0, 1.5))
    bands = [{
        "type": m["type"], "freq_hz": m["freq_hz"],
        "gain_db": round(float(m["gain_db"]) * amt, 2), "q": m["q"],
        "enabled": bool(m.get("enabled", True)),
    } for m in moves]
    return {"enabled": bool(bands), "bands": bands}


def _loudest_excerpt(spans: List[Tuple[int, int]], rms_db: np.ndarray,
                     contiguous: bool, sr: int, n: int) -> Tuple[int, int]:
    k = max(1, int(math.ceil(VERIFY_S / WIN_S)))
    lin = 10.0 ** (rms_db / 10.0)
    if contiguous and len(spans) >= k:
        sums = np.convolve(lin, np.ones(k), mode="valid")
        a = spans[int(np.argmax(sums))][0]
    else:
        a = spans[int(np.argmax(lin))][0]
    b = min(n, a + int(VERIFY_S * sr))
    a = max(0, b - int(VERIFY_S * sr))
    return a, b


def _verify(ex: np.ndarray, sr: int, moves: List[Dict[str, Any]],
            start_s: float) -> Dict[str, Any]:
    """Run the plan on the loudest excerpt and compare loudness and peaks.
    Halves boosts, then drops them, if peaks rise more than loudness:
    that is exactly when the limiter would work harder."""
    before = measure_loudness(ex, sr)
    boosts_scaled = False
    boosts_dropped = False

    def run(ms: List[Dict[str, Any]]) -> Dict[str, float]:
        if not ms:
            return before
        y = apply_eq(ex, sr, EqParams(enabled=True, bands=_bands_from_moves(ms)))
        return measure_loudness(y, sr)

    def plr_shift(bef: Dict[str, float], aft: Dict[str, float]) -> Optional[float]:
        if not (math.isfinite(bef["lufs_i"]) and math.isfinite(aft["lufs_i"])):
            return None
        d_l = aft["lufs_i"] - bef["lufs_i"]
        d_p = aft["true_peak_dbtp"] - bef["true_peak_dbtp"]
        return float(d_p - d_l)

    after = run(moves)
    shift = plr_shift(before, after)
    risky = shift is not None and shift > LIMITER_RISK_DB
    if risky and any(m["gain_db"] > 0 for m in moves):
        for m in moves:
            if m["gain_db"] > 0:
                m["gain_db"] = round(m["gain_db"] * 0.5, 2)
        boosts_scaled = True
        after = run(moves)
        shift = plr_shift(before, after)
        if shift is not None and shift > LIMITER_RISK_DB:
            moves[:] = [m for m in moves if m["gain_db"] < 0]
            boosts_dropped = True
            after = run(moves)
            shift = plr_shift(before, after)

    def plr(d: Dict[str, float]) -> Optional[float]:
        if math.isfinite(d["lufs_i"]) and math.isfinite(d["true_peak_dbtp"]):
            return round(float(d["true_peak_dbtp"] - d["lufs_i"]), 2)
        return None

    def fin(v: float) -> Optional[float]:
        return round(float(v), 2) if math.isfinite(v) else None

    return {
        "excerpt_start_s": round(start_s, 1),
        "excerpt_s": round(ex.shape[0] / sr, 1),
        "lufs_before": fin(before["lufs_i"]), "lufs_after": fin(after["lufs_i"]),
        "tp_before": fin(before["true_peak_dbtp"]), "tp_after": fin(after["true_peak_dbtp"]),
        "plr_before": plr(before), "plr_after": plr(after),
        "plr_shift_db": round(shift, 2) if shift is not None else None,
        "limiter_safe": not (shift is not None and shift > LIMITER_RISK_DB),
        "boosts_scaled": boosts_scaled, "boosts_dropped": boosts_dropped,
    }


def plan_tone(x: np.ndarray, sr: int, family: str = DEFAULT_FAMILY,
              cutoff_hz: Optional[float] = None,
              tone_curve_db: Optional[List[float]] = None,
              notches: Optional[List[Dict[str, Any]]] = None,
              cleaner: Optional[Callable[[np.ndarray], np.ndarray]] = None
              ) -> Dict[str, Any]:
    """Measure the track and return the Tone plan (see module docstring).

    Args:
        x: audio (samples,) or (samples, channels).
        sr: sample rate.
        family: genre family key (FAMILIES); unknown keys fall back to neutral.
        cutoff_hz: the render's bandwidth cutoff, if known. No boost lands
            at or above 0.9 x cutoff, and bands above it are not judged.
        tone_curve_db: the 29-band correction the mastering stage will
            apply (mastering.compute_tone_curve). When given, the balance
            is judged AFTER that curve so the two never double up.
        notches: the static-repair notch list (repair.NotchPlan dicts);
            lines already notched are not planned again.
        cleaner: optional callable that runs the cleaning stage on a clip
            (samples, channels) -> (samples, channels). It is run once on
            the loudest excerpt; the balance is judged after cleaning and
            the plan is verified on the cleaned clip, because that is
            what the EQ stage will actually hear.
    """
    family = normalize_family(family)
    x2 = as_2d(np.asarray(x, dtype=np.float32))
    n = x2.shape[0]
    mono = _mono(x2)
    spans, contiguous = _window_spans(n, sr)
    freqs, psd, rms_db = _psd_windows(mono, sr, spans)
    loud = _loud_mask(rms_db)
    idx = _band_index(freqs)
    bp = _band_power_db(psd, freqs, idx)                 # (W, 29)
    rel_w = np.vstack([relative_band_levels(row) for row in bp])
    rel = np.median(rel_w[loud], axis=0)                 # the track's shape
    pg = _Prominence(psd[loud], freqs)

    # The loudest excerpt: verification, and the cleaning's effect.
    a, b = _loudest_excerpt(spans, rms_db, contiguous, sr, n)
    ex_raw = x2[a:b].astype(np.float32)
    ex = ex_raw
    clean_delta = np.zeros(len(_REF_FREQS))
    cleaning_applied = False
    if cleaner is not None and ex_raw.shape[0] >= sr:
        cleaned = as_2d(np.asarray(cleaner(ex_raw), dtype=np.float32))
        m = min(cleaned.shape[0], ex_raw.shape[0])
        if m >= sr:
            ex = cleaned[:m]
            clean_delta = _shape_of(ex, sr) - _shape_of(ex_raw[:m], sr)
            cleaning_applied = True

    center, tol = _family_bands(family)
    usable = _usable_bands(cutoff_hz)
    # Everything downstream is judged as the EQ will hear it: after the
    # cleaning stage and after the mastering tone curve.
    adjust = clean_delta.copy()
    if tone_curve_db is not None and len(tone_curve_db) == len(_REF_FREQS):
        adjust = adjust + np.asarray(tone_curve_db, dtype=np.float64)
    judged = rel + adjust
    judged_w = rel_w[loud] + adjust
    devs = _region_devs(judged, center, tol, usable)

    moves: List[Dict[str, Any]] = []
    fixed_regions: set = set()

    # ── Fix layer 1: ringing tones ──────────────────────────────────────
    for r in _find_resonances(pg, notches):
        if r["freq_hz"] < NOTCH_MIN_HZ:
            continue
        moves.append(_move(
            "resonance", "fix", _region_of(r["freq_hz"]), "bell",
            r["freq_hz"], r["gain_db"], r["q"],
            f"A ringing tone at {_fmt_hz(r['freq_hz'])} stands "
            f"{r['prominence_db']:.0f} dB above its neighbours in "
            f"{int(round(r['persist'] * 100))}% of the loud parts."))

    # ── Fix layer 2: mud stack (200-500 Hz above the low-end trend) ─────
    res_w = np.vstack([_fit_residual(row, 100.0, 1000.0, MUD_LO_HZ, MUD_HI_HZ)[0]
                       for row in judged_w])
    _, mud_ix = _fit_residual(judged, 100.0, 1000.0, MUD_LO_HZ, MUD_HI_HZ)
    med = np.median(res_w, axis=0)
    j = int(np.argmax(med))
    excess = float(med[j])
    persist = float(np.mean(res_w[:, j] >= MUD_EXCESS_DB - 0.5))
    f_mud = float(_REF_FREQS[mud_ix[j]])
    # A single played note lifts its band too; mud is broad, not a tone.
    tonal = pg.max_in(f_mud / 2 ** (1 / 6), f_mud * 2 ** (1 / 6)) >= RES_PROM_DB
    if (excess >= MUD_EXCESS_DB and persist >= PERSIST and not tonal
            and devs["lowmid"]["dev"] > -devs["lowmid"]["tol"]):
        moves.append(_move(
            "mud", "fix", "lowmid", "bell", f_mud,
            -min(MUD_MAX_CUT_DB, 0.6 * excess), 1.4,
            f"Energy stacks up around {_fmt_hz(f_mud)}, {excess:.1f} dB over the "
            "low-end trend in most loud parts. This is the mud zone."))
        fixed_regions.add("lowmid")

    # ── Fix layer 3: harsh band (2-5 kHz above the top-end trend) ───────
    res_w = np.vstack([_fit_residual(row, 1000.0, 8000.0, HARSH_LO_HZ, HARSH_HI_HZ)[0]
                       for row in judged_w])
    _, h_ix = _fit_residual(judged, 1000.0, 8000.0, HARSH_LO_HZ, HARSH_HI_HZ)
    med = np.median(res_w, axis=0)
    j = int(np.argmax(med))
    excess = float(med[j])
    persist = float(np.mean(res_w[:, j] >= HARSH_EXCESS_DB - 0.5))
    f_h = float(_REF_FREQS[h_ix[j]])
    tonal = pg.max_in(f_h / 2 ** (1 / 6), f_h * 2 ** (1 / 6)) >= RES_PROM_DB
    if (excess >= HARSH_EXCESS_DB and persist >= PERSIST and not tonal
            and devs["presence"]["dev"] > -devs["presence"]["tol"]):
        moves.append(_move(
            "harsh", "fix", "presence", "bell", f_h,
            -min(HARSH_MAX_CUT_DB, 0.5 * excess), 1.2,
            f"The {_fmt_hz(f_h)} area sits {excess:.1f} dB over the top-end "
            "trend and stays there. That reads as harsh."))
        fixed_regions.add("presence")

    # ── Shape layer: at most three broad, gentle balance moves ─────────
    fam_label = FAMILIES[family]["label"]
    cands: Dict[str, Dict[str, Any]] = {}
    for key, _label, _lo, _hi in REGIONS:
        d = devs[key]
        if not d["measured"] or d["outside"] <= 0 or key in fixed_regions:
            continue
        gain = -math.copysign(min(SHAPE_MAX_DB, 0.75 * d["outside"]), d["dev"])
        if gain > 0:
            cap = BOOST_MAX_HIGH_DB if key in ("presence", "air") else BOOST_MAX_DB
            if key == "air" and cutoff_hz and 0 < float(cutoff_hz) <= 11000.0:
                continue                         # nothing real to lift up there
            gain = min(gain, cap)
        if abs(gain) < MIN_MOVE_DB:
            continue
        cands[key] = {"gain": gain, "dev": d}

    def shape_move(key: str, gain: float, d: Dict[str, Any], ftype: str,
                   f: float, q: float, label: str) -> Dict[str, Any]:
        where = "above" if d["dev"] > 0 else "under"
        verb = "Small trim." if gain < 0 else "Small lift."
        return _move("balance", "shape", key, ftype, f, gain, q,
                     f"{label} sits {abs(d['dev']):.1f} dB {where} the {fam_label} "
                     f"range (±{d['tol']:.0f} dB). {verb}")

    shape_moves: List[Dict[str, Any]] = []
    # Sub and bass moving the same way is one low-end decision: one shelf,
    # not two filters stacking under 60 Hz.
    if "sub" in cands and "bass" in cands and \
            math.copysign(1, cands["sub"]["gain"]) == math.copysign(1, cands["bass"]["gain"]):
        pick = max(("sub", "bass"), key=lambda k: abs(cands[k]["gain"]))
        ftype, f, q = _LOW_END_SHELF
        mv = shape_move("bass", cands[pick]["gain"], cands[pick]["dev"], ftype, f, q,
                        "The low end (sub and bass)")
        mv["outside"] = max(cands["sub"]["dev"]["outside"], cands["bass"]["dev"]["outside"])
        shape_moves.append(mv)
        cands.pop("sub")
        cands.pop("bass")
    for key, c in cands.items():
        ftype, f, q = _SHAPE_FILTERS[key]
        mv = shape_move(key, c["gain"], c["dev"], ftype, f, q, _REGION_LABEL[key])
        mv["outside"] = c["dev"]["outside"]
        shape_moves.append(mv)
    shape_moves.sort(key=lambda m: (m["gain_db"] > 0, -m.pop("outside")))
    moves.extend(shape_moves[:MAX_SHAPE_MOVES])

    # Cuts before boosts, then the move budget.
    moves.sort(key=lambda m: (m["gain_db"] > 0, m["layer"] != "fix"))
    moves = moves[:MAX_MOVES]

    # ── Verify on the loudest excerpt (cleaned, if a cleaner was given) ─
    verify = _verify(ex, sr, moves, a / sr)

    after_dev: Dict[str, Optional[float]] = {k: None for k in _REGION_KEYS}
    if moves:
        y = apply_eq(ex, sr, EqParams(enabled=True, bands=_bands_from_moves(moves)))
        shift = _shape_of(y, sr) - _shape_of(ex, sr)     # what the plan changed
        d_after = _region_devs(judged + shift, center, tol, usable)
        after_dev = {k: round(d_after[k]["dev"], 2) for k in _REGION_KEYS}

    regions = []
    for key, label, lo, hi in REGIONS:
        d = devs[key]
        status = "inside"
        if d["measured"] and d["outside"] > 0:
            status = "over" if d["dev"] > 0 else "under"
        regions.append({
            "key": key, "label": label, "lo_hz": lo, "hi_hz": hi,
            "dev_db": round(d["dev"], 2), "tol_db": round(d["tol"], 2),
            "status": status if d["measured"] else "n/a",
            "dev_after_db": after_dev[key],
        })

    for i, m in enumerate(moves):
        m["id"] = f"t{i + 1}"

    return {
        "version": 1,
        "family": family,
        "family_label": fam_label,
        "moves": moves,
        "regions": regions,
        "shape": {
            "freqs_hz": [float(f) for f in _REF_FREQS],
            "measured_db": [round(float(v), 2) for v in rel],
            "judged_db": [round(float(v), 2) for v in judged],
            "center_db": [round(float(v), 2) for v in center],
            "tol_db": [round(float(v), 2) for v in tol],
            "usable": [bool(u) for u in usable],
        },
        "verify": verify,
        "verdict": _verdict(moves),
        "why": _why(moves, fam_label, verify),
        "summary": _verdict(moves) + " " + _why(moves, fam_label, verify),
        "eq": moves_to_eq_payload(moves),
        "analysis": {
            "windows": int(len(rms_db)), "loud_windows": int(loud.sum()),
            "cutoff_hz": float(cutoff_hz) if cutoff_hz else None,
            "tone_curve_applied": tone_curve_db is not None,
            "cleaning_applied": cleaning_applied,
        },
    }


def _verdict(moves: List[Dict[str, Any]]) -> str:
    """The headline: what the plan is, in four words."""
    if not moves:
        return "No EQ needed."
    n = len(moves)
    return f"{n} move{'s' if n > 1 else ''} suggested."


def _why(moves: List[Dict[str, Any]], fam_label: str, verify: Dict[str, Any]) -> str:
    """The reason under the headline: what was found and what the check
    said. Never repeats the headline."""
    if not moves:
        return f"Every region sits inside the {fam_label} range."
    kinds: Dict[str, int] = {}
    for m in moves:
        kinds[m["kind"]] = kinds.get(m["kind"], 0) + 1
    parts = []
    if kinds.get("resonance"):
        k = kinds["resonance"]
        parts.append(f"{k} ringing tone{'s' if k > 1 else ''} tamed")
    if kinds.get("mud"):
        parts.append("mud trimmed")
    if kinds.get("harsh"):
        parts.append("harshness eased")
    if kinds.get("balance"):
        k = kinds["balance"]
        parts.append(f"{k} balance move{'s' if k > 1 else ''} toward {fam_label}")
    head = ", ".join(parts)
    head = head[0].upper() + head[1:] + "."
    check = ""
    if verify.get("lufs_before") is not None and verify.get("lufs_after") is not None:
        dl = verify["lufs_after"] - verify["lufs_before"]
        dp = (verify["tp_after"] or 0) - (verify["tp_before"] or 0)
        shift = verify.get("plr_shift_db")
        if verify.get("limiter_safe"):
            tail = "limiter safe"
        else:
            tail = f"the limiter works about {shift:.1f} dB harder" if shift else "the limiter works harder"
        check = (f" Checked on the loudest {verify['excerpt_s']:.0f} s: loudness "
                 f"{dl:+.1f} dB, peaks {dp:+.1f} dB, {tail}.")
        if verify.get("boosts_dropped"):
            check += " Boosts were dropped to keep peaks in check."
        elif verify.get("boosts_scaled"):
            check += " Boosts were halved to keep peaks in check."
    return head + check
