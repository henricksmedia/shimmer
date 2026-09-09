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
            self._acc, self._n, self.heard = None, 0, 0.0
        if acc is None or n == 0 or heard < MIN_SECONDS:
            return None            # too short to be a stable average
        rel = relative_band_levels(
            10.0 * np.log10(np.maximum(acc / n, 1e-20)))
        lib = load()
        lib["tracks"].append({
            "label": (name or "untitled").strip(),
            "genre": "",
            "source": "capture",
            "tone_only": True,
            "heard_seconds": round(heard, 1),
            "rel_db": [round(float(v), 2) for v in rel],
        })
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
    out: Dict[str, Any] = {"count": s["count"], "bands_hz": s["bands_hz"],
                           "target_db": s["target_db"], "caveats": [], "rows": []}
    if s["count"] == 0:
        out["headline"] = "Nothing captured yet."
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
    out["presence_mean_diff"] = round(float(diff[band].mean()), 2)
    # Search only where the report shows values. The 31.5 and 40 Hz bands sit
    # below most program material, so a track with nothing there produces a
    # meaningless outlier that would otherwise be reported as the headline.
    shown = (f >= 50) & (f <= 20000)
    j = int(np.arange(len(f))[shown][np.argmax(np.abs(diff[shown]))])
    out["worst_band_hz"] = float(f[j])
    out["worst_diff"] = round(float(diff[j]), 2)
    out["slope_captured"] = round(_slope(f, med, 4000.0, 16000.0), 2)
    out["slope_target"] = round(_slope(f, tgt, 4000.0, 16000.0), 2)

    d = out["presence_mean_diff"]
    if abs(d) < 1.5:
        out["headline"] = ("The captured music agrees with the tone target "
                           f"({d:+.1f} dB mean across 2.5-12.5 kHz).")
        out["verdict"] = "agrees"
    else:
        direction = "darker" if d < 0 else "brighter"
        out["headline"] = (
            f"The captured music is {abs(d):.1f} dB {direction} than the tone "
            f"target across 2.5-12.5 kHz. If that holds up, the target does "
            f"not describe commercial music.")
        out["verdict"] = "disagrees"

    # A large disagreement is more likely to be a measurement fault than a
    # discovery, so the things that would cause one are listed before it is
    # believed.
    if out["verdict"] == "disagrees":
        out["caveats"] = [
            "System audio effects. Realtek, NVIDIA or Windows 'Audio "
            "enhancements' colour everything captured. Turn them off and "
            "recapture one track to check.",
            "The player's own equaliser. Spotify has one, and it is easy to "
            "leave on by accident.",
            "Lossy streaming. Ogg Vorbis rolls off the very top, which "
            "explains 16 kHz and above but not the presence band.",
            "The verification test below settles all three at once.",
        ]
    if s["count"] < 20:
        out["caveats"].append(
            f"Only {s['count']} tracks. The spread between them is already "
            f"{spread[(f >= 4000) & (f <= 10000)].mean():.1f} dB in the "
            f"presence band, so the median will move as more arrive.")
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
