"""De-click: the Clicks and crackle card's fix, rebuilt.

Short pops, ticks and crackle: a few samples to 3 ms where the waveform
jumps off its course and comes straight back. The fix finds each one and
fills it in from the sound on both sides of it.

What 1.x's de-clicker got wrong (docs/HANDOFF-CHECKLIST.md item 17): on
8 s clips with about 12 planted pops it counted 450-870 "clicks", because it
took drum hits for clicks, and it left the pops' energy where it was; it
took 0.104-0.107 sones of music. This one:

- **Pinpoints a click from both sides.** A model of the music predicts
  each sample from the ones before it (forward) and from the ones after it
  (backward). A click breaks both predictions, at the same samples; a hit
  breaks only the forward one, since after a hit the music follows its new
  course. Only samples both predictions miss are candidates.
- **Tells a pop from a hit.** A pop is short (at most MAX_MS) and the sound
  after it carries on at the level it had before; a hit starts something
  louder that keeps going (ONSET_RATIO).
- **Fills the gap from both sides.** The missing samples are the ones that
  best continue the model of the music on either side of the gap
  (least-squares AR interpolation, Janssen, Veldhuis and Vries, 1986), not a
  crossfade and not silence.

Amount sets how far a sample must stray to count: THRESHOLD_TOP x the
music's own prediction error at Amount 100 %, THRESHOLD_BOTTOM at 0 %.

The models are fitted on blocks counted from the start of the song and
nothing reaches more than a few milliseconds, so a preview window matches
the same span of a full render.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

import numpy as np
from scipy import signal as ss
from scipy.linalg import solve_toeplitz

ORDER = 24                     # samples the model looks back (and ahead)
BLOCK_MS = 40.0                # the model is refitted every 40 ms
THRESHOLD_TOP = 6.0            # robust sigmas of prediction error, at Amount 100 %. At
                               # 5, music that changes chord at once was flagged just
                               # past the change (5.8-6.2 sigma); at 6 it is not.
THRESHOLD_BOTTOM = 12.0        # ... at Amount 0 %
MAX_MS = 3.0                   # longer than this is not a click
PAD = 6                        # samples added either side of a found click (its tail)
ONSET_MS = 5.0                 # the stretch compared before and after
ONSET_RATIO = 4.0              # louder after than before by this power ratio: a hit
# The fill: a model of the music (FILL_ORDER samples back) fitted on CONTEXT
# samples either side of the gap, by the autocorrelation method. Chosen on
# five real songs (docs/STEP6-FIXES.md): it took out about 70 % of the pops'
# energy (0.31 left) and 46 % / 41 % of their audible share at 2.0 / 0.5
# sones. Longer models fitted on 10-20 ms filled steady synthetic chords
# better but misfired on the real songs' denser sound (up to 10x the pop's
# energy left on one song).
FILL_ORDER = ORDER
CONTEXT = 4 * ORDER
TAIL_SHARE = 0.25              # the gap runs past the flagged samples by this share of
                               # their length, for the click's fading tail
# After a click the music is predictable again; after a hit's noisy start it
# is not. The prediction error just past the click (beyond the ORDER samples
# the click itself spoils) must fall back under RETURN_RATIO x its usual
# power, on both sides. Off: on five real songs it threw out half the real
# pops with the hits, and the isolation check alone kept false alarms to a
# few per 8 s (docs/STEP6-FIXES.md).
CHECK_RETURN = False
RETURN_MS = 3.0
RETURN_RATIO = 4.0
# A click stands alone: its error peak is ISOLATION x the largest error
# around it, within ISOLATION_MS; or, with ISOLATION_SCALE set, within that
# many times the click's own length (at least ISOLATION_MIN_MS, at most
# ISOLATION_MS), so crackle, many tiny clicks close together, is judged on
# the millisecond or two around each one.
CHECK_ISOLATION = True
ISOLATION_MS = 10.0
ISOLATION = 3.0
ISOLATION_SCALE = 4.0
ISOLATION_MIN_MS = 1.0


@dataclass(frozen=True)
class Plan:
    """Nothing is needed from the whole song: clicks are found where they are."""


def plan(audio: np.ndarray, sr: int) -> Plan:
    return Plan()


def _ar(r: np.ndarray, p: int, noise: float = 1e-6) -> np.ndarray:
    """AR coefficients [1, a1..ap] from autocorrelation r[0..p]."""
    r = np.asarray(r, dtype=np.float64).copy()
    if r[0] <= 1e-20:
        return np.concatenate([[1.0], np.zeros(p)])
    r[0] *= 1.0 + noise                     # a little white noise keeps it stable
    return np.concatenate([[1.0], solve_toeplitz(r[:p], -r[1:p + 1])])


def _autocorr(x: np.ndarray, p: int) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    if x.size <= p:
        return np.zeros(p + 1)
    w = x * np.hanning(x.size)
    full = np.correlate(w, w, "full")
    mid = x.size - 1
    return full[mid:mid + p + 1] / x.size


def _residuals(x: np.ndarray, sr: int, offset: int):
    """The forward and backward prediction errors (magnitude) and their
    robust scale, sample by sample, from a model refitted every block."""
    n = x.size
    blk = max(ORDER * 4, int(round(BLOCK_MS * 1e-3 * sr)))
    first = (-int(offset)) % blk
    edges = [0] + list(range(first, n, blk)) + [n]
    edges = sorted(set(e for e in edges if 0 <= e <= n))
    ef, eb = np.zeros(n), np.zeros(n)
    sf, sb = np.full(n, 1e-12), np.full(n, 1e-12)
    for b0, b1 in zip(edges[:-1], edges[1:]):
        if b1 - b0 < 2:
            continue
        c0, c1 = max(0, b0 - ORDER), min(n, b1 + ORDER)
        seg = x[c0:c1]
        a = _ar(_autocorr(seg, ORDER), ORDER)
        fwd = ss.lfilter(a, [1.0], seg)
        bwd = ss.lfilter(a, [1.0], seg[::-1])[::-1]
        s0, s1 = b0 - c0, b1 - c0
        ef[b0:b1], eb[b0:b1] = np.abs(fwd[s0:s1]), np.abs(bwd[s0:s1])
        sf[b0:b1] = 1.4826 * np.median(ef[b0:b1]) + 1e-12
        sb[b0:b1] = 1.4826 * np.median(eb[b0:b1]) + 1e-12
    return ef, eb, sf, sb


def _returns(ef, eb, sf, sb, s: int, e: int, sr: int) -> bool:
    """Past the ORDER samples the click spoils, both predictions are back to
    their usual error within RETURN_MS."""
    w = max(4, int(round(RETURN_MS * 1e-3 * sr)))
    a0, a1 = e + ORDER, e + ORDER + w
    b0, b1 = s - ORDER - w, s - ORDER
    if b0 < 0 or a1 > ef.size:
        return False
    return bool(np.mean(ef[a0:a1] ** 2) < RETURN_RATIO * np.mean(sf[a0:a1] ** 2)
                and np.mean(eb[b0:b1] ** 2) < RETURN_RATIO * np.mean(sb[b0:b1] ** 2))


def _isolated(ef, eb, s: int, e: int, sr: int) -> bool:
    """The click's error peak stands ISOLATION x above every error within
    ISOLATION_MS around it."""
    ms = ISOLATION_MS
    if ISOLATION_SCALE > 0.0:
        ms = min(ISOLATION_MS, max(ISOLATION_MIN_MS, ISOLATION_SCALE * (e - s) / sr * 1e3))
    w = int(round(ms * 1e-3 * sr)) + ORDER
    peak = min(float(ef[s:e].max()), float(eb[s:e].max()))
    lo, hi = slice(max(0, s - w), max(0, s - ORDER)), slice(min(ef.size, e + ORDER), min(ef.size, e + w))
    around = np.concatenate([ef[lo], ef[hi], eb[lo], eb[hi]])
    return around.size == 0 or peak > ISOLATION * float(around.max())


def _runs(flags: np.ndarray) -> List[Tuple[int, int]]:
    d = np.diff(np.concatenate([[0], flags.astype(np.int8), [0]]))
    starts, ends = np.where(d == 1)[0], np.where(d == -1)[0]
    runs: List[Tuple[int, int]] = []
    for s, e in zip(starts, ends):
        if runs and s - runs[-1][1] <= 2 * PAD:
            runs[-1] = (runs[-1][0], e)
        else:
            runs.append((s, e))
    return runs


def _is_click(x: np.ndarray, sr: int, s: int, e: int) -> bool:
    if e - s > MAX_MS * 1e-3 * sr:
        return False
    w = max(4, int(round(ONSET_MS * 1e-3 * sr)))
    before = x[max(0, s - PAD - w):max(0, s - PAD)]
    after = x[min(x.size, e + PAD):min(x.size, e + PAD + w)]
    if before.size < w // 2 or after.size < w // 2:
        return False
    pb = float(np.mean(before ** 2)) + 1e-20
    pa = float(np.mean(after ** 2)) + 1e-20
    return pa < ONSET_RATIO * pb


def _fill(x: np.ndarray, s: int, e: int, sr: int = 48000) -> None:
    """Least-squares AR interpolation of x[s:e], in place, from a model of
    the music fitted on the stretches either side."""
    p = FILL_ORDER
    pre = x[max(0, s - CONTEXT):s]
    post = x[e:min(x.size, e + CONTEXT)]
    parts = [seg for seg in (pre, post) if seg.size > p]
    if not parts:
        return
    a = _ar(sum(_autocorr(seg, p) for seg in parts) / len(parts), p)
    r0, r1 = max(0, s - p), min(x.size, e + p)
    region = x[r0:r1].astype(np.float64)
    m = region.size
    if m <= p:
        return
    # Row i of A gives the prediction error at region[i + p].
    A = np.zeros((m - p, m))
    for i in range(m - p):
        A[i, i:i + p + 1] = a[::-1]
    unknown = np.zeros(m, dtype=bool)
    unknown[s - r0:e - r0] = True
    Au, Ak = A[:, unknown], A[:, ~unknown]
    sol, *_ = np.linalg.lstsq(Au, -Ak @ region[~unknown], rcond=None)
    x[s:e] = sol


def find(x: np.ndarray, sr: int, amount: float, offset: int = 0) -> List[Tuple[int, int]]:
    """The clicks in one channel: (start, end) sample spans, padded."""
    a = float(np.clip(amount, 0.0, 1.0))
    k = THRESHOLD_BOTTOM + (THRESHOLD_TOP - THRESHOLD_BOTTOM) * a
    ef, eb, sf, sb = _residuals(x, sr, offset)
    out: List[Tuple[int, int]] = []
    for s, e in _runs((ef > k * sf) & (eb > k * sb)):
        if not _is_click(x, sr, s, e):
            continue
        if CHECK_RETURN and not _returns(ef, eb, sf, sb, s, e, sr):
            continue
        if CHECK_ISOLATION and not _isolated(ef, eb, s, e, sr):
            continue
        # A click fades out: its tail falls under the threshold before it is
        # gone, so the gap runs on a little past the flagged samples. Only a
        # little: every sample added to a gap makes the fill less exact.
        out.append((max(0, s - PAD), min(x.size, e + max(PAD, int(TAIL_SHARE * (e - s))))))
    return out


def apply(x: np.ndarray, sr: int, p: Plan, amount: float, offset: int = 0) -> np.ndarray:
    """Find and fill the clicks in each channel. Returns x itself when none
    are found."""
    if amount <= 0.0 or np.asarray(x).shape[0] == 0:
        return x
    a = np.asarray(x, dtype=np.float64)
    y = a[:, None].copy() if a.ndim == 1 else a.copy()
    changed = False
    for c in range(y.shape[1]):
        for s, e in find(y[:, c], sr, amount, offset):
            _fill(y[:, c], s, e, sr)
            changed = True
    if not changed:
        return x
    return y if a.ndim == 2 else y[:, 0]


def summary(p: Plan, amount: float) -> Dict[str, Any]:
    a = float(np.clip(amount, 0.0, 1.0))
    return {"tool": "declick",
            "threshold_sigma": round(THRESHOLD_BOTTOM + (THRESHOLD_TOP - THRESHOLD_BOTTOM) * a, 2)}
