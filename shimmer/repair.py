"""
repair.py — Deterministic repairs that run first in the chain.

Two stages, both placed after Trim and before the tone curve and the
crossover (docs/PLAN.md Section 2, placements approved 2026-09-04):

  1. De-click / de-crackle (`declick`).  Impulsive noise is the first
     step in every restoration order, because every adaptive detector
     downstream reads a click as a transient and backs off.  Detection
     runs on the high band (>= dc_min_hz) so bass hits cannot trigger
     it: a per-second linear-prediction model whitens the band, samples
     whose residual exceeds a robust threshold are flagged, short runs
     are re-synthesised from the model forwards and backwards and
     cross-faded.  Only the flagged samples of the high-band component
     change; the low band is untouched.

  2. Static repair (`apply_static_repair`).  The generator's fixed
     tonal lines and comb teeth are stationary for the whole file
     (architecture artifacts, see docs/PRESET_REVIEW.md).  They are
     found once by the whole-file scan in detect.py, turned into a
     NotchPlan by `plan_from_lines` under strict eligibility rules, and
     removed with narrow zero-phase notches applied to L and R at full
     depth: a fixed 17.7 kHz line is not music and does not deserve the
     Mid-channel protection the engine gives vocals.

`estimate_cutoff_hz` measures where a render's top end stops (many
Suno exports end at 12–15 kHz) so shelves and the tone curve never
boost the empty band above it.

Nothing here is adaptive per frame; that is the point.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from scipy.signal import lfilter, sosfiltfilt, welch

from .dsp import apply_highpass, as_2d

_EPS = 1e-12

# Static-repair eligibility (see docs/PLAN.md A1).
MAX_NOTCH_DEPTH_DB = 30.0
MIN_LINE_EXCESS_DB = 6.0        # 25th-percentile excess over the whole file
LOW_LINE_HZ = 3000.0            # below this, stricter:
LOW_LINE_MIN_EXCESS_DB = 10.0
LOW_LINE_MIN_DUTY = 0.9
MIN_NOTCH_HZ = 2000.0
MAX_NOTCHES = 24
NOTCH_BW_BINS = 4.0             # width in analysis bins (sr / 4096): ~43 Hz at 44.1 kHz

# De-click.
DECLICK_K_MAX = 9.0             # residual threshold in robust sigmas at amount 0
DECLICK_K_MIN = 4.0             # at amount 1
CRACKLE_RUNS_PER_S = 40.0       # above this, a region is crackle: threshold drops
CRACKLE_K_DROP = 2.0


# ---------------------------------------------------------------------------
# Static repair
# ---------------------------------------------------------------------------

@dataclass
class Notch:
    hz: float
    depth_db: float
    bw_hz: float = 24.0
    kind: str = "line"          # "line" | "comb"
    excess_db: float = 0.0
    duty: float = 0.0


@dataclass
class NotchPlan:
    enabled: bool = True
    notches: List[Notch] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {"enabled": bool(self.enabled),
                "notches": [asdict(n) for n in self.notches]}

    @classmethod
    def from_dict(cls, d: Optional[Dict[str, Any]], sr: int = 48000) -> "NotchPlan":
        """Build a plan from a client payload, validating every number so a
        bad request can never turn into a wild filter."""
        d = d or {}
        out = cls(enabled=bool(d.get("enabled", True)))
        nyq = 0.5 * float(sr)
        for raw in d.get("notches") or []:
            try:
                hz = float(raw.get("hz"))
                depth = float(raw.get("depth_db", 0.0))
                bw = float(raw.get("bw_hz", 24.0))
            except (TypeError, ValueError, AttributeError):
                continue
            if not (MIN_NOTCH_HZ <= hz < 0.98 * nyq):
                continue
            depth = float(np.clip(depth, 0.0, MAX_NOTCH_DEPTH_DB))
            bw = float(np.clip(bw, 6.0, 200.0))
            if depth < 0.5:
                continue
            out.notches.append(Notch(
                hz=hz, depth_db=depth, bw_hz=bw,
                kind=str(raw.get("kind", "line")),
                excess_db=float(raw.get("excess_db", depth) or depth),
                duty=float(raw.get("duty", 0.0) or 0.0)))
            if len(out.notches) >= MAX_NOTCHES:
                break
        return out


def plan_from_lines(lines: Sequence[Dict[str, Any]], sr: int,
                    enabled: bool = True) -> NotchPlan:
    """Turn scanned fixed lines into a notch plan.

    Eligibility: the line's 25th-percentile excess over the whole file
    must be >= 6 dB (present at least three quarters of the time, which
    rules out musical partials); below 3 kHz it must also be >= 10 dB
    and present >= 90 % of the time. Depth follows the loud parts of the
    song (`excess_hi_db`, the 90th percentile) so the notch removes the
    line where it is strongest, capped at 30 dB. Width is four analysis
    bins; a fixed line is not music, so a slightly wider notch costs
    nothing and forgives the scan's frequency error.
    """
    plan = NotchPlan(enabled=enabled)
    bw = max(20.0, NOTCH_BW_BINS * float(sr) / 4096.0)
    nyq = 0.5 * float(sr)
    ordered = sorted(lines, key=lambda L: -float(L.get("excess_db", 0.0)))
    for L in ordered:
        hz = float(L.get("hz", 0.0))
        ex = float(L.get("excess_db", 0.0))
        duty = float(L.get("duty", 0.0))
        if hz < MIN_NOTCH_HZ or hz >= 0.98 * nyq:
            continue
        if ex < MIN_LINE_EXCESS_DB:
            continue
        if hz < LOW_LINE_HZ and (ex < LOW_LINE_MIN_EXCESS_DB or duty < LOW_LINE_MIN_DUTY):
            continue
        if any(abs(hz - n.hz) < bw for n in plan.notches):
            continue
        ex_hi = float(L.get("excess_hi_db", ex) or ex)
        depth = float(min(MAX_NOTCH_DEPTH_DB, max(0.0, ex - 1.0, ex_hi)))
        if depth < 0.5:
            continue
        plan.notches.append(Notch(hz=hz, depth_db=depth, bw_hz=bw,
                                  kind=str(L.get("kind", "line")),
                                  excess_db=ex, duty=duty))
        if len(plan.notches) >= MAX_NOTCHES:
            break
    return plan


def _peaking_sos(sr: int, hz: float, gain_db: float, q: float) -> np.ndarray:
    """RBJ peaking section (one pass). Applied forward and backward by
    sosfiltfilt, so callers pass half the wanted dB."""
    A = 10.0 ** (gain_db / 40.0)
    w0 = 2.0 * np.pi * hz / sr
    alpha = np.sin(w0) / (2.0 * max(0.5, q))
    b0, b1, b2 = 1 + alpha * A, -2 * np.cos(w0), 1 - alpha * A
    a0, a1, a2 = 1 + alpha / A, -2 * np.cos(w0), 1 - alpha / A
    return np.array([b0 / a0, b1 / a0, b2 / a0, 1.0, a1 / a0, a2 / a0], dtype=np.float64)


def apply_static_repair(x: np.ndarray, sr: int, plan: Optional[NotchPlan]
                        ) -> Tuple[np.ndarray, Dict[str, Any]]:
    """Apply the plan's notches, zero-phase, to every channel at full depth."""
    x2 = as_2d(np.asarray(x, dtype=np.float32))
    if plan is None or not plan.enabled or not plan.notches:
        return x2, {"enabled": False, "notches": 0}
    nyq = 0.5 * float(sr)
    rows = []
    applied = []
    for n in plan.notches:
        if not (0.0 < n.hz < 0.98 * nyq) or n.depth_db <= 0.0:
            continue
        q = n.hz / max(1.0, n.bw_hz)
        rows.append(_peaking_sos(sr, n.hz, -0.5 * n.depth_db, q))
        applied.append(n)
    if not rows:
        return x2, {"enabled": False, "notches": 0}
    sos = np.vstack(rows)
    # High-Q sections ring for ~1/(pi*bw) s; pad well past that.
    padlen = int(min(x2.shape[0] - 1, max(0, 0.25 * sr)))
    y = sosfiltfilt(sos, x2.astype(np.float64), axis=0, padlen=padlen)
    report = {
        "enabled": True,
        "notches": len(applied),
        "lines": [{"hz": round(n.hz, 1), "depth_db": round(n.depth_db, 1),
                   "kind": n.kind} for n in applied],
        "deepest_db": round(max(n.depth_db for n in applied), 1),
    }
    return y.astype(np.float32), report


# ---------------------------------------------------------------------------
# De-click / de-crackle
# ---------------------------------------------------------------------------

def _lpc(frame: np.ndarray, order: int) -> Optional[np.ndarray]:
    """Autocorrelation-method linear predictor via Levinson-Durbin.
    Returns A(z) coefficients [1, a1, ..., a_order] or None if degenerate."""
    frame = np.asarray(frame, dtype=np.float64)
    n = frame.shape[0]
    if n <= order + 1:
        return None
    # Only lags 0..order are needed: O(n * order), not a full correlation.
    r = np.array([float(np.dot(frame[:n - k], frame[k:])) if k else float(np.dot(frame, frame))
                  for k in range(order + 1)], dtype=np.float64)
    if r[0] <= _EPS:
        return None
    a = np.zeros(order + 1, dtype=np.float64)
    a[0] = 1.0
    err = float(r[0])
    for i in range(1, order + 1):
        acc = float(r[i] + np.dot(a[1:i], r[i - 1:0:-1]))
        k = -acc / err
        a_new = a.copy()
        a_new[1:i] = a[1:i] + k * a[i - 1:0:-1]
        a_new[i] = k
        a = a_new
        err *= (1.0 - k * k)
        if err <= _EPS:
            break
    return a


def _runs(mask: np.ndarray) -> List[Tuple[int, int]]:
    if not np.any(mask):
        return []
    d = np.diff(mask.astype(np.int8), prepend=0, append=0)
    starts = np.where(d == 1)[0]
    ends = np.where(d == -1)[0]
    return list(zip(starts.tolist(), ends.tolist()))


def _detect_clicks(h: np.ndarray, sr: int, order: int, k: float,
                   max_run: int, pad: int
                   ) -> Tuple[List[Tuple[int, int]], List[Tuple[int, int, np.ndarray]]]:
    """Flag impulsive samples in a high-band channel.

    Returns (runs, models): runs are [start, end) sample ranges to
    repair; models are (block_start, block_end, A(z)) per second of
    audio, reused for the repair."""
    n = h.shape[0]
    block = int(sr)
    flags = np.zeros(n, dtype=bool)
    models: List[Tuple[int, int, np.ndarray]] = []
    scales = np.zeros(n, dtype=np.float64)
    for s0 in range(0, n, block):
        s1 = min(n, s0 + block)
        lead = max(0, s0 - order)
        seg = h[lead:s1]
        a = _lpc(seg, order)
        if a is None:
            continue
        e = lfilter(a, [1.0], seg)[s0 - lead:]
        med = float(np.median(e))
        scale = 1.4826 * float(np.median(np.abs(e - med))) + 1e-9
        flags[s0:s1] = np.abs(e - med) > (k * scale)
        scales[s0:s1] = scale
        models.append((s0, s1, a))
    if not models:
        return [], []

    runs = _accept_runs(h, flags, sr, n, max_run, pad)

    # Crackle: regions dense with small isolated clicks get a lower
    # threshold on a second look, so a fizz of micro-clicks is treated as
    # one problem. Density is counted from *accepted* runs, so drum hits
    # (rejected below as not isolated) can never trigger it.
    win = max(1, int(0.25 * sr))
    if runs and k > DECLICK_K_MIN:
        density = np.zeros(n // win + 1, dtype=np.float64)
        for a0, _ in runs:
            density[a0 // win] += 1.0
        density /= (win / float(sr))
        hot = density > CRACKLE_RUNS_PER_S
        if np.any(hot):
            k2 = max(DECLICK_K_MIN, k - CRACKLE_K_DROP)
            flags2 = flags.copy()
            for (s0, s1, a) in models:
                blk_hot = hot[s0 // win:(s1 - 1) // win + 1]
                if not np.any(blk_hot):
                    continue
                seg = h[max(0, s0 - order):s1]
                e = lfilter(a, [1.0], seg)[s0 - max(0, s0 - order):]
                med = float(np.median(e))
                thr = k2 * scales[s0:s1]
                hot_mask = np.repeat(blk_hot, win)[: (s1 - s0)]
                if hot_mask.shape[0] < (s1 - s0):
                    hot_mask = np.pad(hot_mask, (0, (s1 - s0) - hot_mask.shape[0]))
                flags2[s0:s1] |= (np.abs(e - med) > thr) & hot_mask
            runs = _accept_runs(h, flags2, sr, n, max_run, pad)
    return runs, models


def _accept_runs(h: np.ndarray, flags: np.ndarray, sr: int, n: int,
                 max_run: int, pad: int) -> List[Tuple[int, int]]:
    """Merge flagged samples into padded runs and keep only the ones that
    look like clicks: short, and *isolated*. A click stands out from the
    signal on both sides and the level afterwards matches the level
    before. A drum hit or a consonant onset also spikes the residual,
    but what follows it is far louder than what preceded it, so it is
    rejected here and left to the transient hold downstream."""
    runs: List[Tuple[int, int]] = []
    for a0, b0 in _runs(flags):
        a1, b1 = max(0, a0 - pad), min(n, b0 + pad)
        if runs and a1 <= runs[-1][1]:
            runs[-1] = (runs[-1][0], max(runs[-1][1], b1))
        else:
            runs.append((a1, b1))
    W = max(16, int(0.003 * sr))
    kept: List[Tuple[int, int]] = []
    for a0, b0 in runs:
        if (b0 - a0) > max_run:
            continue
        pre = h[max(0, a0 - W):a0]
        post = h[b0:min(n, b0 + W)]
        if pre.size < 4 or post.size < 4:
            continue
        pre_e = float(np.mean(pre * pre)) + 1e-18
        post_e = float(np.mean(post * post)) + 1e-18
        peak_e = float(np.max(h[a0:b0] ** 2))
        # Not isolated: level jumps across the run (an onset, not a click).
        if post_e > 4.0 * pre_e:
            continue
        # Not impulsive: the run does not stand out from its surroundings.
        if peak_e < 10.0 * max(pre_e, post_e):
            continue
        kept.append((a0, b0))
    return kept


def _model_for(models: List[Tuple[int, int, np.ndarray]], pos: int) -> Optional[np.ndarray]:
    for s0, s1, a in models:
        if s0 <= pos < s1:
            return a
    return models[-1][2] if models else None


def _ar_fill(h: np.ndarray, a: np.ndarray, s: int, e: int) -> np.ndarray:
    """Re-synthesise h[s:e] from the AR model: predict forward from the
    samples before the gap and backward from the samples after, then
    cross-fade. Falls back to a straight line at the file edges."""
    L = e - s
    order = a.shape[0] - 1
    coefs = -a[1:][::-1]           # x[n] = sum coefs[j] * x[n-order+j]
    if s < order or e + order > h.shape[0] or L <= 0:
        left = h[s - 1] if s > 0 else 0.0
        right = h[e] if e < h.shape[0] else 0.0
        return np.linspace(left, right, L + 2)[1:-1]
    fwd = np.empty(L)
    hist = h[s - order:s].astype(np.float64).copy()
    for i in range(L):
        v = float(np.dot(coefs, hist))
        fwd[i] = v
        hist = np.roll(hist, -1)
        hist[-1] = v
    bwd = np.empty(L)
    hist = h[e:e + order][::-1].astype(np.float64).copy()
    for i in range(L):
        v = float(np.dot(coefs, hist))
        bwd[i] = v
        hist = np.roll(hist, -1)
        hist[-1] = v
    w = np.linspace(0.0, 1.0, L) if L > 1 else np.array([0.5])
    return (1.0 - w) * fwd + w * bwd[::-1]


def declick(x: np.ndarray, sr: int, amount: float,
            min_hz: float = 2000.0, order: int = 32,
            max_ms: float = 2.0, pad: int = 8
            ) -> Tuple[np.ndarray, Dict[str, Any]]:
    """Remove clicks and crackle from the high band. `amount` 0..1 sets
    the detection threshold (0 = off, 1 = most sensitive)."""
    x2 = as_2d(np.asarray(x, dtype=np.float32))
    amount = float(np.clip(amount, 0.0, 1.0))
    if amount <= 1e-6 or x2.shape[0] < sr // 2:
        return x2, {"enabled": False}
    k = DECLICK_K_MAX - (DECLICK_K_MAX - DECLICK_K_MIN) * amount
    max_run = max(4, int(max_ms * 1e-3 * sr))
    h = apply_highpass(x2, sr, float(min_hz), order=4).astype(np.float64)
    y = x2.astype(np.float64).copy()
    total_runs = 0
    total_samples = 0
    longest = 0
    for ch in range(x2.shape[1]):
        hc = h[:, ch]
        runs, models = _detect_clicks(hc, sr, int(order), k, max_run, int(pad))
        if not runs:
            continue
        hr = hc.copy()
        for (s, e) in runs:
            a = _model_for(models, s)
            if a is None:
                continue
            hr[s:e] = _ar_fill(hc, a, s, e)
            total_samples += (e - s)
            longest = max(longest, e - s)
        total_runs += len(runs)
        y[:, ch] += (hr - hc)
    dur = x2.shape[0] / float(sr)
    return y.astype(np.float32), {
        "enabled": True,
        "amount": amount,
        "threshold_sigma": round(k, 2),
        "clicks": int(total_runs),
        "clicks_per_s": round(total_runs / max(dur, 1e-9), 3),
        "samples_repaired": int(total_samples),
        "longest_ms": round(1000.0 * longest / float(sr), 2),
    }


def click_rate(x: np.ndarray, sr: int, min_hz: float = 2000.0,
               order: int = 32, k: float = 7.0, max_ms: float = 2.0) -> float:
    """Detection only (for Analyze): short isolated blips per second in
    the high band at a fixed threshold. Dense hi-hat patterns register
    here too, so Analyze only calls it crackle above a high rate."""
    x2 = as_2d(np.asarray(x, dtype=np.float32))
    if x2.shape[0] < sr // 2:
        return 0.0
    mono = x2.mean(axis=1)
    h = apply_highpass(mono[:, None], sr, float(min_hz), order=4)[:, 0].astype(np.float64)
    runs, _ = _detect_clicks(h, sr, int(order), float(k), max(4, int(max_ms * 1e-3 * sr)), 8)
    return float(len(runs) / (x2.shape[0] / float(sr)))


# ---------------------------------------------------------------------------
# Bandwidth cutoff
# ---------------------------------------------------------------------------

def estimate_cutoff_hz(x: np.ndarray, sr: int, max_s: float = 120.0) -> Dict[str, Any]:
    """Find where the render's top end stops.

    Long-term Welch spectrum on the mono mix; a trend line is fitted on
    4–10 kHz (dB against log-frequency); the cutoff is the lowest
    frequency above 8 kHz where the spectrum sits >= 30 dB under the
    trend and stays there for the rest of the band, with real content
    (within 12 dB of trend) in the octave just below. Returns
    {"cutoff_hz": float or None, "above_db": mean excess above cutoff}.
    """
    x2 = as_2d(np.asarray(x, dtype=np.float32))
    n = min(x2.shape[0], int(max_s * sr))
    if n < 8192:
        return {"cutoff_hz": None, "above_db": None}
    mono = x2[:n].mean(axis=1).astype(np.float64)
    f, P = welch(mono, fs=sr, nperseg=4096, noverlap=2048)
    L = 10.0 * np.log10(P + _EPS)
    fit = (f >= 4000.0) & (f <= 10000.0)
    if fit.sum() < 8:
        return {"cutoff_hz": None, "above_db": None}
    lf = np.log2(np.maximum(f, 1.0))
    slope, icpt = np.polyfit(lf[fit], L[fit], 1)
    trend = slope * lf + icpt
    excess = L - trend
    nyq = 0.5 * sr
    # A roll-off in the last tenth of the band is the normal anti-alias
    # slope of the export, not a cutoff worth acting on.
    cand = np.where((f >= 8000.0) & (f <= 0.9 * nyq))[0]
    for i in cand:
        if excess[i] >= -30.0:
            continue
        rest = excess[i:][f[i:] <= 0.95 * nyq]
        if rest.size and np.mean(rest < -20.0) >= 0.9:
            below = (f >= f[i] * 0.5) & (f < f[i])
            if below.sum() and float(np.mean(excess[below])) > -12.0:
                return {"cutoff_hz": float(f[i]), "above_db": float(np.mean(rest))}
    return {"cutoff_hz": None, "above_db": None}
