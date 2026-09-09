"""
budget.py — Remove as much as there is artifact, then stop.

The failure this fixes (docs/BRIGHTNESS-ASSESSMENT.md): every cleaning preset
removes a fixed amount set by its own strength, with no reference to how much
artifact the track actually contains. On a commercial reference master carrying *no*
measurable hash, Deep Scrub still stripped 6.5 dB out of 16 kHz. There was
nothing there to take, so all of it was air that belonged to the music. Across
a chain of two cleaning passes plus a tone curve plus an auto EQ — none of
which sums the total — that is how a master ends up 11 dB out of tilt while no
single stage looks unreasonable.

The principle here came out of a listening test. Asked whether the removed
material was music, the listener correctly said no: air played on its own
sounds like *shhh*, never like music, so a residual can always be made to look
innocent. The right question is not "does this sound like music" but **"was
there artifact there to remove?"** — and that is measurable.

So:

  1. `estimate_budget` measures how much artifact the track carries, and turns
     it into a ceiling expressed in sones of audible damage.
  2. `apply_within_budget` runs whatever cleaning was asked for, measures what
     it actually cost with the BS.1387 model (perceptual.py), and if that
     exceeds the ceiling, mixes back toward the original until it fits.

The mix-back is the honest lever: a partly-cleaned track is exactly the
original minus a fraction of what the preset wanted to remove, so nothing is
invented and nothing is re-synthesised. It also means this works with any
preset, including badly-behaved ones, without retuning them one at a time —
a preset that over-reaches simply gets pulled back to the budget.

On a clean track the budget falls to near zero and the cleaning becomes a
near-no-op, which is the behaviour a repair tool should have when there is
nothing to repair.
"""

from __future__ import annotations

from . import _winfix  # noqa: F401

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import numpy as np

from .dsp import as_2d
from .perceptual import measure_damage

# ── Budget calibration ─────────────────────────────────────────────────
#
# The artifact signal is the Suno hash: amplitude modulation at 10-50 Hz in
# 4.5-12 kHz that real instruments do not produce. `flicker_excess_db`
# (detect.py) measures it as the modulation depth of that band over the
# modulation depth of the mids, so the units are dB of *excess* flicker and
# the zero point is meaningful: a track whose brilliance band flickers no more
# than its mids has no hash to remove. Measured on the references, a finished
# master with no hash reads -0.2 dB and one that still carries it reads +0.9.
#
# EXCESS_FLOOR_DB is where a budget starts to open up at all. It sits just
# above zero rather than at it, because the measure is noisy at small values
# and the cost of over-removal is higher than the cost of leaving faint hash
# in place — the reference masters leave the hash in entirely and were
# still preferred in listening.
EXCESS_FLOOR_DB = 0.5

# Once a hash signature is present at all, this much removal is allowed.
#
# The obvious model - allowance proportional to measured excess - is NOT
# supported by the data. Fitting it on the four reference sources gives a
# constant of 0.093, 0.082 and 0.015 sones/dB: a six-fold spread, because what
# a well-aimed preset costs turns out to be roughly flat (Suno Hash costs
# 0.036-0.060 sones whether the excess is 0.9 dB or 3.1 dB) while the excess
# varies by 3x. So the budget is mostly a flat allowance gated on the artifact
# being present, with only a weak proportional term.
#
# The base sits just under the cheapest well-aimed clean measured (0.036), so
# a preset that costs no more than the best-behaved one passes essentially
# untouched and anything greedier is pulled back.
#
# Four songs is not a calibration set. Re-run scripts/calibrate_budget.py with
# more material before trusting these to two significant figures; the anchor
# that matters most (a clean master earns zero) does not depend on them.
SONES_BASE = 0.030
SONES_PER_DB = 0.010

# Never allow more than this however hashed the track is. A render this far
# gone is a re-render, not a repair job.
MAX_BUDGET_SONES = 0.10

# A SECOND ceiling, on spectral-tilt damage.
#
# Gating on removed loudness alone is not enough, and a test caught it: a
# -12 dB shelf at 3 kHz registers only 0.007 sones of missing content while
# scoring 71.7 on lin_dist. Broad tilt moves little *loudness* and ruins a
# master, which is precisely the failure in the assessment - so the tilt
# measure needs a ceiling of its own, and the cleaning must satisfy both.
#
# Measured on the four sources plus the clean control: Cymbal Sheen scores
# 0.04-0.08, Suno Hash 0.43-0.79, Deep Scrub 12.5-20.4. A ceiling of 1.0
# passes the two presets a listener accepted and stops the one that was
# ranked last on every song.
LIN_DIST_BASE = 1.0
LIN_DIST_PER_DB = 0.25
MAX_LIN_DIST = 3.0

# A budget below this is treated as zero: no measurable artifact, so any
# removal is collateral.
MIN_BUDGET_SONES = 0.004

# Mix-back search. The damage measure is monotonic in the mix amount, so a
# bisection converges quickly and deterministically.
SEARCH_ITERS = 6
SEARCH_TOL = 0.02


@dataclass
class Budget:
    """How much audible removal this track's own artifact content justifies.

    Two ceilings, both of which must hold: `sones` caps how much audible
    content may go, `lin_dist` caps how far the tone may tilt. Cleaning can
    breach either one on its own.
    """
    sones: float
    lin_dist: float
    flicker_excess_db: float
    reason: str

    def as_dict(self) -> Dict[str, Any]:
        return {"sones": round(self.sones, 4),
                "lin_dist": round(self.lin_dist, 3),
                "flicker_excess_db": round(self.flicker_excess_db, 2),
                "reason": self.reason}

    def fits(self, damage) -> bool:
        """Is this damage within both ceilings?"""
        return (damage.missing <= self.sones + 1e-9
                and damage.lin_dist <= self.lin_dist + 1e-9)


def estimate_budget(x: np.ndarray, sr: int,
                    flicker_excess_db: Optional[float] = None) -> Budget:
    """How much removal this track has earned.

    Pass `flicker_excess_db` when the detector has already measured it (an
    Analyze run has); otherwise it is measured here.
    """
    if flicker_excess_db is None:
        from .detect import evidence_scan
        flicker_excess_db = float(evidence_scan(x, sr).evidence.flicker_excess_db)

    excess = float(flicker_excess_db) - EXCESS_FLOOR_DB
    if excess <= 0.0:
        return Budget(
            0.0, 0.0, float(flicker_excess_db),
            "No hash signature: the brilliance band flickers no more than the "
            "mids, so there is nothing to remove and any removal is collateral.")

    sones = min(SONES_BASE + excess * SONES_PER_DB, MAX_BUDGET_SONES)
    lin = min(LIN_DIST_BASE + excess * LIN_DIST_PER_DB, MAX_LIN_DIST)
    if sones < MIN_BUDGET_SONES:
        return Budget(0.0, 0.0, float(flicker_excess_db),
                      "Hash signature too faint to act on.")
    capped = " (capped)" if sones >= MAX_BUDGET_SONES else ""
    return Budget(
        sones, lin, float(flicker_excess_db),
        f"{flicker_excess_db:+.1f} dB of excess flicker in 4.5-12 kHz "
        f"justifies up to {sones:.3f} sones of audible removal and "
        f"{lin:.2f} of tone shift{capped}.")


@dataclass
class BudgetReport:
    """What the cleaning cost, and what had to be given back to stay in
    budget. `mix` of 1.0 means the preset ran in full."""
    mix: float
    budget_sones: float
    damage_before: Dict[str, float] = field(default_factory=dict)
    damage_after: Dict[str, float] = field(default_factory=dict)
    reason: str = ""
    held_back: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return {"mix": round(self.mix, 3),
                "budget_sones": round(self.budget_sones, 4),
                "damage_before": self.damage_before,
                "damage_after": self.damage_after,
                "held_back": self.held_back,
                "reason": self.reason}


def _blend(original: np.ndarray, cleaned: np.ndarray, mix: float) -> np.ndarray:
    """`mix` of what the preset removed. 1.0 = the cleaned signal, 0.0 = the
    original untouched."""
    if mix >= 1.0:
        return cleaned
    if mix <= 0.0:
        return original
    return original + mix * (cleaned - original)


def apply_within_budget(original: np.ndarray, cleaned: np.ndarray, sr: int,
                        budget: Budget) -> tuple[np.ndarray, BudgetReport]:
    """Hold the cleaning to what the track's artifact content justifies.

    Returns the audio to use and a report of what happened. When the cleaning
    already fits, the cleaned signal is returned untouched and `mix` is 1.0.
    """
    orig = as_2d(np.asarray(original, dtype=np.float32))
    clean = as_2d(np.asarray(cleaned, dtype=np.float32))
    n = min(orig.shape[0], clean.shape[0])
    orig, clean = orig[:n], clean[:n]

    full = measure_damage(orig, clean, sr)
    before = full.as_dict()

    if budget.sones <= 0.0:
        # Nothing earned. Anything removed is collateral, so remove nothing.
        return orig, BudgetReport(
            mix=0.0, budget_sones=0.0, damage_before=before,
            damage_after={"lin_dist": 0.0, "missing": 0.0, "added": 0.0},
            held_back=True,
            reason="No artifact measured, so no removal is justified. "
                   + budget.reason)

    if budget.fits(full):
        return clean, BudgetReport(
            mix=1.0, budget_sones=budget.sones, damage_before=before,
            damage_after=before, held_back=False,
            reason=(f"Cleaning cost {full.missing:.3f} sones and "
                    f"{full.lin_dist:.2f} of tone shift, within the "
                    f"{budget.sones:.3f} and {budget.lin_dist:.2f} the track "
                    f"earned."))

    # Over budget on one ceiling or both: find the largest mix that satisfies
    # every ceiling. Damage rises with mix, so bisect. Cheap because each step
    # is one damage measurement, not a re-run of the cleaning.
    lo, hi = 0.0, 1.0
    best = 0.0
    best_damage = {"lin_dist": 0.0, "missing": 0.0, "added": 0.0}
    for _ in range(SEARCH_ITERS):
        mid = 0.5 * (lo + hi)
        d = measure_damage(orig, _blend(orig, clean, mid), sr)
        if budget.fits(d):
            best, best_damage = mid, d.as_dict()
            lo = mid
        else:
            hi = mid
        if hi - lo < SEARCH_TOL:
            break

    breached = []
    if full.missing > budget.sones:
        breached.append(f"{full.missing:.3f} sones of content against a "
                        f"budget of {budget.sones:.3f}")
    if full.lin_dist > budget.lin_dist:
        breached.append(f"{full.lin_dist:.2f} of tone shift against a budget "
                        f"of {budget.lin_dist:.2f}")

    y = _blend(orig, clean, best)
    return y, BudgetReport(
        mix=best, budget_sones=budget.sones, damage_before=before,
        damage_after=best_damage, held_back=True,
        reason=(f"Cleaning would have cost " + " and ".join(breached)
                + f", so it was held to {best * 100:.0f}%. " + budget.reason))
