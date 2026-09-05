"""
tags.py — Metadata on exports: read the source's tags, carry them through,
fill the blanks from the user's defaults, add Shimmer's provenance note,
and write everything in each container's native form.

Why: a finished file should say what it is. Players, stores and DAWs read
tags, not filenames, and a pass ledger in the comment lets anyone (and
Shimmer itself) see what was done to a file without decoding its name.

Formats:
  WAV   RIFF INFO chunk (INAM, IART, IPRD, IGNR, ICRD, ICMT, ICOP, ISFT,
        ITRK) for DAWs and libsndfile tools, PLUS an ID3v2.3 "id3 " chunk
        (mutagen.wave) which Windows Explorer and most players read.
  FLAC  Vorbis comments.            OGG   Vorbis comments.
  MP3   ID3v2.3, UTF-16 — the version every player and OS understands.
  M4A   iTunes atoms (ISRC as an iTunes freeform atom).
  AAC   raw ADTS has no tag container; nothing is written.

Field names used everywhere in Shimmer (all plain strings):
  title, artist, album_artist, album, genre, year, track, comment,
  copyright, isrc, software
"""

from __future__ import annotations

import os
import re
import struct
from typing import Any, Dict, List, Optional

FIELDS = ("title", "artist", "album_artist", "album", "genre", "year",
          "track", "comment", "copyright", "isrc", "software")

# Shimmer's export suffix: {stem}_{preset}_{processed|trimmed}_{8 hex}
_SHIMMER_SUFFIX = re.compile(r"_[a-z0-9_]+?_(?:processed|trimmed)_[0-9a-f]{8}$")


def _known_presets() -> List[str]:
    try:
        from .presets import list_presets
        return sorted((str(k) for k in list_presets()), key=len, reverse=True)
    except Exception:  # noqa: BLE001
        return []


# ═══════════════════════════════════════════════════════════════════════
# Names
# ═══════════════════════════════════════════════════════════════════════

def strip_shimmer_suffix(stem: str) -> str:
    """Remove every trailing Shimmer export suffix from a filename stem, so
    a second pass does not chain another one on: `song_glaze_processed_ab12cd34`
    becomes `song`."""
    s = stem or ""
    presets = _known_presets()
    while True:
        m = _SHIMMER_SUFFIX.search(s)
        if not m:
            return s
        # The preset name is the shortest match; prefer the longest known
        # preset key so `my_song_generic_processed_x` keeps `my_song`.
        tail = s[m.start():]
        cut = m.start()
        for key in presets:
            marker = f"_{key}_"
            i = s.rfind(marker)
            if i >= 0 and i + len(marker) <= len(s) and re.match(
                    r"(?:processed|trimmed)_[0-9a-f]{8}$", s[i + len(marker):]):
                cut = i
                break
        s = s[:cut]


def title_from_stem(stem: str) -> str:
    """A readable title from a filename stem: suffixes off, underscores to
    spaces, doubled spaces collapsed."""
    s = strip_shimmer_suffix(stem or "")
    s = s.replace("_", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


# ═══════════════════════════════════════════════════════════════════════
# Reading
# ═══════════════════════════════════════════════════════════════════════

def _first(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, (list, tuple)):
        return _first(v[0]) if v else ""
    if hasattr(v, "text"):
        t = v.text
        return _first(t) if isinstance(t, (list, tuple)) else str(t)
    return str(v)


def _read_id3(tags: Any) -> Dict[str, str]:
    """ID3 frames (mutagen.id3.ID3) to Shimmer fields."""
    out: Dict[str, str] = {}
    if not tags:
        return out
    frame_map = {
        "TIT2": "title", "TPE1": "artist", "TPE2": "album_artist", "TALB": "album",
        "TCON": "genre", "TRCK": "track", "TCOP": "copyright", "TSRC": "isrc",
        "TSSE": "software",
    }
    for fid, key in frame_map.items():
        fr = tags.get(fid)
        if fr is not None:
            out[key] = _first(fr)
    for fid in ("TDRC", "TYER", "TDRL"):
        fr = tags.get(fid)
        if fr is not None and not out.get("year"):
            out["year"] = _first(fr)[:4]
    comms = tags.getall("COMM") if hasattr(tags, "getall") else []
    for c in comms:
        txt = _first(c)
        if txt:
            out["comment"] = txt
            break
    return {k: v for k, v in out.items() if v}


def _read_vorbis(tags: Any) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not tags:
        return out
    key_map = {
        "title": "title", "artist": "artist", "albumartist": "album_artist",
        "album": "album", "genre": "genre", "date": "year", "tracknumber": "track",
        "comment": "comment", "description": "comment", "copyright": "copyright",
        "isrc": "isrc", "encoder": "software",
    }
    for k, key in key_map.items():
        v = tags.get(k)
        if v and not out.get(key):
            out[key] = _first(v)
    if out.get("year"):
        out["year"] = out["year"][:4]
    return out


def _read_mp4(tags: Any) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not tags:
        return out
    key_map = {
        "\xa9nam": "title", "\xa9ART": "artist", "aART": "album_artist",
        "\xa9alb": "album", "\xa9gen": "genre", "\xa9day": "year",
        "\xa9cmt": "comment", "cprt": "copyright", "\xa9too": "software",
        "----:com.apple.iTunes:ISRC": "isrc",
    }
    for k, key in key_map.items():
        v = tags.get(k)
        if v:
            s = v[0]
            if isinstance(s, bytes):
                s = s.decode("utf-8", errors="replace")
            out[key] = str(s)
    trk = tags.get("trkn")
    if trk:
        try:
            n, total = trk[0]
            out["track"] = f"{n}/{total}" if total else str(n)
        except (TypeError, ValueError):
            pass
    if out.get("year"):
        out["year"] = out["year"][:4]
    return out


def _read_riff_info(path: str) -> Dict[str, str]:
    """RIFF LIST/INFO strings from a WAV (libsndfile via soundfile)."""
    try:
        import soundfile as sf
        with sf.SoundFile(path) as f:
            keys = {"title": "title", "artist": "artist", "album": "album",
                    "genre": "genre", "date": "year", "tracknumber": "track",
                    "comment": "comment", "copyright": "copyright",
                    "software": "software"}
            out = {}
            for attr, key in keys.items():
                try:
                    v = getattr(f, attr)
                except Exception:  # noqa: BLE001
                    v = ""
                if v:
                    out[key] = str(v)[:4] if key == "year" else str(v)
            return out
    except Exception:  # noqa: BLE001
        return {}


def read_tags(path: str) -> Dict[str, str]:
    """Tags of an audio file as Shimmer fields. Missing or unreadable tags
    give an empty dict; this never raises."""
    ext = os.path.splitext(path)[1].lower()
    out: Dict[str, str] = {}
    try:
        import mutagen
        from mutagen.flac import FLAC
        from mutagen.mp4 import MP4
        from mutagen.oggvorbis import OggVorbis
        from mutagen.wave import WAVE
        if ext == ".wav":
            out.update(_read_riff_info(path))
            try:
                w = WAVE(path)
                out.update(_read_id3(w.tags))
            except Exception:  # noqa: BLE001
                pass
        elif ext == ".flac":
            out.update(_read_vorbis(FLAC(path).tags))
        elif ext == ".ogg":
            out.update(_read_vorbis(OggVorbis(path).tags))
        elif ext in (".m4a", ".mp4"):
            out.update(_read_mp4(MP4(path).tags))
        elif ext == ".mp3":
            f = mutagen.File(path)
            out.update(_read_id3(getattr(f, "tags", None)))
        else:
            f = mutagen.File(path)
            t = getattr(f, "tags", None)
            if t is not None:
                out.update(_read_vorbis(t) if hasattr(t, "get") and not hasattr(t, "getall") else _read_id3(t))
    except Exception:  # noqa: BLE001
        pass
    return {k: v.strip() for k, v in out.items() if isinstance(v, str) and v.strip()}


# ═══════════════════════════════════════════════════════════════════════
# Building the export's tags
# ═══════════════════════════════════════════════════════════════════════

def build_tags(source: Optional[Dict[str, str]], defaults: Optional[Dict[str, Any]],
               title_hint: str = "", note: str = "",
               software: str = "Shimmer") -> Dict[str, str]:
    """Merge the source's tags with the user's defaults.

    `defaults` may carry: title, artist, album_artist, album, genre, year,
    track, copyright, isrc, plus `mode` ("fill": the file's own tags win,
    the defaults fill blanks; "overwrite": the defaults win where set) and
    `notes` (bool, default True: add Shimmer's note to the comment).
    A `title` in defaults is a per-file entry and always wins when given.
    """
    src = dict(source or {})
    d = dict(defaults or {})
    overwrite = str(d.get("mode", "fill")).lower() == "overwrite"

    def pick(key: str) -> str:
        user = str(d.get(key) or "").strip()
        own = str(src.get(key) or "").strip()
        if overwrite:
            return user or own
        return own or user

    out: Dict[str, str] = {}
    title = str(d.get("title") or "").strip() or str(src.get("title") or "").strip() \
        or title_from_stem(title_hint)
    if title:
        out["title"] = title
    for key in ("artist", "album", "genre", "year", "track", "copyright", "isrc"):
        v = pick(key)
        if v:
            out[key] = v
    album_artist = pick("album_artist") or out.get("artist", "")
    if album_artist:
        out["album_artist"] = album_artist
    if out.get("year"):
        out["year"] = re.sub(r"[^0-9]", "", out["year"])[:4]
    if not out.get("copyright") and out.get("artist") and out.get("year"):
        out["copyright"] = f"© {out['year']} {out['artist']}"

    # Comment: the source's own lines stay; Shimmer's note is appended once.
    lines: List[str] = []
    own_comment = str(src.get("comment") or "").strip()
    if own_comment:
        lines.extend(ln for ln in own_comment.splitlines() if ln.strip())
    user_comment = str(d.get("comment") or "").strip()
    if user_comment and user_comment not in lines:
        lines.append(user_comment)
    if note and d.get("notes", True):
        lines = [ln for ln in lines if ln.strip() != note.strip()]
        lines.append(note.strip())
    if lines:
        out["comment"] = "\n".join(lines)
    out["software"] = software
    return out


def shimmer_note(software: str, pass_label: str, preset_label: str,
                 strength: float, mastered: bool, target_lufs: Optional[float],
                 ceiling_dbtp: Optional[float], eq_bands: int = 0) -> str:
    """One provenance line, e.g.
    `Shimmer 1.4: pass 2, Sibilance rattle 80%, EQ 3 bands, mastered -14 LUFS / -1.0 dBTP`."""
    parts = [f"{pass_label}, {preset_label} {int(round(strength * 100))}%"]
    if eq_bands:
        parts.append(f"EQ {eq_bands} band{'s' if eq_bands != 1 else ''}")
    if mastered:
        m = "mastered"
        if target_lufs is not None:
            m += f" {target_lufs:g} LUFS"
        if ceiling_dbtp is not None:
            m += f" / {ceiling_dbtp:g} dBTP"
        parts.append(m)
    else:
        parts.append("cleaning only")
    return f"{software}: " + ", ".join(parts)


# ═══════════════════════════════════════════════════════════════════════
# Writing
# ═══════════════════════════════════════════════════════════════════════

def _write_riff_info(path: str, tags: Dict[str, str]) -> None:
    """Replace (or add) the LIST/INFO chunk of a RIFF WAV in place."""
    info_map = [("title", b"INAM"), ("artist", b"IART"), ("album", b"IPRD"),
                ("genre", b"IGNR"), ("year", b"ICRD"), ("track", b"ITRK"),
                ("comment", b"ICMT"), ("copyright", b"ICOP"), ("software", b"ISFT")]
    body = b""
    for key, fourcc in info_map:
        v = tags.get(key)
        if not v:
            continue
        data = v.encode("utf-8") + b"\x00"
        if len(data) % 2:
            data += b"\x00"
        body += fourcc + struct.pack("<I", len(data) - (1 if len(data) % 2 == 0 and v.encode("utf-8")[-1:] != b"\x00" and False else 0)) + data
    if not body:
        return
    new_chunk = b"LIST" + struct.pack("<I", 4 + len(body)) + b"INFO" + body

    with open(path, "rb") as fh:
        blob = fh.read()
    if blob[:4] != b"RIFF" or blob[8:12] != b"WAVE":
        return
    # Walk the chunks, dropping any existing LIST/INFO.
    pos = 12
    kept = [blob[:12]]
    n = len(blob)
    while pos + 8 <= n:
        cid = blob[pos:pos + 4]
        size = struct.unpack("<I", blob[pos + 4:pos + 8])[0]
        end = pos + 8 + size + (size & 1)
        chunk = blob[pos:min(end, n)]
        if not (cid == b"LIST" and blob[pos + 8:pos + 12] == b"INFO"):
            kept.append(chunk)
        pos = end
    out = b"".join(kept) + new_chunk
    out = out[:4] + struct.pack("<I", len(out) - 8) + out[8:]
    with open(path, "wb") as fh:
        fh.write(out)


def _id3_frames(tags: Dict[str, str]):
    from mutagen.id3 import (
        COMM, TALB, TCON, TCOP, TDRC, TIT2, TPE1, TPE2, TRCK, TSRC, TSSE,
    )
    enc = 1  # UTF-16 with BOM: readable by Windows Explorer and old players
    frames = []
    if tags.get("title"):
        frames.append(TIT2(encoding=enc, text=[tags["title"]]))
    if tags.get("artist"):
        frames.append(TPE1(encoding=enc, text=[tags["artist"]]))
    if tags.get("album_artist"):
        frames.append(TPE2(encoding=enc, text=[tags["album_artist"]]))
    if tags.get("album"):
        frames.append(TALB(encoding=enc, text=[tags["album"]]))
    if tags.get("genre"):
        frames.append(TCON(encoding=enc, text=[tags["genre"]]))
    if tags.get("year"):
        frames.append(TDRC(encoding=enc, text=[tags["year"]]))
    if tags.get("track"):
        frames.append(TRCK(encoding=enc, text=[tags["track"]]))
    if tags.get("copyright"):
        frames.append(TCOP(encoding=enc, text=[tags["copyright"]]))
    if tags.get("isrc"):
        frames.append(TSRC(encoding=enc, text=[tags["isrc"]]))
    if tags.get("software"):
        frames.append(TSSE(encoding=enc, text=[tags["software"]]))
    if tags.get("comment"):
        frames.append(COMM(encoding=enc, lang="eng", desc="", text=[tags["comment"]]))
    return frames


def _write_id3_into(container, tags: Dict[str, str]) -> None:
    if container.tags is None:
        container.add_tags()
    t = container.tags
    for fid in ("TIT2", "TPE1", "TPE2", "TALB", "TCON", "TDRC", "TYER", "TRCK",
                "TCOP", "TSRC", "TSSE", "COMM"):
        t.delall(fid)
    for fr in _id3_frames(tags):
        t.add(fr)
    container.save(v2_version=3)


def _write_vorbis(container, tags: Dict[str, str]) -> None:
    if container.tags is None:
        container.add_tags()
    key_map = {"title": "TITLE", "artist": "ARTIST", "album_artist": "ALBUMARTIST",
               "album": "ALBUM", "genre": "GENRE", "year": "DATE", "track": "TRACKNUMBER",
               "comment": "COMMENT", "copyright": "COPYRIGHT", "isrc": "ISRC",
               "software": "ENCODER"}
    for key, vk in key_map.items():
        v = tags.get(key)
        if v:
            container.tags[vk] = [v]
        elif vk in container.tags:
            del container.tags[vk]
    container.save()


def _write_mp4(container, tags: Dict[str, str]) -> None:
    from mutagen.mp4 import MP4FreeForm
    if container.tags is None:
        container.add_tags()
    t = container.tags
    key_map = {"title": "\xa9nam", "artist": "\xa9ART", "album_artist": "aART",
               "album": "\xa9alb", "genre": "\xa9gen", "year": "\xa9day",
               "comment": "\xa9cmt", "copyright": "cprt", "software": "\xa9too"}
    for key, ak in key_map.items():
        v = tags.get(key)
        if v:
            t[ak] = [v]
        elif ak in t:
            del t[ak]
    if tags.get("track"):
        m = re.match(r"\s*(\d+)(?:\s*/\s*(\d+))?", tags["track"])
        if m:
            t["trkn"] = [(int(m.group(1)), int(m.group(2) or 0))]
    if tags.get("isrc"):
        t["----:com.apple.iTunes:ISRC"] = [MP4FreeForm(tags["isrc"].encode("utf-8"))]
    container.save()


def write_tags(path: str, tags: Dict[str, str]) -> Dict[str, Any]:
    """Write `tags` to the file at `path` in its native form. Returns a
    small report: {"written": bool, "form": str, "fields": [...]}."""
    ext = os.path.splitext(path)[1].lower()
    clean = {k: str(v).strip() for k, v in (tags or {}).items()
             if k in FIELDS and v is not None and str(v).strip()}
    if not clean:
        return {"written": False, "form": "", "fields": []}
    try:
        if ext == ".wav":
            from mutagen.wave import WAVE
            _write_riff_info(path, clean)
            _write_id3_into(WAVE(path), clean)
            form = "RIFF INFO + ID3v2.3"
        elif ext == ".flac":
            from mutagen.flac import FLAC
            _write_vorbis(FLAC(path), clean)
            form = "Vorbis comments"
        elif ext == ".ogg":
            from mutagen.oggvorbis import OggVorbis
            _write_vorbis(OggVorbis(path), clean)
            form = "Vorbis comments"
        elif ext == ".mp3":
            from mutagen.mp3 import MP3
            _write_id3_into(MP3(path), clean)
            form = "ID3v2.3"
        elif ext in (".m4a", ".mp4"):
            from mutagen.mp4 import MP4
            _write_mp4(MP4(path), clean)
            form = "iTunes atoms"
        else:
            return {"written": False, "form": "", "fields": [],
                    "reason": f"{ext or 'this format'} has no tag container"}
    except Exception as e:  # noqa: BLE001
        return {"written": False, "form": "", "fields": [], "reason": str(e)}
    return {"written": True, "form": form, "fields": sorted(clean)}
