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

  grain     the grain on the voice: how much of the centre's 4-8 kHz the
            Vocal grain fix's grain step takes out (sharp spots standing
            above their neighbours in time and pitch), in the 15 s
            stretches where the voice is strongest, as dB. Only that step:
            the fix's two floor steps take as much or more from finished
            masters, whose full top end is not grain.

The last three are slow (a whole-song render or plan each, 5-15 s), so they
run after the upload, in their own job (slow()).

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
# set under its damage limit (docs/STEP6-FIXES.md), except Vocal grain's:
# its 100 % is the author's "extra strong", so it starts at 40 % for some
# and at his "strong", 75 %, for a lot.
AMOUNT = {"some": 0.5, "a lot": 1.0}
AMOUNTS = {"grain": {"some": 0.4, "a lot": 0.75}}


def amount(card: str, level: str) -> float:
    """The Amount Analyze recommends for this card's fix at this level."""
    return AMOUNTS.get(card, AMOUNT)[level]
_ACT_DB = 1.0            # a frame counts as acted on past this cut
_ACT_FRAME_S = 0.05
# Vocal grain: dB the fix's grain step takes from the centre's 4-8 kHz, in
# the song's strongest voice stretches (grain_db). Set on the library's
# spread (docs/DETECTORS.md).
# Library: typical song 2.4 dB, top tenth 3.8 dB or more. Just Another Rain
# 4.1-4.7 dB; the finished masters 1.0 and 1.7 dB.
GRAIN_SOME_DB, GRAIN_A_LOT_DB = 2.5, 3.5
GRAIN_WINDOW_S = 15.0
GRAIN_LOUD_DB = -6.0     # a stretch this far under the song's loud level is left out


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


def grain_windows(source):
    """Per 15 s stretch of the song: (centre_db, level_db, share), where
    share is the part of the centre's 4-8 kHz energy the Vocal grain fix's
    grain step takes, centre_db how much more of the 1-4 kHz energy sits in
    the centre than the sides (a lead vocal sits in the centre), and
    level_db the stretch's level against the song's loud parts."""
    from scipy import signal as ss

    from ..repair import vocal_grain as vg

    def make():
        sr = source.sr
        x = np.asarray(source.audio, dtype=np.float64)
        x = x[:, None] if x.ndim == 1 else x
        if x.shape[1] == 1:
            x = np.repeat(x, 2, axis=1)
        mid, side = x.mean(axis=1), (x[:, 0] - x[:, 1]) / 2.0
        if mid.size < vg.NPER:
            return []
        st = vg.steps(mid, sr)
        core = (st.f >= vg.BAND_HZ[0]) & (st.f <= vg.BAND_HZ[1])
        cb = core[st.band]
        P0 = st.power[core]
        before = P0 * st.g1[core] ** 2 * st.g2[cb] ** 2      # what the grain step works on
        e0 = P0.sum(axis=0)
        taken = (before * (1.0 - st.g3[cb] ** 2)).sum(axis=0)
        f = np.fft.rfftfreq(vg.NPER, 1.0 / sr)

        def power(sig):
            return np.abs(ss.stft(sig, fs=sr, nperseg=vg.NPER, noverlap=vg.NPER - vg.HOP)[2]) ** 2

        Pm, Ps = power(mid), power(side)
        n = min(Pm.shape[1], e0.size)
        e0, taken = e0[:n], taken[:n]
        vb = (f >= 1000.0) & (f <= 4000.0)
        em, es = Pm[vb, :n].sum(axis=0), Ps[vb, :n].sum(axis=0)
        per = int(round(GRAIN_WINDOW_S * sr / vg.HOP))
        loud = np.percentile(em, 90) + 1e-20
        out = []
        for k in range(0, n - per + 1, per):
            s = slice(k, k + per)
            out.append((float(10 * np.log10((em[s].sum() + 1e-20) / (es[s].sum() + 1e-20))),
                        float(10 * np.log10(em[s].mean() / loud + 1e-20)),
                        float(taken[s].sum() / (e0[s].sum() + 1e-20))))
        return out
    return source._remember(("detect", "grain_windows"), make)


def grain_db(windows) -> Optional[float]:
    """The song's grain score from its stretches: leave out the first and
    last and the quiet ones, keep the half where the voice is most in the
    centre, and take the middle share among them, as dB taken."""
    w = [x for x in windows[1:-1] if x[1] >= GRAIN_LOUD_DB]
    if not w:
        return None
    mid = float(np.median([x[0] for x in w]))
    shares = [x[2] for x in w if x[0] >= mid]
    share = float(np.median(shares))
    return -10.0 * float(np.log10(max(1e-6, 1.0 - share)))


def grain(source) -> Reading:
    v = grain_db(grain_windows(source))
    if v is None or GRAIN_SOME_DB is None:
        return Reading(round(v or 0.0, 1), "dB", "")
    return Reading(round(v, 1), "dB", _level(v, GRAIN_SOME_DB, GRAIN_A_LOT_DB))


def sibilance(source) -> Reading:
    share = acting_share(source, "sibilance")
    return Reading(round(100 * share, 1), "%", _level(share, SIBILANCE_SOME, SIBILANCE_A_LOT))


def harshness(source) -> Reading:
    share = acting_share(source, "harshness")
    return Reading(round(100 * share, 1), "%", _level(share, HARSHNESS_SOME, HARSHNESS_A_LOT))


# The slow detectors, in the order the job runs them, with what each
# finding says.
SLOW = (
    ("grain", grain, "Sharp grain rides on the voice ({v:.1f} dB in 4-8 kHz)"),
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
