"""
settings_store.py — Persist last-used UI settings to a JSON file.

Location:
    Windows:  %APPDATA%/Shimmer/settings.json
    Other:    ~/.config/shimmer/settings.json
    Either, when SHIMMER_CONFIG_DIR is set: that folder instead. A second
    copy of Shimmer (the rebuild, while it is being built) sets it so it
    never reads or writes the everyday app's settings or projects
    (docs/ARCHITECTURE.md §19.1 item 4).

The frontend posts the full control state and we write it verbatim.
Same-session consumers (e.g. Batch EQ reuse) always read it back.  The
Single File UI restores values on page load only when
``remember_settings`` is true.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict


def _settings_dir() -> str:
    override = os.environ.get("SHIMMER_CONFIG_DIR", "").strip()
    if override:
        return override
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, "Shimmer")
    return os.path.join(os.path.expanduser("~"), ".config", "shimmer")


def _settings_path() -> str:
    return os.path.join(_settings_dir(), "settings.json")


# Saves are stamped with this. 2: from 2.0.2, when a Streaming target saved
# by an older version stopped being carried over (migrate_saved).
SETTINGS_VERSION = 2


def load_settings() -> Dict[str, Any]:
    """Return the last-saved settings, or {} if none exist, carried over
    from 1.x as they load (see migrate_saved)."""
    path = _settings_path()
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
    except (OSError, json.JSONDecodeError):
        return {}
    return migrate_saved(data)


def migrate_saved(data: Dict[str, Any]) -> Dict[str, Any]:
    """Settings saved by 1.x, carried over (docs/ARCHITECTURE.md §19.3):

    - A version-named preset key ("suno_v5_pro") gets its current name
      ("air_brittle"), for the old preset menu while it remains.
    - A file with no card picks yet ("fixes") gets the card its preset maps
      to, at that card's default Amount. Once 2.0 has saved the picks, they
      are kept as saved, so a card turned off stays off.

    - A loudness target of "streaming" saved before 2.0.2 becomes the
      Commercial default. Streaming (-14 LUFS) was 1.x's default, so almost
      every upgrade carried it over unchosen, and 2.0 mastered those songs
      5 dB quieter than the Commercial default it was built to fix. Every
      save from 2.0.2 on is stamped SETTINGS_VERSION, so a Streaming choice
      made since then is kept.

    Nothing is written back until the screen next saves. The tables are the
    engine's (core.settings), so the 1.x presets module can go.
    """
    # Local import, as before: nothing heavy at server start.
    from .core import catalog
    from .core.settings import LEGACY_ALIASES, card_for_preset
    out = dict(data)
    preset = out.get("preset")
    if isinstance(preset, str) and preset.strip().lower() in LEGACY_ALIASES:
        out["preset"] = LEGACY_ALIASES[preset.strip().lower()]
    if not isinstance(out.get("fixes"), dict):
        card = card_for_preset(out.get("preset"))
        out["fixes"] = {card: catalog.card(card).default_amount} if card else {}
    master = out.get("mastering")
    if (int(out.get("settings_version") or 0) < SETTINGS_VERSION and isinstance(master, dict)
            and master.get("target") == "streaming"):
        out["mastering"] = {**master, "target": catalog.DEFAULT_LOUDNESS}
    return out


def save_settings(data: Dict[str, Any]) -> None:
    """Atomically write settings JSON to disk, stamped SETTINGS_VERSION."""
    data = {**data, "settings_version": SETTINGS_VERSION}
    d = _settings_dir()
    os.makedirs(d, exist_ok=True)
    path = _settings_path()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)
