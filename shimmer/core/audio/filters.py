"""One filter design for every EQ-type filter in the engine.

"The dB you set is the dB you get." The old engine designed shelves and bells
at full gain and then ran them forward and backward, so each landed at twice
its setting (docs/ARCHITECTURE.md §10). Here a filter that runs both ways is
designed at half its gain, so the two passes add up to exactly the setting.

Which way a filter runs is set by measurement (ARCHITECTURE §19.1 item 16):

- **Both ways (zero-phase)** when its pre-echo stays within 20 ms of a hit.
  Bells, shelves and notches at normal settings. Nothing shifts in time
  between low and high.
- **One way** otherwise. Every high-pass and low-pass: a zero-phase 30 Hz
  low-cut put pre-echo 32-47 ms ahead of a kick drum. And any bell that
  rings long, such as a low, narrow one.

`phase="auto"` applies that rule. A control the user sweeps can pin
`phase="minimum"` (always one way) so the curve's shape never changes as the
knob moves; `phase="zero"` forces both ways where bands are split and summed
back, which needs them to line up in time.

Designs: the RBJ Audio EQ Cookbook biquads for bells and shelves; a notch is
a deep, narrow bell, so its depth is its gain. Passes are 2nd-order
Butterworth (12 dB per octave), -3.01 dB at the cutoff.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.signal import butter, sosfilt, sosfiltfilt

KINDS = ("bell", "low_shelf", "high_shelf", "high_pass", "low_pass", "notch")
PHASES = ("auto", "zero", "minimum")

# Pre-echo the ear does not hear: nothing louder than this, this long before
# a hit (backward masking covers roughly the last 5-20 ms before an onset).
PRE_ECHO_WINDOW_S = 0.020
PRE_ECHO_FLOOR_DB = -60.0


@dataclass(frozen=True)
class Design:
    """A designed filter. Pass it to apply()."""
    kind: str
    hz: float
    sr: int
    gain_db: float
    q: float
    sos: np.ndarray      # second-order sections, shape (k, 6); empty = no change
    two_way: bool        # True: zero-phase (run forward, then backward)

    @property
    def is_identity(self) -> bool:
        return self.sos.size == 0


def _rbj(kind: str, hz: float, sr: int, gain_db: float, q: float) -> np.ndarray:
    """One RBJ cookbook biquad as a (1, 6) second-order section."""
    A = 10.0 ** (gain_db / 40.0)
    w = 2.0 * np.pi * hz / sr
    cw, sw = np.cos(w), np.sin(w)
    alpha = sw / (2.0 * q)
    if kind in ("bell", "notch"):
        b = (1 + alpha * A, -2 * cw, 1 - alpha * A)
        a = (1 + alpha / A, -2 * cw, 1 - alpha / A)
    elif kind == "low_shelf":
        k = 2 * np.sqrt(A) * alpha
        b = (A * ((A + 1) - (A - 1) * cw + k), 2 * A * ((A - 1) - (A + 1) * cw),
             A * ((A + 1) - (A - 1) * cw - k))
        a = ((A + 1) + (A - 1) * cw + k, -2 * ((A - 1) + (A + 1) * cw),
             (A + 1) + (A - 1) * cw - k)
    else:  # high_shelf
        k = 2 * np.sqrt(A) * alpha
        b = (A * ((A + 1) + (A - 1) * cw + k), -2 * A * ((A - 1) + (A + 1) * cw),
             A * ((A + 1) + (A - 1) * cw - k))
        a = ((A + 1) - (A - 1) * cw + k, 2 * ((A - 1) - (A + 1) * cw),
             (A + 1) - (A - 1) * cw - k)
    a0 = a[0]
    return np.array([[b[0] / a0, b[1] / a0, b[2] / a0, 1.0, a[1] / a0, a[2] / a0]])


def _pre_echo_db(sos: np.ndarray, sr: int, hz: float) -> float:
    """Loudest zero-phase response more than 20 ms before a hit, in dB
    relative to the response's peak.

    The hit is a tone at the filter's own frequency, switched on at once. A
    filter rings at its own frequency, so this is the worst case. A click is
    not: its energy is spread across every frequency, and a 50 Hz bell that
    passed with a click put -47 dB of pre-echo ahead of a kick drum.
    """
    n = sr                                      # one second on each side
    t = np.arange(n) / sr
    tone = np.cos(2 * np.pi * hz * t)
    fade = n // 10                              # no edge at the far end
    tone[-fade:] *= np.hanning(2 * fade)[fade:]
    x = np.concatenate([np.zeros(n), tone])
    y = sosfiltfilt(sos, x)
    early = np.abs(y[:n - int(PRE_ECHO_WINDOW_S * sr)])
    return float(20.0 * np.log10(early.max() / np.abs(y).max() + 1e-300))


def design(kind: str, hz: float, sr: int, gain_db: float = 0.0, q: float = 0.707,
           phase: str = "auto") -> Design:
    """Design one filter.

    kind     one of KINDS
    hz       centre (bell, notch), corner (shelves) or cutoff (passes)
    gain_db  bells and shelves: the gain at the centre or on the shelf;
             notch: the depth (negative); passes: ignored
    q        bells and notches: width (higher is narrower); shelves: slope
             (0.707 is the steepest with no bump); passes: ignored
    phase    "auto" (the measured rule), "zero" or "minimum"
    """
    if kind not in KINDS:
        raise ValueError(f"unknown filter kind {kind!r}; expected one of {KINDS}")
    if phase not in PHASES:
        raise ValueError(f"unknown phase {phase!r}; expected one of {PHASES}")
    hz, sr, gain_db, q = float(hz), int(sr), float(gain_db), float(q)
    if not 0.0 < hz < sr / 2.0:
        raise ValueError(f"{kind} at {hz} Hz is outside 0-{sr / 2:.0f} Hz")
    if q <= 0.0:
        raise ValueError("q must be positive")

    if kind in ("high_pass", "low_pass"):
        sos = butter(2, hz, btype="highpass" if kind == "high_pass" else "lowpass",
                     fs=sr, output="sos")
        if phase == "zero":
            raise ValueError("passes always run one way: zero-phase smears kick "
                             "drums with pre-echo (ARCHITECTURE §19.1 item 16)")
        return Design(kind, hz, sr, 0.0, q, sos, two_way=False)

    if kind == "notch" and gain_db > 0.0:
        raise ValueError("a notch cuts: its gain_db (depth) must be negative")
    if gain_db == 0.0:
        return Design(kind, hz, sr, 0.0, q, np.zeros((0, 6)), two_way=True)

    half = _rbj(kind, hz, sr, gain_db / 2.0, q)
    if phase == "zero" or (phase == "auto" and _pre_echo_db(half, sr, hz) <= PRE_ECHO_FLOOR_DB):
        return Design(kind, hz, sr, gain_db, q, half, two_way=True)
    return Design(kind, hz, sr, gain_db, q, _rbj(kind, hz, sr, gain_db, q), two_way=False)


def apply(x: np.ndarray, sr: int, d: Design) -> np.ndarray:
    """Filter audio of shape (n,) or (n, channels). Returns float64, same
    shape. Every channel gets the same filter."""
    if int(sr) != d.sr:
        raise ValueError(f"filter designed for {d.sr} Hz, audio is {sr} Hz")
    y = np.asarray(x, dtype=np.float64)
    if d.is_identity:
        return y.copy()
    if d.two_way:
        return sosfiltfilt(d.sos, y, axis=0)
    return sosfilt(d.sos, y, axis=0)
