"""
projects_store.py — Per-track project persistence (disk, not browser).

A "project" is everything the user has dialed in for one specific audio
file, keyed by the file's content hash — the same digest the stem cache
uses, so a crash/reload recovery is: re-drop the file, stems come from
cache, knobs come from here.

Location:
    Windows:  %APPDATA%/Shimmer/projects/<sha1>.json
    Other:    ~/.config/shimmer/projects/<sha1>.json

Each file holds {"name": ..., "updated_at": ..., "remix": {...}} and is
written atomically on every (debounced) change from the UI.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Dict, List, Optional

from settings_store import _settings_dir

_DIGEST_RE = re.compile(r"^[0-9a-f]{40}$")


def _projects_dir() -> str:
    return os.path.join(_settings_dir(), "projects")


def _project_path(digest: str) -> Optional[str]:
    if not _DIGEST_RE.match(digest or ""):
        return None
    return os.path.join(_projects_dir(), f"{digest}.json")


def load_project(digest: str) -> Dict[str, Any]:
    path = _project_path(digest)
    if not path or not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_project(digest: str, data: Dict[str, Any]) -> bool:
    path = _project_path(digest)
    if not path:
        return False
    data = dict(data)
    data["updated_at"] = time.time()
    os.makedirs(_projects_dir(), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)
    return True


def list_projects(limit: int = 50) -> List[Dict[str, Any]]:
    """Most-recent-first project summaries (for a future history view)."""
    d = _projects_dir()
    if not os.path.isdir(d):
        return []
    out = []
    for fn in os.listdir(d):
        if not fn.endswith(".json"):
            continue
        digest = fn[:-5]
        if not _DIGEST_RE.match(digest):
            continue
        data = load_project(digest)
        if not data:
            continue
        out.append({
            "digest": digest,
            "name": data.get("name", ""),
            "updated_at": data.get("updated_at", 0),
        })
    out.sort(key=lambda p: -float(p.get("updated_at") or 0))
    return out[:limit]
