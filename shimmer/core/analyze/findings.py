"""What Analyze reports, card by card: findings(source) -> [Finding].

Each finding is {card, value, unit, detail} (docs/API.md §3), keyed by a
"What do you hear?" card (shimmer.core.catalog).

Only what can be measured reliably today reports:

- **Fixed tones:** the whole-file scan the notch uses. The notch removes
  96 % of a fixed tone.
- **Loudness:** how far the song sits under the chosen Loudness target.

Every other card reports nothing until its detector passes its own tests
(REBUILD-TRACKER Step 6). A card that cannot measure its fault stays quiet
rather than guess: the old detector recommended cleaning finished masters
(PITFALLS "A metric that cannot fail").
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List

from .. import catalog
from ..audio import meters
from ..repair.notch import plan_from_lines
from .tones import scan_fixed_lines

LOUDNESS_REPORT_DB = 1.0       # under the target by less than this: no finding


@dataclass(frozen=True)
class Finding:
    card: str
    value: float
    unit: str
    detail: str


def findings(source, loudness_target: str = catalog.DEFAULT_LOUDNESS) -> List[Finding]:
    """What this song has, as findings for the cards. Measures only."""
    out: List[Finding] = []
    for n in plan_from_lines(scan_fixed_lines(source.audio, source.sr), source.sr).notches:
        out.append(Finding(
            "tones", round(n.hz, 1), "Hz",
            f"A steady tone at {n.hz / 1000.0:.2f} kHz, {n.excess_db:.0f} dB above "
            f"its surroundings for most of the song"))

    target = catalog.loudness_target(loudness_target)
    lufs = meters.loudness(source.audio, source.sr)
    if math.isfinite(lufs) and target.lufs - lufs >= LOUDNESS_REPORT_DB:
        under = target.lufs - lufs
        out.append(Finding(
            "loudness", round(under, 1), "dB",
            f"{under:.1f} dB quieter than {target.label} ({target.lufs:g} LUFS)"))
    return out
