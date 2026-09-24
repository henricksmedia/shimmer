"""The detectors behind Analyze's findings, one per "What do you hear?" card.

Each measures one fault on the song as it came in and says how much there
is: nothing to report, "some" or "a lot". A card lights up (Found) only
from a detector here; one with no detector stays quiet rather than guess
(docs/PITFALLS.md, "A metric that cannot fail").

Every line was set on the test library (284 AI songs, scripts/
test_library.py; the numbers are in docs/DETECTORS.md), so it flags the
songs that stand out and leaves the rest alone:

  air       the 8-16 kHz bands against the tone target, below the song's
            own cutoff (the tone measurement mastering makes)
  lowmid    the 200-500 Hz bands against the tone target
  sibilance, harshness
            the share of the song the card's own fix acts on at full
            strength (cuts more than 1 dB of its band, in 50 ms frames).
            Those fixes only act when their band sticks out, so the share
            is the measure. Two finished masters read 0-5 %.

The last two are slow (a whole-song render each, 5-15 s), so they run
after the upload, in their own job (slow()).

Measures only: nothing here changes the audio.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Optional

import numpy as np

from ..master import tone
from .tones import estimate_cutoff_hz
from .track import analyze_spectrum

SOME, A_LOT = "some", "a lot"

# Lack of air: dB the 8-16 kHz bands sit under the tone target. The typical
# library song sits 4.7 dB under; 65 % are 3 dB or more under.
AIR_SOME_DB, AIR_A_LOT_DB = 3.0, 6.0
AIR_BAND_HZ = (8000.0, 16000.0)
# Low-mid build-up: dB the 200-500 Hz bands sit over the tone target. The
# typical song sits on it (-0.2 dB); 7 % are 2 dB or more over.
LOWMID_SOME_DB, LOWMID_A_LOT_DB = 2.0, 4.0
LOWMID_BAND_HZ = (200.0, 500.0)
# Sibilance: the de-esser acts on a typical core-set song 2.7 % of the time,
# the top tenth 12 % or more; the finished master "Hey" (real singing,
# real "s" sounds) reads 5 %.
SIBILANCE_SOME, SIBILANCE_A_LOT = 0.08, 0.14
# Harshness: the dynamic EQ acts on a typical song 3.3 % of the time, the
# top tenth 18 % or more; the finished masters read 0 and 1.5 %.
HARSHNESS_SOME, HARSHNESS_A_LOT = 0.06, 0.15
# The Amount Analyze recommends for a fix, by level. Every fix's 100 % was
# set under its damage limit (docs/STEP6-FIXES.md).
AMOUNT = {"some": 0.5, "a lot": 1.0}
_ACT_DB = 1.0            # a frame counts as acted on past this cut
_ACT_FRAME_S = 0.05


@dataclass(frozen=True)
class Reading:
    """One detector's measure: `value` in `unit`, and its level ("" when
    there is nothing to report)."""
    value: float
    unit: str
    level: str


def _level(value: float, some: float, a_lot: float) -> str:
    return A_LOT if value >= a_lot else SOME if value >= some else ""


def _tone_diff(source) -> np.ndarray:
    """The tone target minus the song, per band (tone.REF_FREQS), measured
    the way mastering measures it. Worked out once per song."""
    def make():
        spec = analyze_spectrum(source.audio, source.sr)
        return tone.REF_DB - np.asarray(spec["rel_db"], dtype=np.float64)
    return source._remember(("detect", "tone_diff"), make)


def _cutoff(source) -> Optional[float]:
    return source._remember(("detect", "cutoff"),
                            lambda: estimate_cutoff_hz(source.audio, source.sr).get("cutoff_hz"))


def air(source) -> Optional[Reading]:
    """How far the top end (8-16 kHz) sits under the tone target, in dB.
    Bands at or above 90 % of the song's cutoff are left out: there is only
    noise there. None when no band is left to measure."""
    f = tone.REF_FREQS
    top = tone.boost_limit_hz(_cutoff(source))
    band = (f >= AIR_BAND_HZ[0]) & (f <= AIR_BAND_HZ[1]) & (f < top)
    if not band.any():
        return None
    under = float(np.mean(_tone_diff(source)[band]))
    return Reading(round(under, 1), "dB", _level(under, AIR_SOME_DB, AIR_A_LOT_DB))


def lowmid(source) -> Reading:
    """How far the low mids (200-500 Hz) sit over the tone target, in dB."""
    f = tone.REF_FREQS
    band = (f >= LOWMID_BAND_HZ[0]) & (f <= LOWMID_BAND_HZ[1])
    over = float(-np.mean(_tone_diff(source)[band]))
    return Reading(round(over, 1), "dB", _level(over, LOWMID_SOME_DB, LOWMID_A_LOT_DB))


def _band(x: np.ndarray, sr: int, lo: float, hi: Optional[float]) -> np.ndarray:
    from scipy import signal as ss
    hi = min(hi or 0.45 * sr, 0.45 * sr)
    sos = ss.butter(4, [lo, hi], btype="bandpass", fs=sr, output="sos")
    return ss.sosfiltfilt(sos, np.asarray(x, dtype=np.float64), axis=0)


def acting_share(source, card: str) -> float:
    """The share of the song (50 ms frames with sound) where the card's fix,
    at full strength, cuts more than 1 dB of its band. Worked out once."""
    def make() -> float:
        from .. import catalog
        from ..render import render
        from ..settings import Settings
        s = Settings(fixes={card: 1.0}, auto=False, mastering=False, preserve_volume=False)
        r = render(source, s, with_removed=True)
        x = source.at_rate(r.sr)
        lo, hi = catalog.card(card).band_hz or (20.0, None)
        xb, rb = _band(x, r.sr, lo, hi), _band(r.removed, r.sr, lo, hi)
        n = int(_ACT_FRAME_S * r.sr)
        k = xb.shape[0] // n
        if k == 0:
            return 0.0
        fx = np.mean(xb[:k * n].reshape(k, n, -1) ** 2, axis=(1, 2))
        fk = np.mean((xb - rb)[:k * n].reshape(k, n, -1) ** 2, axis=(1, 2))
        live = fx > np.max(fx) * 1e-5
        if not live.any():
            return 0.0
        cut = 10.0 * np.log10((fx[live] + 1e-30) / (fk[live] + 1e-30))
        return float(np.mean(cut > _ACT_DB))
    return source._remember(("detect", "acting", card), make)


def sibilance(source) -> Reading:
    share = acting_share(source, "sibilance")
    return Reading(round(100 * share, 1), "%", _level(share, SIBILANCE_SOME, SIBILANCE_A_LOT))


def harshness(source) -> Reading:
    share = acting_share(source, "harshness")
    return Reading(round(100 * share, 1), "%", _level(share, HARSHNESS_SOME, HARSHNESS_A_LOT))


# The slow detectors, in the order the job runs them, with what each
# finding says.
SLOW = (
    ("sibilance", sibilance, "Harsh \u201cs\u201d sounds stick out {v:.0f} % of the song"),
    ("harshness", harshness, "The 2-5 kHz range sticks out {v:.0f} % of the song"),
)


def slow(source, step: Optional[Callable[[str, float], None]] = None) -> Dict[str, Reading]:
    """Every slow detector's reading for the song. `step(card, fraction)`
    hears how far it has got and may raise to stop."""
    out: Dict[str, Reading] = {}
    for i, (card, fn, _) in enumerate(SLOW):
        if step is not None:
            step(card, i / len(SLOW))
        out[card] = fn(source)
    if step is not None:
        step("", 1.0)
    return out
