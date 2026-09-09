"""
references.py — Build the tone reference from music playing on this machine.

The tone target Shimmer masters toward (`mastering._REF_SHAPE_DB`) is measured
from real masters. Today those are all AI renders processed by one automated
service, which the data file says plainly. What is missing, and has been
missing since the target was built, is ordinary commercial music by other
people — the material that would say whether the target generalises.

That material is hard to get as files and easy to get as playback. So this
captures the system's audio output, measures it, and **throws the audio away**,
keeping only the 1/3-octave band curve. A few hundred bytes a track.

Discarding the audio is not a compromise, it is the better design:
  * the band curve is all a tone target needs;
  * nothing is copied, so there is no question about what is being stored;
  * a library of hundreds of tracks stays smaller than one WAV.

**Captured rows are tone-only, and the code enforces it.** Streaming players
normalise on playback, and normalisation is not just a level change — turning
a quiet track up applies a limiter, which alters dynamics. So LUFS, LRA and
true peak from a capture describe the player, not the master, and are never
recorded. Level itself is harmless: `relative_band_levels` normalises to the
median of 200 Hz-2 kHz, so a uniform gain cancels exactly (verified: a 12 dB
gain moves the curve by 0.000000 dB). Shape survives playback level; loudness
does not survive playback processing.

This is developer tooling. It is reachable at /static/references/ and is not
in the app's navigation, the same arrangement as static/marketing/. End users
get the constant this produces, not the machine that produced it.

Requires `soundcard` (Windows WASAPI loopback). Imported lazily so the app
runs without it.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np

from .mastering import (analyze_spectrum, relative_band_levels, _REF_FREQS,
                        _REF_DB)

# Where the library lives. Sits beside the file-derived reference so both can
# feed scripts/build_tone_reference.py.
LIBRARY = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "docs", "reference-library.json")

SR = 48000
BLOCK = 4096
MIN_SECONDS = 20.0        # below this a long-term average is not stable
MAX_SECONDS = 600.0       # a safety stop, not a target
SILENCE_DBFS = -60.0      # blocks quieter than this do not count as music

# A short excerpt reads slightly darker than the whole master, because a
# capture tends to catch quieter passages. Measured on the chain itself:
# eight masters that exist on disk, played through the player and captured,
# landed 0.6 dB below the file over 2.5-12.5 kHz (se 0.4, n=8). An earlier
# figure of -1.35 dB came from comparing 30 s windows against whole files and
# had a 95% interval of [-3.19, +0.50] — too wide to correct with. See
# BRIGHTNESS-ASSESSMENT.md §7.7.
EXCERPT_BIAS_DB = -0.6
EXCERPT_BIAS_SE_DB = 0.4

TONE_REFERENCE = os.path.join(os.path.dirname(LIBRARY), "tone-reference.json")


# ── Is a capture music, or a broken recording? ──────────────────────────

_GATE: Optional[Dict[str, float]] = None


def gate() -> Dict[str, float]:
    """Bounds that real masters stay inside, measured from the shipped corpus.

    Two captures in the first library read -50 and -43 dB at 10 kHz. No
    record does that; those were broken recordings, not dark music. But a
    plain median over the library counted them, and they set its headline.

    The bounds come from `docs/tone-reference.json` — masters known to be
    real — and deliberately NOT from the tone target. A gate that asks "does
    this look like the target?" rejects captures for disagreeing with it,
    which is the one question the library exists to answer. This asks only
    whether the roll-off is physically like music.

    The 1st percentile, so it rejects what no master in the corpus does
    rather than what an unusual one might.
    """
    global _GATE
    if _GATE is not None:
        return _GATE
    f = np.asarray(_REF_FREQS, dtype=np.float64)
    i10 = int(np.argmin(np.abs(f - 10000.0)))
    i16 = int(np.argmin(np.abs(f - 16000.0)))
    curves: List[np.ndarray] = []
    try:
        with open(TONE_REFERENCE, "r", encoding="utf-8") as fh:
            for row in json.load(fh).get("tracks", []):
                c = np.asarray(row["rel_db"], dtype=np.float64)
                if c.shape == f.shape:
                    curves.append(c)
    except (OSError, ValueError, KeyError):
        curves = []
    if len(curves) < 30:
        # Corpus missing or unreadable. Fall back to the values it produced
        # when this was written (317 masters), so the gate still works.
        _GATE = {"n": 0, "hz10_db": -29.1, "hz16_db": -40.1,
                 "slope_db_oct": -14.0}
        return _GATE
    arr = np.array(curves)
    hi = (f >= 4000.0) & (f <= 16000.0)
    slopes = np.array([float(np.polyfit(np.log2(f[hi]), c[hi], 1)[0])
                       for c in arr])
    _GATE = {"n": float(len(arr)),
             "hz10_db": float(np.percentile(arr[:, i10], 1)),
             "hz16_db": float(np.percentile(arr[:, i16], 1)),
             "slope_db_oct": float(np.percentile(slopes, 1))}
    return _GATE


SOURCES = os.path.join(os.path.dirname(os.path.dirname(LIBRARY)), "sources")


def is_control(row: Dict[str, Any]) -> bool:
    """Is this a capture of a file we already have, rather than new evidence?

    Playing a local file through the player and capturing it is how the chain
    gets validated — it is the only way to compare a capture against a known
    truth. Those rows are useful and must be kept, but they are not commercial
    music. Most are masters from the same service the tone target was built
    from, so pooling them into the median pulls the answer toward the target
    and hides the very difference the library exists to measure. Measured: the
    difference moves from -7.8 dB to -4.7 dB when eight of them are mixed in.

    A row is a control when a file of the same name sits in `sources/`.
    """
    label = str(row.get("label") or "").strip()
    if not label:
        return False
    for ext in (".wav", ".flac", ".mp3", ".m4a", ".ogg"):
        if os.path.exists(os.path.join(SOURCES, label + ext)):
            return True
    return False


def rejection(row: Dict[str, Any]) -> str:
    """Why this row is not usable, or "" if it is. Reasons are user-facing."""
    heard = float(row.get("heard_seconds") or 0.0)
    if heard < MIN_SECONDS:
        return (f"Only {heard:.0f}s of music. A tone average needs at least "
                f"{MIN_SECONDS:.0f}s to settle.")
    try:
        c = np.asarray(row["rel_db"], dtype=np.float64)
    except (KeyError, TypeError, ValueError):
        return "No tone curve was recorded."
    f = np.asarray(_REF_FREQS, dtype=np.float64)
    if c.shape != f.shape:
        return "The tone curve does not match the current bands."
    g = gate()
    i10 = int(np.argmin(np.abs(f - 10000.0)))
    i16 = int(np.argmin(np.abs(f - 16000.0)))
    if c[i10] < g["hz10_db"]:
        return (f"Almost nothing at 10 kHz ({c[i10]:.0f} dB). No real master "
                f"goes below {g['hz10_db']:.0f} dB there, so this is a broken "
                f"recording rather than a dark track.")
    if c[i16] < g["hz16_db"]:
        return (f"Almost nothing at 16 kHz ({c[i16]:.0f} dB), below anything "
                f"in the reference corpus ({g['hz16_db']:.0f} dB).")
    hi = (f >= 4000.0) & (f <= 16000.0)
    slope = float(np.polyfit(np.log2(f[hi]), c[hi], 1)[0])
    if slope < g["slope_db_oct"]:
        return (f"The top end falls off a cliff ({slope:.0f} dB per octave "
                f"above 4 kHz). Music rolls off; it does not drop like this.")
    return ""


def available() -> bool:
    try:
        import soundcard  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def now_playing() -> Dict[str, str]:
    """What Windows says is playing, from the same source the media keys use.

    This is what makes the capture one button instead of four. Spotify and
    most players report title and artist to the system transport controls, so
    a row can name itself and, more usefully, the capture can tell when the
    track changed — which is the part a listener should not have to do by
    hand. Silence detection cannot do this: Spotify plays gapless and
    crossfades, so there is often no gap between songs to find.

    Returns empty strings when nothing is reporting, and the caller falls
    back to a typed name.
    """
    try:
        import asyncio
        from winsdk.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as Manager)

        async def read() -> Dict[str, str]:
            mgr = await Manager.request_async()
            ses = mgr.get_current_session()
            if ses is None:
                return {}
            props = await ses.try_get_media_properties_async()
            info = ses.get_playback_info()
            return {
                "app": str(ses.source_app_user_model_id or ""),
                "title": str(props.title or "").strip(),
                "artist": str(props.artist or "").strip(),
                # 4 == playing in the Windows enum; anything else is paused,
                # stopped or changing, and must not accumulate.
                "playing": "1" if int(info.playback_status) == 4 else "",
            }

        return asyncio.run(read()) or {}
    except Exception:  # noqa: BLE001
        return {}


def _track_name(np: Dict[str, str]) -> str:
    t, a = np.get("title", ""), np.get("artist", "")
    if t and a:
        return f"{a} — {t}"
    return t or a or ""


def devices() -> List[Dict[str, Any]]:
    """Loopback devices — what the machine is playing, not what a mic hears."""
    import soundcard as sc
    out = []
    default = ""
    try:
        default = sc.default_speaker().name
    except Exception:  # noqa: BLE001
        pass
    for m in sc.all_microphones(include_loopback=True):
        if getattr(m, "isloopback", False):
            out.append({"id": str(m.id), "name": m.name,
                        "is_default": m.name == default})
    return out


@dataclass
class Capture:
    """A listening session. Holds a spectrum accumulator, never audio.

    One session spans as many tracks as you play. The accumulator is flushed
    to a saved row each time Windows reports a different title, so a playlist
    becomes a set of correctly named rows without anyone pressing anything.
    """
    device_id: str
    label: str = ""
    frames: int = 0
    seconds: float = 0.0
    heard: float = 0.0                     # seconds above the silence floor
    peak: float = 0.0
    _acc: Optional[np.ndarray] = None      # summed band power, linear
    _n: int = 0
    # Level is recorded per track, not because a tone curve needs it — the
    # curve is level-invariant by construction — but because without it a
    # capture that is really the noise floor is indistinguishable from a
    # genuinely dark master. The first library had two of those and there was
    # no way to tell which. It stays out of `rel_db`; it is diagnostics.
    _sq: float = 0.0                       # summed mean-square, linear
    track: str = ""                        # what is playing right now
    saved: List[str] = field(default_factory=list)
    auto: bool = True                      # follow track changes
    _stop: threading.Event = field(default_factory=threading.Event)
    _thread: Optional[threading.Thread] = None
    _lock: threading.Lock = field(default_factory=threading.Lock)
    error: str = ""

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return {"label": self.label, "seconds": round(self.seconds, 1),
                    "heard_seconds": round(self.heard, 1),
                    "peak_dbfs": (round(20.0 * float(np.log10(max(self.peak, 1e-9))), 1)),
                    "running": bool(self._thread and self._thread.is_alive()),
                    "enough": self.heard >= MIN_SECONDS,
                    "track": self.track,
                    "saved": list(self.saved),
                    "auto": self.auto,
                    "error": self.error}

    def _flush(self, name: str) -> Optional[str]:
        """Save what has accumulated as one row. Caller holds no lock."""
        with self._lock:
            acc, n, heard = self._acc, self._n, self.heard
            sq, pk = self._sq, self.peak
            self._acc, self._n, self.heard = None, 0, 0.0
            self._sq, self.peak = 0.0, 0.0
        if acc is None or n == 0 or heard < MIN_SECONDS:
            return None            # too short to be a stable average
        rel = relative_band_levels(
            10.0 * np.log10(np.maximum(acc / n, 1e-20)))
        row = {
            "label": (name or "untitled").strip(),
            "genre": "",
            "source": "capture",
            "tone_only": True,
            "heard_seconds": round(heard, 1),
            "rms_dbfs": round(10.0 * float(np.log10(max(sq / n, 1e-20))), 1),
            "peak_dbfs": round(20.0 * float(np.log10(max(pk, 1e-9))), 1),
            "rel_db": [round(float(v), 2) for v in rel],
        }
        # Say so at the moment of saving rather than only in the report, so a
        # bad capture is caught while the track is still fresh in mind.
        why = rejection(row)
        if why:
            row["rejected"] = why
        lib = load()
        lib["tracks"].append(row)
        save(lib)
        with self._lock:
            self.saved.append(name)
        return name


_ACTIVE: Optional[Capture] = None


def _run(cap: Capture) -> None:
    import soundcard as sc
    poll = 0.0
    try:
        mic = sc.get_microphone(cap.device_id, include_loopback=True)
        with mic.recorder(samplerate=SR, channels=2, blocksize=BLOCK) as rec:
            while not cap._stop.is_set() and cap.seconds < MAX_SECONDS:
                data = rec.record(numframes=BLOCK)
                mono = data.mean(axis=1) if data.ndim > 1 else data
                dur = len(mono) / SR
                pk = float(np.max(np.abs(mono))) if len(mono) else 0.0
                rms = float(np.sqrt(np.mean(mono ** 2))) if len(mono) else 0.0
                with cap._lock:
                    cap.seconds += dur
                    cap.peak = max(cap.peak, pk)

                # Ask Windows what is playing about once a second. Cheaper
                # than per-block, and a track change is not a sub-second
                # event.
                poll += dur
                if cap.auto and poll >= 1.0:
                    poll = 0.0
                    np_info = now_playing()
                    name = _track_name(np_info)
                    if name and name != cap.track:
                        # The track changed. Bank what we have under the name
                        # it was playing under, then start the next one.
                        if cap.track:
                            cap._flush(cap.track)
                        with cap._lock:
                            cap.track = name
                    elif not cap.track and name:
                        with cap._lock:
                            cap.track = name

                # Silence is not music. A paused player would otherwise pull
                # the average toward whatever the noise floor looks like.
                if rms > 10.0 ** (SILENCE_DBFS / 20.0):
                    bp = np.array(analyze_spectrum(mono, SR)["band_power_db"])
                    lin = 10.0 ** (bp / 10.0)
                    with cap._lock:
                        cap._acc = lin if cap._acc is None else cap._acc + lin
                        cap._n += 1
                        cap._sq += rms * rms
                        cap.heard += dur
    except Exception as e:  # noqa: BLE001
        with cap._lock:
            cap.error = str(e)


def start(device_id: str, label: str = "") -> Dict[str, Any]:
    global _ACTIVE
    if _ACTIVE and _ACTIVE._thread and _ACTIVE._thread.is_alive():
        return {"ok": False, "error": "already recording"}
    cap = Capture(device_id=device_id, label=label)
    cap._thread = threading.Thread(target=_run, args=(cap,), daemon=True)
    cap._thread.start()
    _ACTIVE = cap
    return {"ok": True, "status": cap.status()}


def status() -> Dict[str, Any]:
    return _ACTIVE.status() if _ACTIVE else {"running": False}


def stop(label: str = "", genre: str = "") -> Dict[str, Any]:
    """End the session and bank whatever is still accumulating."""
    global _ACTIVE
    cap = _ACTIVE
    if cap is None:
        return {"ok": False, "error": "nothing recording"}
    cap._stop.set()
    if cap._thread:
        cap._thread.join(timeout=5.0)
    _ACTIVE = None

    if cap.error:
        return {"ok": False, "error": cap.error, "saved": cap.saved}

    # Whatever is left belongs to the track that was playing when you stopped.
    final = cap._flush(label.strip() or cap.track or cap.label)
    saved = list(cap.saved)

    if not saved:
        if cap._n == 0 and cap.heard == 0.0:
            return {"ok": False, "saved": [], "error":
                    "no audio was heard — is the right device selected, and "
                    "is something playing?"}
        return {"ok": False, "saved": [], "error":
                f"only {cap.heard:.0f}s of music heard; "
                f"{MIN_SECONDS:.0f}s is the minimum for a stable average"}

    if genre.strip():
        lib = load()
        for row in lib["tracks"][-len(saved):]:
            row["genre"] = genre.strip()
        save(lib)

    return {"ok": True, "saved": saved, "final": final,
            "count": len(load()["tracks"])}


def load() -> Dict[str, Any]:
    if os.path.exists(LIBRARY):
        with open(LIBRARY, encoding="utf-8") as f:
            return json.load(f)
    return {"version": 1,
            "note": "Captured from system playback. Tone curves only — "
                    "loudness is not recorded because playback normalisation "
                    "alters it. Feeds scripts/build_tone_reference.py.",
            "bands_hz": [float(f) for f in _REF_FREQS],
            "tracks": []}


def save(lib: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(LIBRARY), exist_ok=True)
    with open(LIBRARY, "w", encoding="utf-8") as f:
        json.dump(lib, f, indent=1)


def summary() -> Dict[str, Any]:
    """The library's median curve against the target currently shipping, so
    it is obvious whether captured material agrees with it or not."""
    lib = load()
    rows = lib.get("tracks", [])
    good, bad, controls = [], [], []
    for r in rows:
        why = r.get("rejected") or rejection(r)
        if why:
            bad.append((r, why))
        elif is_control(r):
            controls.append((r, ""))
        else:
            good.append((r, why))
    out: Dict[str, Any] = {
        "count": len(good),
        "captured": len(rows),
        "controls": [{"label": r["label"],
                      "heard_seconds": r.get("heard_seconds")}
                     for r, _ in controls],
        "rejected": [{"label": r["label"], "why": why,
                      "heard_seconds": r.get("heard_seconds"),
                      "rms_dbfs": r.get("rms_dbfs")} for r, why in bad],
        "gate": gate(),
        "bands_hz": [float(f) for f in _REF_FREQS],
        "target_db": [round(float(v), 2) for v in _REF_DB],
        # Every row, in library order, each carrying its own status. The list
        # must stay aligned with the file because `delete(index)` indexes the
        # file: filtering here and indexing there removes the wrong track.
        "tracks": [{"label": r["label"], "genre": r.get("genre", ""),
                    "heard_seconds": r.get("heard_seconds"),
                    "rms_dbfs": r.get("rms_dbfs"),
                    "status": ("rejected" if (r.get("rejected") or rejection(r))
                               else "control" if is_control(r) else "ok"),
                    "why": r.get("rejected") or rejection(r)}
                   for r in rows]}
    if good:
        arr = np.array([r["rel_db"] for r, _ in good], dtype=np.float64)
        out["median_db"] = [round(float(v), 2) for v in np.median(arr, axis=0)]
        out["p16_db"] = [round(float(v), 2) for v in np.percentile(arr, 16, axis=0)]
        out["p84_db"] = [round(float(v), 2) for v in np.percentile(arr, 84, axis=0)]
        out["sd_db"] = [round(float(v), 2) for v in arr.std(axis=0, ddof=1)] \
            if len(arr) > 1 else [0.0] * arr.shape[1]
        out["vs_target_db"] = [round(float(a - b), 2)
                               for a, b in zip(out["median_db"], out["target_db"])]
    return out


def delete(index: int) -> Dict[str, Any]:
    lib = load()
    rows = lib.get("tracks", [])
    if not 0 <= index < len(rows):
        return {"ok": False, "error": "no such row"}
    removed = rows.pop(index)
    save(lib)
    return {"ok": True, "removed": removed["label"], "count": len(rows)}


# ── Report ──────────────────────────────────────────────────────────────

def _slope(freqs: np.ndarray, db: np.ndarray, lo: float, hi: float) -> float:
    """dB per octave of band power over a range, by least squares."""
    m = (freqs >= lo) & (freqs <= hi)
    x = np.log2(freqs[m])
    A = np.vstack([x, np.ones_like(x)]).T
    return float(np.linalg.lstsq(A, db[m], rcond=None)[0][0])


def report() -> Dict[str, Any]:
    """What the captured library says about the tone target that ships.

    The target in mastering._REF_SHAPE_DB was measured from masters of AI
    renders processed by one automated service. Whether it describes music in
    general has been the open question since it was built. This is the first
    evidence either way, so it is reported with its caveats attached rather
    than as a verdict.
    """
    s = summary()
    out: Dict[str, Any] = {"count": s["count"], "captured": s["captured"],
                           "rejected": s["rejected"], "gate": s["gate"],
                           "controls": s["controls"],
                           "bands_hz": s["bands_hz"],
                           "target_db": s["target_db"], "caveats": [], "rows": []}
    if s["count"] == 0:
        out["n"] = 0
        out["verdict"] = "unclear"
        out["headline"] = (
            "Nothing usable captured yet." if not s["captured"] else
            f"All {s['captured']} captures were left out as broken. "
            f"See the reasons below.")
        return out

    f = np.array(s["bands_hz"])
    med = np.array(s["median_db"])
    tgt = np.array(s["target_db"])
    spread = 0.5 * (np.array(s["p84_db"]) - np.array(s["p16_db"]))
    diff = med - tgt

    for i, hz in enumerate(f):
        if hz < 50 or hz > 20000:
            continue
        out["rows"].append({"hz": float(hz), "captured": round(float(med[i]), 2),
                            "spread": round(float(spread[i]), 2),
                            "target": round(float(tgt[i]), 2),
                            "diff": round(float(diff[i]), 2)})

    band = (f >= 2500) & (f <= 12500)
    n = int(s["count"])
    raw = float(diff[band].mean())

    # How much of this is the sample, and how much is real? Each track gives
    # one number for the band; their spread across tracks divided by root-n is
    # how far the median may move as more arrive. Reporting the difference
    # without it is how "8.4 dB darker" was published from a set that included
    # two broken captures.
    rows_ok = [t for t in load().get("tracks", [])
               if not (t.get("rejected") or rejection(t)) and not is_control(t)]
    vals = np.array([np.asarray(t["rel_db"], dtype=np.float64)[band].mean()
                     for t in rows_ok])
    se = float(vals.std(ddof=1) / np.sqrt(len(vals))) if len(vals) > 1 else 0.0

    # A capture reads slightly dark because it catches quieter passages, so
    # remove that before judging the target. Its own uncertainty is carried
    # too: correcting with a number and hiding its error bar is not better
    # than not correcting.
    corrected = raw - EXCERPT_BIAS_DB
    total_se = float(np.sqrt(se ** 2 + EXCERPT_BIAS_SE_DB ** 2))
    lo, hi = corrected - 1.96 * total_se, corrected + 1.96 * total_se

    out["n"] = n
    out["presence_mean_diff"] = round(raw, 2)
    out["presence_corrected"] = round(corrected, 2)
    out["presence_se"] = round(total_se, 2)
    out["presence_ci"] = [round(lo, 2), round(hi, 2)]
    out["excerpt_bias_db"] = EXCERPT_BIAS_DB
    # Search only where the report shows values. The 31.5 and 40 Hz bands sit
    # below most program material, so a track with nothing there produces a
    # meaningless outlier that would otherwise be reported as the headline.
    shown = (f >= 50) & (f <= 20000)
    j = int(np.arange(len(f))[shown][np.argmax(np.abs(diff[shown]))])
    out["worst_band_hz"] = float(f[j])
    out["worst_diff"] = round(float(diff[j]), 2)
    out["slope_captured"] = round(_slope(f, med, 4000.0, 16000.0), 2)
    out["slope_target"] = round(_slope(f, tgt, 4000.0, 16000.0), 2)

    # The verdict is about the interval, not the point estimate. A difference
    # is only a finding when the interval excludes zero; otherwise the honest
    # answer is that there is not enough here to say.
    direction = "darker" if corrected < 0 else "brighter"
    if lo <= 0.0 <= hi:
        out["verdict"] = "unclear"
        out["headline"] = (
            f"Not enough captured yet to say. The {n} tracks read "
            f"{corrected:+.1f} dB against the tone target across "
            f"2.5-12.5 kHz, but the range that fits the evidence is "
            f"{lo:+.1f} to {hi:+.1f} dB, which includes no difference at all.")
    else:
        out["verdict"] = "disagrees"
        out["headline"] = (
            f"The captured music is {abs(corrected):.1f} dB {direction} than "
            f"the tone target across 2.5-12.5 kHz, from {n} tracks. The range "
            f"that fits the evidence is {lo:+.1f} to {hi:+.1f} dB, so the "
            f"direction is not in doubt even at the edge of it.")

    bad_count = len(out.get("rejected", []))
    if bad_count:
        out["caveats"].append(
            f"{bad_count} capture{'s' if bad_count > 1 else ''} left out as "
            f"broken, listed below with the reason. They are not counted in "
            f"the {n} above.")
    out["caveats"].append(
        f"Corrected for excerpt bias: the raw difference is "
        f"{raw:+.1f} dB and a capture reads about {abs(EXCERPT_BIAS_DB):.1f} dB "
        f"dark because it catches quieter passages, so the figure above is "
        f"{corrected:+.1f} dB.")
    if n < 20:
        out["caveats"].append(
            f"Only {n} tracks. The spread between them is "
            f"{spread[(f >= 4000) & (f <= 10000)].mean():.1f} dB in the "
            f"presence band, so the median will move as more arrive.")
    out["caveats"].append(
        "The capture chain itself has been checked: playing a known file "
        "through the player and capturing it back agreed with the file to "
        "0.6 dB across eight masters. Re-run that check after changing "
        "anything in the audio path.")
    return out


def verify_against_file(path: str) -> Dict[str, Any]:
    """Capture-chain self-test: measure a file, compare with a capture of it.

    The one check that separates "commercial music is darker than the target"
    from "something between the player and this code is rolling off the top".
    Play the same file through the player, capture it, then point this at the
    file. A clean chain agrees within a fraction of a dB.
    """
    from .audio_io import load_audio
    lib = load()
    rows = lib.get("tracks", [])
    if not rows:
        return {"ok": False, "error": "capture the file first, then run this"}
    x, sr = load_audio(path)
    file_rel = relative_band_levels(
        np.array(analyze_spectrum(x, sr)["band_power_db"]))
    cap = np.array(rows[-1]["rel_db"])          # the most recent capture
    d = cap - file_rel
    f = np.asarray(_REF_FREQS)
    band = (f >= 250) & (f <= 12500)
    return {"ok": True, "compared_with": rows[-1]["label"],
            "file": os.path.basename(path),
            "mean_abs_diff": round(float(np.mean(np.abs(d[band]))), 2),
            "max_diff": round(float(d[np.argmax(np.abs(d))]), 2),
            "max_diff_hz": float(f[np.argmax(np.abs(d))]),
            "clean": bool(np.mean(np.abs(d[band])) < 1.0),
            "diff_db": [round(float(v), 2) for v in d]}
