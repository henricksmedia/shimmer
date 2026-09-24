"""What Analyze reports, card by card: findings(source) -> [Finding].

Each finding is {card, value, unit, detail, level, amount} (docs/API.md
§3), keyed by a "What do you hear?" card (shimmer.core.catalog). `level` is
"some" or "a lot" where the detector grades it; `amount` is the Amount
(0-1) Analyze recommends for the card's fix, or None.

What reports:

- **Fixed tones:** the whole-file scan the notch uses. The notch removes
  96 % of a fixed tone.
- **Loudness:** how far the song sits under the chosen Loudness target.
- **Lack of air, Low-mid build-up:** the song's tone against the tone
  target (analyze/detectors.py).

Every other card reports nothing until its detector passes its own tests.
A card that cannot measure its fault stays quiet rather than guess: the old
detector recommended cleaning finished masters (PITFALLS "A metric that
cannot fail").
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional

from .. import catalog
from ..audio import meters
from ..repair.notch import plan_from_lines
from . import detectors
from .tones import scan_fixed_lines

LOUDNESS_REPORT_DB = 1.0       # under the target by less than this: no finding


@dataclass(frozen=True)
class Finding:
    card: str
    value: float
    unit: str
    detail: str
    level: str = ""
    amount: Optional[float] = None


def findings(source, loudness_target: str = catalog.DEFAULT_LOUDNESS) -> List[Finding]:
    """What this song has, as findings for the cards. Measures only."""
    out: List[Finding] = []
    for n in plan_from_lines(scan_fixed_lines(source.audio, source.sr), source.sr).notches:
        out.append(Finding(
            "tones", round(n.hz, 1), "Hz",
            f"A steady tone at {n.hz / 1000.0:.2f} kHz, {n.excess_db:.0f} dB above "
            f"its surroundings for most of the song", amount=1.0))

    target = catalog.loudness_target(loudness_target)
    lufs = meters.loudness(source.audio, source.sr)
    if math.isfinite(lufs) and target.lufs - lufs >= LOUDNESS_REPORT_DB:
        under = target.lufs - lufs
        level = f"{target.lufs:g}".replace("-", "−")   # a real minus sign, as on screen
        out.append(Finding(
            "loudness", round(under, 1), "dB",
            f"{under:.1f} dB quieter than {target.label} ({level} LUFS)"))

    air = detectors.air(source)
    if air is not None and air.level:
        out.append(Finding(
            "air", air.value, air.unit,
            f"The top end (8-16 kHz) sits {air.value:.1f} dB under the tone target",
            level=air.level))
    mud = detectors.lowmid(source)
    if mud.level:
        out.append(Finding(
            "mud", mud.value, mud.unit,
            f"The low mids (200-500 Hz) sit {mud.value:.1f} dB over the tone target",
            level=mud.level, amount=detectors.AMOUNT[mud.level]))
    return out


def slow_findings(source, step=None) -> List[Finding]:
    """The findings of the slow detectors (analyze/detectors.py SLOW), which
    the screen asks for after the upload, as their own job."""
    readings = detectors.slow(source, step)
    out: List[Finding] = []
    for card, _fn, text in detectors.SLOW:
        r = readings[card]
        if r.level:
            out.append(Finding(card, r.value, r.unit, text.format(v=r.value),
                               level=r.level, amount=detectors.AMOUNT[r.level]))
    return out
