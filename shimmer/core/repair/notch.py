"""Static repair: narrow notches for the generator's fixed tones (the Fixed
tones card).

Ported unchanged from shimmer/repair.py (1.1.1): Notch, NotchPlan,
plan_from_lines and apply_static_repair (docs/ARCHITECTURE.md §19.1 item
1). This is the one cleaning tool that measured clearly: it removes 96 % of
a fixed tone.

The generator's fixed tonal lines and comb teeth are stationary for the
whole file. They are found once by the whole-file scan
(shimmer.core.analyze.tones), turned into a plan under strict eligibility
rules, and removed with narrow zero-phase notches applied to L and R at
full depth.

plan(source) and apply(x, sr, notches) are the engine's entry points
(tests/core/test_core_analyze_repair.py).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from scipy.signal import sosfiltfilt


def as_2d(x: np.ndarray) -> np.ndarray:
    return x[:, None] if x.ndim == 1 else x


# Static-repair eligibility (see docs/PLAN.md A1).
MAX_NOTCH_DEPTH_DB = 30.0
MIN_LINE_EXCESS_DB = 6.0        # 25th-percentile excess over the whole file
LOW_LINE_HZ = 3000.0            # below this, stricter:
LOW_LINE_MIN_EXCESS_DB = 10.0
LOW_LINE_MIN_DUTY = 0.9
MIN_NOTCH_HZ = 2000.0
MAX_NOTCHES = 24
NOTCH_BW_BINS = 4.0             # width in analysis bins (sr / 4096): ~43 Hz at 44.1 kHz


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


# ── Engine entry points ─────────────────────────────────────────────────

def plan(source) -> List[Notch]:
    """The notches for this song, from the whole-file scan."""
    from ..analyze.tones import scan_fixed_lines
    return plan_from_lines(scan_fixed_lines(source.audio, source.sr), source.sr).notches


def apply(x: np.ndarray, sr: int, notches: Sequence[Notch]) -> np.ndarray:
    """Remove the given notches' tones from x."""
    y, _ = apply_static_repair(x, sr, NotchPlan(enabled=True, notches=list(notches)))
    return y
