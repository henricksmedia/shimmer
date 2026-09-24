"""Where private material lives: the git-ignored `private/` folder.

The repo is public. Anything that names the author's songs or folders (song
paths, test libraries, research data, listening notes) lives in `private/`
at the top of the main checkout, which git never tracks (.gitignore). A
worktree or a test copy finds the same folder through git, so there is one
private home, not one per copy. docs/STYLE.md, "Public and private", has the
rule; tests/test_privacy.py checks it.

    private_dir()          the folder (SHIMMER_PRIVATE overrides it)
    private_path(*parts)   a path inside it
    paths()                private/paths.json: folder locations the scripts
                           need, kept out of the code
    need(key)              one of those, or a clear message saying where to
                           add it
"""
from __future__ import annotations

import json
import os
import subprocess
from typing import Any, Dict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def private_dir() -> str:
    override = os.environ.get("SHIMMER_PRIVATE", "").strip()
    if override:
        return override
    try:
        common = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
                                cwd=ROOT, capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        common = ""
    main = os.path.dirname(common) if common else ROOT
    return os.path.join(main, "private")


def private_path(*parts: str) -> str:
    return os.path.join(private_dir(), *parts)


def paths() -> Dict[str, Any]:
    p = private_path("paths.json")
    if not os.path.isfile(p):
        return {}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def need(key: str) -> Any:
    value = paths().get(key)
    if value is None:
        raise SystemExit(f"Add \"{key}\" to {private_path('paths.json')}: this script needs it, "
                         "and folder locations stay out of the public code.")
    return value
