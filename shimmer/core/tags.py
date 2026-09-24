"""Metadata on exports: read the source's tags, carry them through, fill the
blanks from the user's defaults, add Shimmer's provenance note, and write
everything in each container's native form.

Ported from shimmer/tags.py (1.1.1), with one fix: a RIFF INFO string's
size no longer counts its padding byte, as the RIFF format requires.

Why: a finished file should say what it is. Players, stores and DAWs read
tags, not filenames, and a pass ledger in the comment lets anyone (and
Shimmer itself) see what was done to a file without decoding its name.

Formats:
  WAV   RIFF INFO chunk (INAM, IART, IPRD, IGNR, ICRD, ICMT, ICOP, ISFT,
        ITRK) for DAWs and libsndfile tools, PLUS an ID3v2.3 "id3 " chunk
        which Windows Explorer and most players read.
  FLAC  Vorbis comments.            OGG   Vorbis comments.
  MP3   ID3v2.3, UTF-16 — the version every player and OS understands.
  M4A   iTunes atoms (ISRC as an iTunes freeform atom).
  AAC   raw ADTS has no tag container; nothing is written.

Every form is read and written by the code below, from its published
layout, so Shimmer needs no tag library.

Field names used everywhere in Shimmer (all plain strings):
  title, artist, album_artist, album, genre, year, track, comment,
  copyright, isrc, software
"""

from __future__ import annotations

import os
import re
import struct
from typing import Any, Dict, List, Optional, Tuple

from .settings import LEGACY_ALIASES, LEGACY_PRESETS

FIELDS = ("title", "artist", "album_artist", "album", "genre", "year",
          "track", "comment", "copyright", "isrc", "software")

# Shimmer's export suffixes:
#   1.x   {stem}_{preset}_{processed|removed|trimmed}_{8 hex}
#   2.0   {stem}_{processed|removed|trimmed}_{8 hex}
_SHIMMER_SUFFIX = re.compile(r"_(?:processed|removed|trimmed)_[0-9a-f]{8}$")

# Every 1.x preset key and version-named alias, from the frozen table in
# shimmer.core.settings, so a 1.x export still loses its whole suffix after
# the presets are gone (docs/ARCHITECTURE.md §19.1 item 11). Longest first,
# so `vocal_glaze_plus` is tried before `vocal_glaze`.
LEGACY_PRESET_KEYS = tuple(sorted((*LEGACY_PRESETS, *LEGACY_ALIASES), key=len, reverse=True))


# ═══════════════════════════════════════════════════════════════════════
# Names
# ═══════════════════════════════════════════════════════════════════════

def strip_shimmer_suffix(stem: str) -> str:
    """Remove every trailing Shimmer export suffix from a filename stem, so
    a second pass does not chain another one on. Both
    `song_vocal_glaze_processed_ab12cd34` (1.x) and
    `song_processed_ab12cd34` (2.0) become `song`."""
    s = stem or ""
    while True:
        m = _SHIMMER_SUFFIX.search(s)
        if not m:
            return s
        cut = m.start()
        head = s[:cut]
        for key in LEGACY_PRESET_KEYS:
            if head.endswith("_" + key):
                cut -= len(key) + 1
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


MAX_NOTE_OVERRIDES = 8   # keep one pass's note readable in a comment field


def shimmer_note(software: str, pass_label: str, preset_label: str,
                 strength: float, mastered: bool, target_lufs: Optional[float],
                 ceiling_dbtp: Optional[float], eq_bands: int = 0,
                 overrides: Optional[List[str]] = None,
                 eq_moves: Optional[List[str]] = None,
                 tone: str = "") -> str:
    """One provenance line, e.g.
    `Shimmer 1.4: pass 2, Sibilance rattle 80%, EQ 3 bands, mastered -14 LUFS / -1.0 dBTP`.

    `overrides` are the knobs moved off the preset (see
    params.preset_overrides), `eq_moves` the EQ bands as applied, and
    `tone` the mastering tone setting. They are what makes a finished
    file reproducible: without them the note names a preset the run may
    not actually have used.
    """
    parts = [f"{pass_label}, {preset_label} {int(round(strength * 100))}%"]
    if overrides:
        shown = list(overrides)[:MAX_NOTE_OVERRIDES]
        more = len(overrides) - len(shown)
        parts.append("tweaks " + "; ".join(shown) + (f"; +{more} more" if more else ""))
    if eq_moves:
        parts.append("EQ " + "; ".join(eq_moves))
    elif eq_bands:
        parts.append(f"EQ {eq_bands} band{'s' if eq_bands != 1 else ''}")
    if tone:
        parts.append(f"tone {tone}")
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
# The containers, read and written by Shimmer's own code
# ═══════════════════════════════════════════════════════════════════════
#
# Each tag form is written from its published layout, so Shimmer needs no
# tag library. Every writer changes only the tag part of the file: the
# audio bytes are copied as they are.

_ID3_TEXT = (("title", "TIT2"), ("artist", "TPE1"), ("album_artist", "TPE2"),
             ("album", "TALB"), ("genre", "TCON"), ("year", "TDRC"), ("track", "TRCK"),
             ("copyright", "TCOP"), ("isrc", "TSRC"), ("software", "TSSE"))
_VORBIS_KEYS = (("title", "TITLE"), ("artist", "ARTIST"), ("album_artist", "ALBUMARTIST"),
                ("album", "ALBUM"), ("genre", "GENRE"), ("year", "DATE"),
                ("track", "TRACKNUMBER"), ("comment", "COMMENT"), ("copyright", "COPYRIGHT"),
                ("isrc", "ISRC"), ("software", "ENCODER"))
_VORBIS_READ = {"title": "title", "artist": "artist", "albumartist": "album_artist",
                "album": "album", "genre": "genre", "date": "year", "tracknumber": "track",
                "comment": "comment", "description": "comment", "copyright": "copyright",
                "isrc": "isrc", "encoder": "software"}
_MP4_KEYS = (("title", b"\xa9nam"), ("artist", b"\xa9ART"), ("album_artist", b"aART"),
             ("album", b"\xa9alb"), ("genre", b"\xa9gen"), ("year", b"\xa9day"),
             ("comment", b"\xa9cmt"), ("copyright", b"cprt"), ("software", b"\xa9too"))
_MP4_ISRC = (b"com.apple.iTunes", b"ISRC")


def _clean_text(s: str) -> str:
    return s.replace("\x00", " ").strip()


# ── ID3v2 (MP3, and the "id3 " chunk of a WAV) ──────────────────────────

def _syncsafe(n: int) -> bytes:
    return bytes(((n >> 21) & 0x7F, (n >> 14) & 0x7F, (n >> 7) & 0x7F, n & 0x7F))


def _unsyncsafe(b: bytes) -> int:
    return (b[0] << 21) | (b[1] << 14) | (b[2] << 7) | b[3]


def _utf16(text: str) -> bytes:
    return b"\xff\xfe" + text.encode("utf-16-le")


def _id3_tag(tags: Dict[str, str], padding: int = 1024) -> bytes:
    """An ID3v2.3 tag, text in UTF-16 with a BOM: the version and encoding
    every player and Windows Explorer read."""
    frames = b""

    def frame(fid: str, body: bytes) -> bytes:
        return fid.encode("ascii") + struct.pack(">I", len(body)) + b"\x00\x00" + body

    for key, fid in _ID3_TEXT:
        if tags.get(key):
            frames += frame(fid, b"\x01" + _utf16(tags[key]))
    if tags.get("comment"):
        frames += frame("COMM", b"\x01" + b"eng" + _utf16("") + b"\x00\x00"
                        + _utf16(tags["comment"]))
    body = frames + b"\x00" * padding
    return b"ID3\x03\x00\x00" + _syncsafe(len(body)) + body


def _id3_size(blob: bytes) -> int:
    """The length of the ID3v2 tag at the start of `blob`, or 0."""
    if len(blob) < 10 or blob[:3] != b"ID3" or blob[3] not in (2, 3, 4):
        return 0
    size = 10 + _unsyncsafe(blob[6:10])
    if blob[5] & 0x10:
        size += 10                                      # a footer
    return size


def _decode_id3_text(enc: int, raw: bytes) -> str:
    try:
        if enc == 0:
            s = raw.decode("latin-1")
        elif enc == 1:
            s = raw.decode("utf-16")
        elif enc == 2:
            s = raw.decode("utf-16-be")
        else:
            s = raw.decode("utf-8")
    except UnicodeDecodeError:
        s = raw.decode("latin-1", errors="replace")
    return s.split("\x00")[0]


def _split_id3_string(enc: int, raw: bytes) -> Tuple[bytes, bytes]:
    """Split off one null-terminated string: (the string, the rest)."""
    if enc in (1, 2):
        for i in range(0, len(raw) - 1, 2):
            if raw[i:i + 2] == b"\x00\x00":
                return raw[:i], raw[i + 2:]
        return raw, b""
    i = raw.find(b"\x00")
    return (raw, b"") if i < 0 else (raw[:i], raw[i + 1:])


def _read_id3(blob: bytes) -> Dict[str, str]:
    """Shimmer fields from an ID3v2.3 or v2.4 tag at the start of `blob`."""
    out: Dict[str, str] = {}
    size = _id3_size(blob)
    if not size or blob[3] == 2:
        return out
    version, flags = blob[3], blob[5]
    body = blob[10:min(size, len(blob))]
    if flags & 0x80:                                    # unsynchronised
        body = body.replace(b"\xff\x00", b"\xff")
    pos = 0
    if flags & 0x40 and len(body) >= 4:                 # an extended header
        pos = (_unsyncsafe(body[:4]) if version == 4 else struct.unpack(">I", body[:4])[0] + 4)
    names = {fid: key for key, fid in _ID3_TEXT}
    names.update({"TYER": "year", "TDRL": "year"})
    while pos + 10 <= len(body):
        fid = body[pos:pos + 4]
        if not fid.strip(b"\x00") or not fid.isalnum():
            break
        n = (_unsyncsafe(body[pos + 4:pos + 8]) if version == 4
             else struct.unpack(">I", body[pos + 4:pos + 8])[0])
        data = body[pos + 10:pos + 10 + n]
        pos += 10 + n
        if not data:
            continue
        name = fid.decode("ascii")
        key = names.get(name)
        if key and not out.get(key):
            out[key] = _decode_id3_text(data[0], data[1:])
        elif name == "COMM" and not out.get("comment") and len(data) > 4:
            _desc, text = _split_id3_string(data[0], data[4:])
            out["comment"] = _decode_id3_text(data[0], text)
    if out.get("year"):
        out["year"] = out["year"][:4]
    return {k: v for k, v in out.items() if v}


# ── WAV: a RIFF INFO chunk and an "id3 " chunk ──────────────────────────

_INFO_MAP = (("title", b"INAM"), ("artist", b"IART"), ("album", b"IPRD"),
             ("genre", b"IGNR"), ("year", b"ICRD"), ("track", b"ITRK"),
             ("comment", b"ICMT"), ("copyright", b"ICOP"), ("software", b"ISFT"))


def _riff_chunks(blob: bytes) -> List[Tuple[bytes, bytes]]:
    """The chunks of a RIFF WAVE file after its header: (id, whole chunk)."""
    out = []
    pos, n = 12, len(blob)
    while pos + 8 <= n:
        cid = blob[pos:pos + 4]
        size = struct.unpack("<I", blob[pos + 4:pos + 8])[0]
        end = pos + 8 + size + (size & 1)
        out.append((cid, blob[pos:min(end, n)]))
        pos = end
    return out


def _info_chunk(tags: Dict[str, str]) -> bytes:
    body = b""
    for key, fourcc in _INFO_MAP:
        v = tags.get(key)
        if not v:
            continue
        data = v.encode("utf-8") + b"\x00"
        size = len(data)                  # the string and its terminator
        if size % 2:
            data += b"\x00"               # word alignment; not counted in size
        body += fourcc + struct.pack("<I", size) + data
    return b"LIST" + struct.pack("<I", 4 + len(body)) + b"INFO" + body if body else b""


def _write_wav(path: str, tags: Dict[str, str]) -> None:
    """Replace the WAV's LIST/INFO and id3 chunks, keeping every other chunk."""
    with open(path, "rb") as fh:
        blob = fh.read()
    if blob[:4] != b"RIFF" or blob[8:12] != b"WAVE":
        raise ValueError("not a RIFF WAVE file")
    kept = [chunk for cid, chunk in _riff_chunks(blob)
            if not (cid == b"LIST" and chunk[8:12] == b"INFO")
            and cid.lower() != b"id3 "]
    id3 = _id3_tag(tags, padding=0)
    id3_chunk = b"id3 " + struct.pack("<I", len(id3)) + id3 + (b"\x00" if len(id3) % 2 else b"")
    out = blob[:12] + b"".join(kept) + _info_chunk(tags) + id3_chunk
    out = out[:4] + struct.pack("<I", len(out) - 8) + out[8:]
    _replace(path, out)


def _read_wav(path: str) -> Dict[str, str]:
    with open(path, "rb") as fh:
        blob = fh.read()
    out: Dict[str, str] = {}
    if blob[:4] != b"RIFF" or blob[8:12] != b"WAVE":
        return out
    names = {fourcc: key for key, fourcc in _INFO_MAP}
    for cid, chunk in _riff_chunks(blob):
        if cid == b"LIST" and chunk[8:12] == b"INFO":
            pos = 12
            while pos + 8 <= len(chunk):
                sub = chunk[pos:pos + 4]
                size = struct.unpack("<I", chunk[pos + 4:pos + 8])[0]
                text = chunk[pos + 8:pos + 8 + size].split(b"\x00")[0]
                pos += 8 + size + (size & 1)
                if sub in names:
                    out[names[sub]] = text.decode("utf-8", errors="replace")
        elif cid.lower() == b"id3 ":
            id3 = _read_id3(chunk[8:])
            out.update(id3)                   # ID3 carries the most fields
    if out.get("year"):
        out["year"] = out["year"][:4]
    return out


# ── Vorbis comments (FLAC and OGG) ──────────────────────────────────────

def _vorbis_comment(tags: Dict[str, str], vendor: bytes) -> bytes:
    items = [f"{vk}={tags[key]}".encode("utf-8") for key, vk in _VORBIS_KEYS if tags.get(key)]
    return (struct.pack("<I", len(vendor)) + vendor + struct.pack("<I", len(items))
            + b"".join(struct.pack("<I", len(i)) + i for i in items))


def _parse_vorbis_comment(data: bytes) -> Tuple[bytes, Dict[str, str]]:
    """(vendor, Shimmer fields) from a Vorbis comment body."""
    out: Dict[str, str] = {}
    try:
        n = struct.unpack("<I", data[:4])[0]
        vendor = data[4:4 + n]
        pos = 4 + n
        count = struct.unpack("<I", data[pos:pos + 4])[0]
        pos += 4
        for _ in range(count):
            m = struct.unpack("<I", data[pos:pos + 4])[0]
            item = data[pos + 4:pos + 4 + m].decode("utf-8", errors="replace")
            pos += 4 + m
            k, _, v = item.partition("=")
            key = _VORBIS_READ.get(k.lower())
            if key and v and not out.get(key):
                out[key] = v
    except (struct.error, IndexError):
        return b"", out
    if out.get("year"):
        out["year"] = out["year"][:4]
    return vendor, out


def _flac_blocks(blob: bytes) -> Tuple[List[Tuple[int, bytes]], int]:
    """The metadata blocks of a FLAC file, (type, body), and where the audio
    starts."""
    if blob[:4] != b"fLaC":
        raise ValueError("not a FLAC file")
    pos, blocks = 4, []
    while pos + 4 <= len(blob):
        head = blob[pos]
        size = int.from_bytes(blob[pos + 1:pos + 4], "big")
        blocks.append((head & 0x7F, blob[pos + 4:pos + 4 + size]))
        pos += 4 + size
        if head & 0x80:
            break
    return blocks, pos


def _write_flac(path: str, tags: Dict[str, str]) -> None:
    with open(path, "rb") as fh:
        blob = fh.read()
    blocks, audio = _flac_blocks(blob)
    vendor = b"Shimmer"
    for t, body in blocks:
        if t == 4:
            vendor = _parse_vorbis_comment(body)[0] or vendor
    kept = [(t, b) for t, b in blocks if t not in (1, 4)]   # no old tags, no padding
    kept.append((4, _vorbis_comment(tags, vendor)))
    kept.append((1, b"\x00" * 1024))
    out = b"fLaC"
    for i, (t, body) in enumerate(kept):
        last = 0x80 if i == len(kept) - 1 else 0
        out += bytes([last | t]) + len(body).to_bytes(3, "big") + body
    _replace(path, out + blob[audio:])


def _read_flac(path: str) -> Dict[str, str]:
    with open(path, "rb") as fh:
        blob = fh.read(1 << 20)
    for t, body in _flac_blocks(blob)[0]:
        if t == 4:
            return _parse_vorbis_comment(body)[1]
    return {}


# ── OGG Vorbis: the comment header, repaginated ─────────────────────────

def _ogg_crc_table() -> List[int]:
    table = []
    for i in range(256):
        r = i << 24
        for _ in range(8):
            r = ((r << 1) ^ 0x04C11DB7) if r & 0x80000000 else (r << 1)
        table.append(r & 0xFFFFFFFF)
    return table


_OGG_CRC = _ogg_crc_table()


def _ogg_crc(page: bytes) -> int:
    crc = 0
    t = _OGG_CRC
    for b in page:
        crc = ((crc << 8) & 0xFFFFFFFF) ^ t[((crc >> 24) ^ b) & 0xFF]
    return crc


def _ogg_pages(blob: bytes):
    """Each page: (offset, header_type, granule, serial, seq, lacing, body, end)."""
    pos = 0
    while pos + 27 <= len(blob) and blob[pos:pos + 4] == b"OggS":
        htype = blob[pos + 5]
        granule, serial, seq = struct.unpack("<qII", blob[pos + 6:pos + 22])
        nseg = blob[pos + 26]
        lacing = blob[pos + 27:pos + 27 + nseg]
        start = pos + 27 + nseg
        end = start + sum(lacing)
        yield pos, htype, granule, serial, seq, lacing, blob[start:end], end
        pos = end


def _ogg_headers(blob: bytes):
    """The three Vorbis header packets, the serial, how many pages they
    take, and where the audio pages start."""
    packets, cur, pages = [], b"", 0
    serial = 0
    for pos, htype, granule, serial, seq, lacing, body, end in _ogg_pages(blob):
        pages += 1
        off = 0
        for lace in lacing:
            cur += body[off:off + lace]
            off += lace
            if lace < 255:
                packets.append(cur)
                cur = b""
        if len(packets) >= 3:
            if len(packets) > 3 or cur:
                raise ValueError("audio shares the last header page")
            return packets, serial, pages, end
    raise ValueError("not an OGG Vorbis file")


def _ogg_page(htype: int, granule: int, serial: int, seq: int, segs: List[int],
              body: bytes) -> bytes:
    head = (b"OggS\x00" + bytes([htype]) + struct.pack("<qII", granule, serial, seq)
            + b"\x00\x00\x00\x00" + bytes([len(segs)]) + bytes(segs))
    page = head + body
    return page[:22] + struct.pack("<I", _ogg_crc(page)) + page[26:]


def _paginate(packets: List[bytes], serial: int, seq: int, first_bos: bool) -> List[bytes]:
    """Pages for header packets, granule 0; a page holds up to 255 segments."""
    pages, segs, body, cont = [], [], b"", False
    lace: List[Tuple[int, bytes]] = []
    for p in packets:
        n = len(p)
        for i in range(n // 255):
            lace.append((255, p[i * 255:(i + 1) * 255]))
        lace.append((n % 255, p[(n // 255) * 255:]))
    for size, chunk in lace:
        segs.append(size)
        body += chunk
        if len(segs) == 255:
            htype = (0x02 if first_bos and not pages else 0) | (0x01 if cont else 0)
            pages.append(_ogg_page(htype, 0, serial, seq + len(pages), segs, body))
            cont = size == 255
            segs, body = [], b""
    if segs:
        htype = (0x02 if first_bos and not pages else 0) | (0x01 if cont else 0)
        pages.append(_ogg_page(htype, 0, serial, seq + len(pages), segs, body))
    return pages


def _write_ogg(path: str, tags: Dict[str, str]) -> None:
    with open(path, "rb") as fh:
        blob = fh.read()
    packets, serial, old_pages, audio = _ogg_headers(blob)
    ident, comment, setup = packets
    if not comment.startswith(b"\x03vorbis"):
        raise ValueError("not an OGG Vorbis file")
    vendor = _parse_vorbis_comment(comment[7:])[0] or b"Shimmer"
    new_comment = b"\x03vorbis" + _vorbis_comment(tags, vendor) + b"\x01"
    # The identification header sits alone on the first page (the Vorbis
    # spec); the comment and setup headers follow, and end their page.
    head = _paginate([ident], serial, 0, True) + _paginate([new_comment, setup], serial, 1, False)
    rest = blob[audio:]
    shift = len(head) - old_pages
    if shift:
        # Later pages keep their audio but take new sequence numbers.
        out = []
        for pos, htype, granule, ser, seq, lacing, body, end in _ogg_pages(rest):
            out.append(_ogg_page(htype, granule, ser, seq + shift, list(lacing), body))
        rest = b"".join(out)
    _replace(path, b"".join(head) + rest)


def _read_ogg(path: str) -> Dict[str, str]:
    with open(path, "rb") as fh:
        blob = fh.read(1 << 20)
    comment = _ogg_headers(blob)[0][1]
    if not comment.startswith(b"\x03vorbis"):
        return {}
    return _parse_vorbis_comment(comment[7:])[1]


# ── M4A: the iTunes item list (moov/udta/meta/ilst) ─────────────────────

def _atoms(blob: bytes, start: int = 0, end: Optional[int] = None):
    """Each atom in blob[start:end]: (type, offset, header size, total size)."""
    end = len(blob) if end is None else end
    pos = start
    while pos + 8 <= end:
        size, kind = struct.unpack(">I4s", blob[pos:pos + 8])
        head = 8
        if size == 1:
            size = struct.unpack(">Q", blob[pos + 8:pos + 16])[0]
            head = 16
        elif size == 0:
            size = end - pos
        if size < head or pos + size > end:
            break
        yield kind, pos, head, size
        pos += size


def _atom(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", 8 + len(body)) + kind + body


def _child(blob: bytes, parent: Tuple[bytes, int, int, int], kind: bytes,
           skip: int = 0) -> Optional[Tuple[bytes, int, int, int]]:
    _, pos, head, size = parent
    for a in _atoms(blob, pos + head + skip, pos + size):
        if a[0] == kind:
            return a
    return None


def _mp4_item(key: bytes, payload: bytes, flags: int = 1) -> bytes:
    return _atom(key, _atom(b"data", struct.pack(">II", flags, 0) + payload))


def _ilst(tags: Dict[str, str], keep: bytes) -> bytes:
    body = keep
    for key, atom in _MP4_KEYS:
        if tags.get(key):
            body += _mp4_item(atom, tags[key].encode("utf-8"))
    m = re.match(r"\s*(\d+)(?:\s*/\s*(\d+))?", tags.get("track") or "")
    if m:
        body += _mp4_item(b"trkn", struct.pack(">HHHH", 0, int(m.group(1)) & 0xFFFF,
                                               int(m.group(2) or 0) & 0xFFFF, 0), flags=0)
    if tags.get("isrc"):
        body += _atom(b"----", _atom(b"mean", b"\x00" * 4 + _MP4_ISRC[0])
                      + _atom(b"name", b"\x00" * 4 + _MP4_ISRC[1])
                      + _atom(b"data", struct.pack(">II", 1, 0) + tags["isrc"].encode("utf-8")))
    return _atom(b"ilst", body)


def _freeform_name(blob: bytes, item: Tuple[bytes, int, int, int]) -> Tuple[bytes, bytes]:
    mean = _child(blob, item, b"mean")
    name = _child(blob, item, b"name")
    get = (lambda a: blob[a[1] + a[2] + 4:a[1] + a[3]] if a else b"")
    return get(mean), get(name)


def _write_m4a(path: str, tags: Dict[str, str]) -> None:
    with open(path, "rb") as fh:
        blob = fh.read()
    top = list(_atoms(blob))
    moov = next((a for a in top if a[0] == b"moov"), None)
    if moov is None:
        raise ValueError("not an M4A file")
    if moov is not top[-1]:
        # With the movie header before the audio, a bigger header would move
        # the audio and break its offsets. Shimmer's own M4A files end with it.
        raise ValueError("the file's header is not at its end")
    managed = {atom for _, atom in _MP4_KEYS} | {b"trkn"}
    keep = b""
    udta = _child(blob, moov, b"udta")
    meta = _child(blob, udta, b"meta") if udta else None
    ilst = _child(blob, meta, b"ilst", skip=4) if meta else None
    if ilst:
        for item in _atoms(blob, ilst[1] + ilst[2], ilst[1] + ilst[3]):
            if item[0] in managed:
                continue
            if item[0] == b"----" and _freeform_name(blob, item) == _MP4_ISRC:
                continue
            keep += blob[item[1]:item[1] + item[3]]
    hdlr = _atom(b"hdlr", b"\x00" * 8 + b"mdir" + b"appl" + b"\x00" * 9)
    meta_body = b"\x00" * 4 + hdlr + _ilst(tags, keep)
    if meta:
        for a in _atoms(blob, meta[1] + meta[2] + 4, meta[1] + meta[3]):
            if a[0] not in (b"hdlr", b"ilst"):
                meta_body += blob[a[1]:a[1] + a[3]]
    udta_body = _atom(b"meta", meta_body)
    if udta:
        for a in _atoms(blob, udta[1] + udta[2], udta[1] + udta[3]):
            if a[0] != b"meta":
                udta_body += blob[a[1]:a[1] + a[3]]
    moov_body = b""
    for a in _atoms(blob, moov[1] + moov[2], moov[1] + moov[3]):
        if a[0] != b"udta":
            moov_body += blob[a[1]:a[1] + a[3]]
    moov_body += _atom(b"udta", udta_body)
    _replace(path, blob[:moov[1]] + _atom(b"moov", moov_body))


def _read_m4a(path: str) -> Dict[str, str]:
    with open(path, "rb") as fh:
        blob = fh.read()
    out: Dict[str, str] = {}
    moov = next((a for a in _atoms(blob) if a[0] == b"moov"), None)
    udta = _child(blob, moov, b"udta") if moov else None
    meta = _child(blob, udta, b"meta") if udta else None
    ilst = _child(blob, meta, b"ilst", skip=4) if meta else None
    if not ilst:
        return out
    names = {atom: key for key, atom in _MP4_KEYS}
    for item in _atoms(blob, ilst[1] + ilst[2], ilst[1] + ilst[3]):
        data = _child(blob, item, b"data")
        if not data:
            continue
        payload = blob[data[1] + data[2] + 8:data[1] + data[3]]
        if item[0] in names:
            out[names[item[0]]] = payload.decode("utf-8", errors="replace")
        elif item[0] == b"trkn" and len(payload) >= 6:
            n, total = struct.unpack(">HH", payload[2:6])
            out["track"] = f"{n}/{total}" if total else str(n)
        elif item[0] == b"----" and _freeform_name(blob, item) == _MP4_ISRC:
            out["isrc"] = payload.decode("utf-8", errors="replace")
    if out.get("year"):
        out["year"] = out["year"][:4]
    return out


# ── MP3 ─────────────────────────────────────────────────────────────────

def _write_mp3(path: str, tags: Dict[str, str]) -> None:
    with open(path, "rb") as fh:
        blob = fh.read()
    _replace(path, _id3_tag(tags) + blob[_id3_size(blob):])


def _read_mp3(path: str) -> Dict[str, str]:
    with open(path, "rb") as fh:
        head = fh.read(10)
        size = _id3_size(head)
        return _read_id3(head + fh.read(max(0, size - 10))) if size else {}


def _replace(path: str, data: bytes) -> None:
    """Write `data` over `path` whole: a new file, then a rename."""
    tmp = path + ".tagging"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, path)


_READERS = {".wav": _read_wav, ".flac": _read_flac, ".ogg": _read_ogg, ".mp3": _read_mp3,
            ".m4a": _read_m4a, ".mp4": _read_m4a}
_WRITERS = {".wav": (_write_wav, "RIFF INFO + ID3v2.3"), ".flac": (_write_flac, "Vorbis comments"),
            ".ogg": (_write_ogg, "Vorbis comments"), ".mp3": (_write_mp3, "ID3v2.3"),
            ".m4a": (_write_m4a, "iTunes atoms"), ".mp4": (_write_m4a, "iTunes atoms")}


def read_tags(path: str) -> Dict[str, str]:
    """Tags of an audio file as Shimmer fields. Missing or unreadable tags
    give an empty dict; this never raises."""
    reader = _READERS.get(os.path.splitext(path)[1].lower())
    out: Dict[str, str] = {}
    if reader is not None:
        try:
            out = reader(path)
        except Exception:  # noqa: BLE001
            out = {}
    return {k: _clean_text(v) for k, v in out.items() if isinstance(v, str) and v.strip()}


def write_tags(path: str, tags: Dict[str, str]) -> Dict[str, Any]:
    """Write `tags` to the file at `path` in its native form. Returns a
    small report: {"written": bool, "form": str, "fields": [...]}."""
    ext = os.path.splitext(path)[1].lower()
    clean = {k: str(v).strip() for k, v in (tags or {}).items()
             if k in FIELDS and v is not None and str(v).strip()}
    if not clean:
        return {"written": False, "form": "", "fields": []}
    if ext not in _WRITERS:
        return {"written": False, "form": "", "fields": [],
                "reason": f"{ext or 'this format'} has no tag container"}
    write, form = _WRITERS[ext]
    try:
        write(path, clean)
    except Exception as e:  # noqa: BLE001
        return {"written": False, "form": "", "fields": [], "reason": str(e)}
    return {"written": True, "form": form, "fields": sorted(clean)}
