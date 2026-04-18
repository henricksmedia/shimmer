"""
settings_store.py — Persist last-used UI settings to a JSON file.

Location:
    Windows:  %APPDATA%/Shimmer/settings.json
    Other:    ~/.config/shimmer/settings.json

The frontend posts the full control state and we write it verbatim.  On
startup we read it back and return it to the frontend so sliders restore.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict


def _settings_dir() -> str:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, "Shimmer")
    return os.path.join(os.path.expanduser("~"), ".config", "shimmer")


def _settings_path() -> str:
    return os.path.join(_settings_dir(), "settings.json")


def load_settings() -> Dict[str, Any]:
    """Return the last-saved settings, or {} if none exist."""
    path = _settings_path()
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_settings(data: Dict[str, Any]) -> None:
    """Atomically write settings JSON to disk."""
    d = _settings_dir()
    os.makedirs(d, exist_ok=True)
    path = _settings_path()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)
