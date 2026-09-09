"""
corpus_check.py — Is the reference corpus what it says it is?

Why this exists. A file named as a reference master turned out not to be one.
Measured, it read +0.49 dB at 800 Hz; the genuine file reads -4.02. That is a
4.5 dB swing on the single most consistent measurement in the corpus, and it
would have been folded into an 8-of-8 finding as a counter-example. Nothing
about the file looked or sounded wrong. Its metadata gave it away: mastering
services stamp their output, and that file carried no stamp at all.

So the corpus needs checking, and checking it has to be automatic — a rule
that depends on someone remembering is the rule that let the file in.

Every measurement script calls `require_valid_corpus()` before it measures
anything, and refuses to run on a corpus that fails. The point is not to have
a validator; it is that you cannot take a measurement without one having run.

What gets checked, and what each catches:

  provenance   A reference master must identify itself. Mastering services
               stamp their exports; a generated render carries its model and
               track id. A file that claims to be a reference and cannot
               prove it is the exact failure above.
  pairing      Every master needs its source, or the "what did this chain do"
               measurement has nothing to subtract.
  identity     The pair must be the same performance (correlation on a common
               excerpt). Catches the right filename holding the wrong take —
               which tags alone cannot see.
  shape        Same duration and sample rate across a set.
  duplicates   Two names, one file. Catches a copy that never happened.
  manifest     Content hashes, so a file changing under a held-out test is
               detectable. A held-out set that can silently change is not
               held out.

Usage:
    python scripts/corpus_check.py              # report on sources/
    python scripts/corpus_check.py --freeze      # write the manifest
    python scripts/corpus_check.py --verify      # check against the manifest
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shimmer.audio_io import load_audio            # noqa: E402
from shimmer.tags import read_tags                 # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCES = os.path.join(ROOT, "sources")
MANIFEST = os.path.join(ROOT, "sources", "CORPUS.json")

# How each role proves it is what it claims. A role with no marker can still
# be used, but it is reported as unverified rather than silently trusted.
#
# `markers` are literal substrings that appear in a file's own metadata. They
# are a technical fact about how tools stamp their exports, held here as data
# so the check is a lookup rather than an opinion about anyone's product.
# Add a marker when a new generator or mastering service enters the corpus.
#
# `aliases` are filename prefixes accepted for the role, so an existing
# corpus does not have to be renamed to be validated.
ROLES = {
    "source": {
        "label": "AI source render",
        "aliases": ["suno", "udio", "source"],
        "markers": ["suno", "udio"],
        "required": False,   # older renders predate the tag
    },
    "reference": {
        "label": "reference master",
        "aliases": ["reference", "distrokid", "ref", "masters", "master"],
        "markers": ["mixea", "distrokid", "landr", "emastered"],
        "required": True,    # an unverified reference is what caused this file
    },
    "shimmer": {
        "label": "Shimmer master",
        "aliases": ["shimmer"],
        "markers": ["shimmer"],
        "required": False,   # exports before 2026-09-05 carry no tags
    },
}

# filename prefix -> role
_ALIAS_TO_ROLE = {a: r for r, spec in ROLES.items() for a in spec["aliases"]}


# A mastering service often stamps its settings into the filename, e.g.
# `Mixea_MediumBright_hd_Song Name.wav`. Two things follow: the song stem has
# to be recovered to pair the file with its source, and the settings are worth
# keeping — a reference mastered on a "bright" preset is not the same yardstick
# as one mastered flat, and reading the corpus without knowing which is how you
# end up measuring a user's taste and calling it a house curve.
_SETTINGS_PREFIX = re.compile(
    r"^(?P<service>mixea|landr|emastered)[_\- ]+"
    r"(?P<settings>[A-Za-z0-9]+)(?:[_\- ]+(?P<quality>hd|sd|lossless))?[_\- ]+",
    re.I)


def split_settings(filename: str):
    """`Mixea_MediumBright_hd_Song.wav` -> ('Song', {service, settings, ...})"""
    base = os.path.splitext(filename)[0]
    m = _SETTINGS_PREFIX.match(base)
    if not m:
        return base, {}
    meta = {k: v for k, v in m.groupdict().items() if v}
    return base[m.end():], meta


def _base_role(role: str) -> str:
    """`shimmer 1` -> `shimmer`. An album may hold more than one run of the
    same stage; they are all that stage for checking purposes."""
    return _ALIAS_TO_ROLE.get(role.split()[0] if role.split() else role, role)

# "Same performance" is judged on the loudness envelope, not on samples.
#
# The first version of this check correlated raw samples from the middle of
# each file and reported ~0.0 for pairs that are demonstrably the same take.
# Sample correlation needs the two files aligned to the sample, and masters
# are routinely trimmed or padded by a fraction of a second. The envelope --
# short-time RMS -- carries the arrangement (where the hits and phrases are)
# and survives both the offset and the EQ/compression differences that are
# the whole point of the comparison. A lag search absorbs what is left.
IDENTITY_MIN_CORR = 0.85
ENV_HOP_S = 0.05           # 50 ms envelope
ENV_MAX_LAG_S = 3.0        # how far apart the two files may start
DURATION_TOL_S = 5.0       # masters get trimmed; that is not a defect


@dataclass
class Issue:
    level: str        # "error" | "warn"
    where: str
    what: str

    def __str__(self) -> str:
        mark = "ERROR" if self.level == "error" else "warn "
        return f"  [{mark}] {self.where}: {self.what}"


@dataclass
class Report:
    issues: List[Issue] = field(default_factory=list)
    checked: int = 0
    sets: int = 0
    # service settings read out of filenames, e.g. {"mixea MediumBright": [...]}
    settings: Dict[str, List[str]] = field(default_factory=dict)

    @property
    def errors(self) -> List[Issue]:
        return [i for i in self.issues if i.level == "error"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def add(self, level: str, where: str, what: str) -> None:
        self.issues.append(Issue(level, where, what))


def _role_and_stem(name: str):
    """`<prefix>-<song>.wav` -> (role, song). The prefix may be any alias in
    ROLES, so a corpus can use whatever naming it already has."""
    m = re.match(r"^([A-Za-z0-9]+)-(.+)\.wav$", name)
    if not m:
        return None, None
    role = _ALIAS_TO_ROLE.get(m.group(1).lower())
    return (role, m.group(2).lower()) if role else (None, None)


def _provenance(path: str) -> str:
    t = read_tags(path) or {}
    return " ".join(str(v) for v in t.values()).lower()


def _sha1(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _envelope(path: str):
    """Short-time RMS in dB over the whole file — the shape of the
    performance, independent of how it was processed or where it starts."""
    x, sr = load_audio(path)
    mono = x.mean(axis=1) if x.ndim > 1 else x
    hop = max(1, int(ENV_HOP_S * sr))
    n = len(mono) // hop
    frames = mono[:n * hop].reshape(n, hop)
    rms = np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1))
    return 20.0 * np.log10(np.maximum(rms, 1e-9)), sr, len(mono) / sr


def _best_lag_corr(a: np.ndarray, b: np.ndarray, max_lag: int) -> float:
    """Highest correlation between two envelopes over a lag search."""
    a = a - a.mean()
    b = b - b.mean()
    if a.std() < 1e-9 or b.std() < 1e-9:
        return float("nan")
    best = -1.0
    for lag in range(-max_lag, max_lag + 1):
        if lag < 0:
            x, y = a[-lag:], b[:len(b) + lag]
        else:
            x, y = a[:len(a) - lag], b[lag:]
        n = min(len(x), len(y))
        if n < 20:
            continue
        x, y = x[:n], y[:n]
        sx, sy = x.std(), y.std()
        if sx < 1e-9 or sy < 1e-9:
            continue
        c = float(np.dot(x - x.mean(), y - y.mean()) / (n * sx * sy))
        best = max(best, c)
    return best


def _collect_flat(folder: str, rep: Report):
    """`<role>-<song>.wav` all in one folder."""
    by_stem: Dict[str, Dict[str, str]] = {}
    for name in sorted(os.listdir(folder)):
        if not name.lower().endswith(".wav"):
            continue
        role, stem = _role_and_stem(name)
        if role is None:
            rep.add("warn", name, "name does not match <role>-<song>.wav, skipped")
            continue
        by_stem.setdefault(stem, {})[role] = os.path.join(folder, name)
    return by_stem


def _collect_album(folder: str, rep: Report):
    """An album laid out as one subfolder per role — `suno/`, `shimmer/`,
    `distrokid/` — with the same song filename in each.

    This is how the albums are actually organised on disk, and renaming
    fifty files to satisfy a validator is the kind of friction that stops
    people validating.
    """
    by_stem: Dict[str, Dict[str, str]] = {}
    for sub in sorted(os.listdir(folder)):
        path = os.path.join(folder, sub)
        if not os.path.isdir(path):
            continue
        # "shimmer 1" and the like: take the leading word as the role.
        role = _ALIAS_TO_ROLE.get(sub.lower().split()[0] if sub.split() else "")
        if role is None:
            continue
        variant = sub.lower() if sub.lower() != role else role
        for name in sorted(os.listdir(path)):
            if not name.lower().endswith(".wav"):
                continue
            song, meta = split_settings(name)
            if meta:
                rep.settings.setdefault(
                    f"{meta.get('service', '?')} {meta.get('settings', '?')}",
                    []).append(song)
            by_stem.setdefault(song.strip().lower(), {})[variant] = \
                os.path.join(path, name)
    return by_stem


def is_album_layout(folder: str) -> bool:
    """True when the folder holds role subfolders rather than loose files."""
    try:
        subs = [d for d in os.listdir(folder)
                if os.path.isdir(os.path.join(folder, d))]
    except OSError:
        return False
    return any(_ALIAS_TO_ROLE.get(d.lower().split()[0] if d.split() else "")
               for d in subs)


def scan(folder: str = SOURCES) -> Report:
    """Check every set in `folder`. A 'set' is one song's files.

    Accepts either layout: loose `<role>-<song>.wav` files, or one subfolder
    per role with matching song filenames.
    """
    rep = Report()
    if not os.path.isdir(folder):
        rep.add("error", folder, "corpus folder does not exist")
        return rep

    by_stem = (_collect_album(folder, rep) if is_album_layout(folder)
               else _collect_flat(folder, rep))

    hashes: Dict[str, List[str]] = {}
    for files in by_stem.values():
        for path in files.values():
            rep.checked += 1
            hashes.setdefault(_sha1(path), []).append(os.path.basename(path))

    for digest, names in hashes.items():
        if len(names) > 1:
            rep.add("error", ", ".join(names),
                    "identical files under different names - a copy that did "
                    "not happen, or a mislabelled file")

    for stem, files in sorted(by_stem.items()):
        rep.sets += 1
        # 1. Provenance.
        for role, path in sorted(files.items()):
            spec = ROLES[_base_role(role)]
            prov = _provenance(path)
            hit = any(m in prov for m in spec["markers"])
            if not hit:
                lvl = "error" if spec["required"] else "warn"
                rep.add(lvl, os.path.basename(path),
                        f"claims to be a {spec['label']} but carries no "
                        f"{'/'.join(spec['markers'])} marker in its tags"
                        + ("" if spec["required"] else " (unverified, may predate tagging)"))

        # 2. Pairing: a master with no source cannot be measured against one.
        if not any(_base_role(r) == "source" for r in files):
            for role in files:
                if _base_role(role) != "source":
                    rep.add("error", stem,
                            f"{role} master has no source render to measure against")
            continue

        # 3 & 4. Identity and shape.
        try:
            src_key = next(r for r in files if _base_role(r) == "source")
            ref, sr_ref, dur_ref = _envelope(files[src_key])
        except Exception as e:  # noqa: BLE001
            rep.add("error", f"source for {stem}", f"unreadable: {e}")
            continue
        max_lag = int(ENV_MAX_LAG_S / ENV_HOP_S)
        for role, path in sorted(files.items()):
            if _base_role(role) == "source":
                continue
            try:
                other, sr, dur = _envelope(path)
            except Exception as e:  # noqa: BLE001
                rep.add("error", os.path.basename(path), f"unreadable: {e}")
                continue
            if sr != sr_ref:
                rep.add("error", os.path.basename(path),
                        f"sample rate {sr} does not match the source's {sr_ref}")
            if abs(dur - dur_ref) > DURATION_TOL_S:
                rep.add("error", os.path.basename(path),
                        f"duration {dur:.1f}s against the source's "
                        f"{dur_ref:.1f}s - too far apart to be the same take")
                continue
            corr = _best_lag_corr(ref, other, max_lag)
            if not np.isfinite(corr):
                rep.add("warn", os.path.basename(path), "envelope is flat or silent")
            elif corr < IDENTITY_MIN_CORR:
                rep.add("error", os.path.basename(path),
                        f"envelope only {corr:.3f} correlated with its source - "
                        f"this is not the same performance")
    return rep


def require_valid_corpus(folder: str = SOURCES, strict: bool = True) -> Report:
    """Call this at the top of anything that measures the corpus.

    Raises on a corpus with errors, so a bad file cannot reach a measurement
    and quietly become a finding.
    """
    rep = scan(folder)
    if strict and not rep.ok:
        lines = "\n".join(str(i) for i in rep.errors)
        raise RuntimeError(
            f"Corpus failed validation - refusing to measure.\n{lines}\n"
            f"Run: python scripts/corpus_check.py")
    return rep


def freeze(folder: str = SOURCES, out: str = MANIFEST) -> int:
    """Record what every file is right now.

    A held-out test set that can silently change is not held out. This makes
    a swap or a re-render detectable rather than something you find out about
    when a number moves for no reason.
    """
    entries = {}
    for name in sorted(os.listdir(folder)):
        if name.lower().endswith(".wav"):
            p = os.path.join(folder, name)
            entries[name] = {"sha1": _sha1(p), "bytes": os.path.getsize(p)}
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"files": entries}, f, indent=1)
    return len(entries)


def verify(folder: str = SOURCES, path: str = MANIFEST) -> Report:
    rep = Report()
    if not os.path.exists(path):
        rep.add("warn", "CORPUS.json", "no manifest yet - run --freeze")
        return rep
    with open(path, encoding="utf-8") as f:
        want = json.load(f)["files"]
    have = {n for n in os.listdir(folder) if n.lower().endswith(".wav")}
    for name, meta in sorted(want.items()):
        if name not in have:
            rep.add("error", name, "in the manifest but missing from the corpus")
            continue
        if _sha1(os.path.join(folder, name)) != meta["sha1"]:
            rep.add("error", name,
                    "content changed since the manifest was frozen - any "
                    "held-out result measured on it is void")
    for name in sorted(have - set(want)):
        rep.add("warn", name, "new file, not in the manifest")
    rep.checked = len(want)
    return rep


def main(argv: List[str]) -> int:
    if "--freeze" in argv:
        n = freeze()
        print(f"Froze {n} files into {os.path.relpath(MANIFEST, ROOT)}")
        return 0
    rep = verify() if "--verify" in argv else scan()
    what = "manifest" if "--verify" in argv else "corpus"
    print(f"Checked {rep.checked} files"
          + (f" across {rep.sets} songs" if rep.sets else "") + f" in the {what}.")
    if not rep.issues:
        print("  All clear.")
    for i in rep.issues:
        print(i)
    print()
    print("PASS" if rep.ok else f"FAIL - {len(rep.errors)} error(s)")
    return 0 if rep.ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
