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


def available() -> bool:
    try:
        import soundcard  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


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
    """One recording in progress. Holds a spectrum accumulator, not audio."""
    device_id: str
    label: str = ""
    frames: int = 0
    seconds: float = 0.0
    heard: float = 0.0                     # seconds above the silence floor
    peak: float = 0.0
    _acc: Optional[np.ndarray] = None      # summed band power, linear
    _n: int = 0
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
                    "error": self.error}


_ACTIVE: Optional[Capture] = None


def _run(cap: Capture) -> None:
    import soundcard as sc
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
                # Silence is not music. A paused player would otherwise pull
                # the average toward whatever the noise floor looks like.
                if rms > 10.0 ** (SILENCE_DBFS / 20.0):
                    bp = np.array(analyze_spectrum(mono, SR)["band_power_db"])
                    lin = 10.0 ** (bp / 10.0)
                    with cap._lock:
                        cap._acc = lin if cap._acc is None else cap._acc + lin
                        cap._n += 1
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
    """Stop, measure, store the curve, discard the audio."""
    global _ACTIVE
    cap = _ACTIVE
    if cap is None:
        return {"ok": False, "error": "nothing recording"}
    cap._stop.set()
    if cap._thread:
        cap._thread.join(timeout=5.0)
    _ACTIVE = None

    if cap.error:
        return {"ok": False, "error": cap.error}
    if cap._acc is None or cap._n == 0:
        return {"ok": False, "error": "no audio was heard — is the right "
                                      "device selected, and is it playing?"}
    if cap.heard < MIN_SECONDS:
        return {"ok": False, "error":
                f"only {cap.heard:.0f}s of audio heard; {MIN_SECONDS:.0f}s is "
                f"the minimum for a stable average"}

    mean_lin = cap._acc / cap._n
    rel = relative_band_levels(10.0 * np.log10(np.maximum(mean_lin, 1e-20)))
    row = {
        "label": (label or cap.label or "untitled").strip(),
        "genre": genre.strip(),
        "source": "capture",
        # Loudness is deliberately absent: playback normalisation rewrites it.
        "tone_only": True,
        "heard_seconds": round(cap.heard, 1),
        "rel_db": [round(float(v), 2) for v in rel],
    }
    lib = load()
    lib["tracks"].append(row)
    save(lib)
    return {"ok": True, "row": row, "count": len(lib["tracks"])}


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
    out: Dict[str, Any] = {"count": len(rows),
                           "bands_hz": [float(f) for f in _REF_FREQS],
                           "target_db": [round(float(v), 2) for v in _REF_DB],
                           "tracks": [{"label": r["label"],
                                       "genre": r.get("genre", ""),
                                       "heard_seconds": r.get("heard_seconds")}
                                      for r in rows]}
    if rows:
        arr = np.array([r["rel_db"] for r in rows], dtype=np.float64)
        out["median_db"] = [round(float(v), 2) for v in np.median(arr, axis=0)]
        out["p16_db"] = [round(float(v), 2) for v in np.percentile(arr, 16, axis=0)]
        out["p84_db"] = [round(float(v), 2) for v in np.percentile(arr, 84, axis=0)]
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
