"""Nothing personal in the public repo (docs/STYLE.md, "Public and private").

The repo is public. Song paths, folder names and anything else that points
at the author's own files belong in the git-ignored `private/` folder. This
reads every file git tracks and fails on:

- a path into a personal music or download folder (the patterns below)
- a path into a user's home folder on Windows
- any line of `private/markers.txt` (song titles, artist names, a user
  name: one per line, # for comments), when that file exists. The markers
  themselves stay private, so on another machine this part is skipped.
"""
import os
import re
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEXT = (".py", ".js", ".html", ".css", ".md", ".json", ".txt", ".bat", ".ps1", ".sh",
        ".toml", ".yml", ".yaml", ".cfg", ".ini")
PATTERNS = [
    re.compile(r"[A-Za-z]:[\\/]{1,2}(MusicVault|DownloadVault)\b", re.I),
    re.compile(r"[A-Za-z]:[\\/]{1,2}Users[\\/]{1,2}(?!<|YOU|NAME|%)[A-Za-z0-9._-]+", re.I),
]
# This file names the patterns it looks for.
EXEMPT = {"tests/test_privacy.py"}


def _tracked():
    try:
        out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True,
                             timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        pytest.skip("git is not available")
    if out.returncode != 0:
        pytest.skip("not a git checkout")
    return [f for f in out.stdout.splitlines() if f.lower().endswith(TEXT) and f not in EXEMPT]


def _private_dir():
    import sys
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    from _private import private_dir
    return private_dir()


def _hits(patterns):
    hits = []
    for f in _tracked():
        try:
            with open(os.path.join(ROOT, f), encoding="utf-8", errors="replace") as fh:
                for n, line in enumerate(fh, 1):
                    for p in patterns:
                        if p.search(line):
                            hits.append(f"{f}:{n}: {line.strip()[:100]}")
                            break
        except OSError:
            continue
    return hits


def test_no_personal_paths_in_the_public_repo():
    hits = _hits(PATTERNS)
    assert not hits, "Move these to private/ (docs/STYLE.md):\n" + "\n".join(hits[:40])


def test_no_private_markers_in_the_public_repo():
    markers_file = os.path.join(_private_dir(), "markers.txt")
    if not os.path.isfile(markers_file):
        pytest.skip("no private/markers.txt on this machine")
    with open(markers_file, encoding="utf-8") as fh:
        words = [w.strip() for w in fh if w.strip() and not w.lstrip().startswith("#")]
    if not words:
        pytest.skip("private/markers.txt lists nothing")
    hits = _hits([re.compile(re.escape(w), re.I) for w in words])
    assert not hits, "Private names in public files:\n" + "\n".join(hits[:40])
