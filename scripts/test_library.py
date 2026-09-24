"""The test library: real AI songs to run every fix and master against.

A fix tuned on one song can hurt the next (docs/CHAIN-AUDIT.md). This finds
the original generator exports under a folder, one per song, and runs
Shimmer's engine over all of them, so a change is judged on many songs,
styles and versions at once.

    python scripts/test_library.py build "D:/Music" --out private/test-library/library.json
    python scripts/test_library.py run private/test-library/library.json --card grain=0.5 --out grain.json
    python scripts/test_library.py run private/test-library/library.json --master cd --out master.json

build   Every folder named "suno" (any case) under the root is one song's
        originals, as the author keeps them. Its main WAV is the song
        (files in subfolders are older takes, and folders named Templates
        are skipped). The MP3 beside it, when there is one, is kept too: it
        carries the export date in its comment tag, and that date gives the
        generator version that was the default on that day (VERSIONS). With
        no date in a tag, the WAV's file date stands in ("dated": "file").
        The style is the artist for a folder under "albums" (Artist/albums/
        Album/Song/suno), else the folder above the song.
        --add merges another manifest in, such as a sample of a downloads
        archive with the version on record for each song.
run     Renders each song through core.render() and reports, per song and
        per version: for a card, how much it takes from the whole song and
        from its own band, and how often it acts; for mastering, the
        loudness reached, the true peak and the gain. A song that fails is
        reported and the run goes on.

The library names private songs, so the manifest and the results go in the
private folder (scripts/_private.py), never in the repo.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# The generator's default model by date, from its release notes and the
# first surge of posts naming each version (docs/CHAIN-AUDIT.md §2; the
# research report checked the dates against the Reddit archive).
VERSIONS = (
    ("2024-05-24", "v3.5"), ("2024-11-19", "v4"), ("2025-05-01", "v4.5"),
    ("2025-07-17", "v4.5+"), ("2025-09-23", "v5"), ("2026-03-26", "v5.5"),
    ("2026-09-09", "v6"),
)
_CREATED = re.compile(r"created=(\d{4}-\d{2}-\d{2})")


def version_on(day: Optional[str]) -> str:
    """The default version on `day` (YYYY-MM-DD), or "unknown"."""
    if not day:
        return "unknown"
    out = "unknown"
    for start, name in VERSIONS:
        if day >= start:
            out = name
    return out


def _created(mp3: str) -> Optional[str]:
    """The export date from an MP3's comment tag, or None."""
    try:
        r = subprocess.run(["ffprobe", "-v", "quiet", "-show_entries", "format_tags=comment",
                            "-of", "default=nw=1:nk=1", mp3],
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = _CREATED.search(r.stdout or "")
    return m.group(1) if m else None


def build(root: str) -> List[Dict[str, Any]]:
    songs = []
    for here, dirs, files in os.walk(root):
        if os.path.basename(here).lower() != "suno":
            continue
        dirs[:] = []                                   # older takes live below
        parent = os.path.dirname(here)
        if "templates" in os.path.basename(parent).lower():
            continue
        wavs = sorted(f for f in files if f.lower().endswith(".wav"))
        if not wavs:
            continue
        wav = wavs[0]
        stem = os.path.splitext(wav)[0]
        mp3s = sorted(f for f in files if f.lower().endswith(".mp3"))
        mp3 = next((f for f in mp3s if os.path.splitext(f)[0] == stem), mp3s[0] if mp3s else None)
        day = _created(os.path.join(here, mp3)) if mp3 else None
        dated = "tag" if day else "file"
        if not day:
            day = dt.date.fromtimestamp(os.path.getmtime(os.path.join(here, wav))).isoformat()
        parts = os.path.normpath(parent).split(os.sep)
        style = (parts[parts.index("albums") - 1] if "albums" in parts[1:]
                 else os.path.basename(os.path.dirname(parent)))
        songs.append({
            "title": os.path.basename(parent),
            "style": style,
            "wav": os.path.join(here, wav),
            "mp3": os.path.join(here, mp3) if mp3 else None,
            "created": day,
            "dated": dated,
            "version": version_on(day),
            "source": "originals",
        })
    songs.sort(key=lambda s: (s["style"], s["title"]))
    return songs


def _band(x: np.ndarray, sr: int, lo: float, hi: Optional[float]) -> np.ndarray:
    from scipy import signal as ss
    hi = min(hi or 0.45 * sr, 0.45 * sr)
    sos = ss.butter(4, [lo, hi], btype="bandpass", fs=sr, output="sos")
    return ss.sosfiltfilt(sos, np.asarray(x, dtype=np.float64), axis=0)


def _db(v: np.ndarray) -> float:
    return float(10.0 * np.log10(np.mean(np.asarray(v, dtype=np.float64) ** 2) + 1e-30))


def run_card(src, card: str, amount: float, mode: Optional[str]) -> Dict[str, Any]:
    from shimmer import core
    s = core.Settings(fixes={card: amount}, fix_modes={card: mode} if mode else {},
                      auto=False, mastering=False, preserve_volume=False)
    r = core.render(src, s, with_removed=True)
    x, rm, sr = src.at_rate(r.sr), r.removed, r.sr
    lo, hi = core.catalog.card(card).band_hz or (20.0, None)
    xb, rb = _band(x, sr, lo, hi), _band(rm, sr, lo, hi)
    # How often it acts: 50 ms frames where it takes more than 1 dB of its band.
    n = int(0.05 * sr)
    k = xb.shape[0] // n
    fx = np.mean(xb[:k * n].reshape(k, n, -1) ** 2, axis=(1, 2))
    fk = np.mean((xb - rb)[:k * n].reshape(k, n, -1) ** 2, axis=(1, 2))
    live = fx > np.max(fx) * 1e-5
    acting = float(np.mean(10 * np.log10((fx[live] + 1e-30) / (fk[live] + 1e-30)) > 1.0))
    return {"took_song_db": round(_db(rm) - _db(x), 1),
            "took_band_db": round(_db(rb) - _db(xb), 1),
            "acting_share": round(acting, 3),
            "report": r.report["fixes"].get(card)}


def run_master(src, target: str) -> Dict[str, Any]:
    from scipy import signal as ss
    from shimmer import core
    r = core.render(src, core.Settings(auto=False, mastering=True, loudness_target=target))
    y = r.audio.astype(np.float64)
    tp = 20 * np.log10(np.max(np.abs(ss.resample_poly(y, 8, 1, axis=0))) + 1e-12)
    return {"lufs": round(core.meters.loudness(y, r.sr), 2), "true_peak_dbtp": round(float(tp), 2),
            "gain_db": round(r.report["mastering"]["gain_db"], 2),
            "shaped_share": round(r.report["mastering"]["shaped_ratio"], 4)}


def summarise(rows: List[Dict[str, Any]], keys: List[str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for group in sorted({r["version"] for r in rows}) + ["all"]:
        g = [r for r in rows if "result" in r and (group == "all" or r["version"] == group)]
        if not g:
            continue
        out[group] = {"songs": len(g)}
        for k in keys:
            v = [r["result"][k] for r in g if isinstance(r["result"].get(k), (int, float))]
            if v:
                out[group][k] = {"median": round(float(np.median(v)), 3),
                                 "min": round(float(min(v)), 3), "max": round(float(max(v)), 3)}
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("root")
    b.add_argument("--add", action="append", default=[],
                   help="another manifest to merge in (its songs list)")
    b.add_argument("--out", required=True)
    r = sub.add_parser("run")
    r.add_argument("manifest")
    r.add_argument("--card", help="card=amount, e.g. grain=0.5")
    r.add_argument("--mode", help="the card's mode, e.g. vocal")
    r.add_argument("--master", help="a loudness target key: cd, loud or streaming")
    r.add_argument("--mp3", action="store_true", help="use the MP3 copy instead of the WAV")
    r.add_argument("--limit", type=int, default=0)
    r.add_argument("--only", action="append", default=[],
                   help="only songs of this version (repeat for more), e.g. v6")
    r.add_argument("--out", required=True)
    r.add_argument("--resume", action="store_true",
                   help="keep the songs already in --out and run only the rest")
    a = ap.parse_args(argv)
    # Song titles can hold any character; a console that cannot show one
    # must not stop a long run (one did, 219 songs in).
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass

    if a.cmd == "build":
        songs = build(a.root)
        for extra in a.add:
            songs += json.load(open(extra, encoding="utf-8"))["songs"]
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump({"root": a.root, "built": dt.date.today().isoformat(), "songs": songs}, f,
                      indent=1)
        by = {}
        for s in songs:
            by[s["version"]] = by.get(s["version"], 0) + 1
        print(f"{len(songs)} songs: " + ", ".join(f"{k} {v}" for k, v in sorted(by.items())))
        return 0

    from shimmer import core
    songs = json.load(open(a.manifest, encoding="utf-8"))["songs"]
    if a.only:
        songs = [s for s in songs if s["version"] in a.only]
    if a.limit:
        songs = songs[:a.limit]
    keys = (["took_song_db", "took_band_db", "acting_share"] if a.card
            else ["lufs", "true_peak_dbtp", "gain_db", "shaped_share"])
    rows = []
    if a.resume and os.path.isfile(a.out):
        rows = [r for r in json.load(open(a.out, encoding="utf-8"))["rows"] if "result" in r]
    done = {r.get("path") for r in rows}

    def save() -> Dict[str, Any]:
        out = {"args": vars(a), "rows": rows, "by_version": summarise(rows, keys)}
        tmp = a.out + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=1)
        os.replace(tmp, a.out)
        return out

    for i, s in enumerate(songs, 1):
        path = s["mp3"] if a.mp3 else s["wav"]
        if path in done:
            continue
        row = {k: s[k] for k in ("title", "style", "version")}
        row["path"] = path
        if not path:
            row["error"] = "no MP3"
            rows.append(row)
            continue
        t = time.time()
        try:
            src = core.Source.load(path)
            if a.card:
                card, _, amt = a.card.partition("=")
                row["result"] = run_card(src, card, float(amt or 0.5), a.mode)
            else:
                row["result"] = run_master(src, a.master or "cd")
        except Exception as e:  # noqa: BLE001 - one bad song must not stop the run
            row["error"] = f"{type(e).__name__}: {e}"
        row["seconds"] = round(time.time() - t, 1)
        rows.append(row)
        save()                                         # a crash keeps what is done
        print(f"[{i}/{len(songs)}] {s['version']:6s} {s['title'][:34]:34s} "
              f"{json.dumps(row.get('result', row.get('error')))[:110]}", flush=True)
    out = save()
    print(json.dumps(out["by_version"], indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
