"""
_winfix.py — Defensive Windows-only patches that must run before scipy/numpy.

Importing scipy submodules on Python 3.12 / Windows transitively calls
``platform.machine()`` → ``platform.uname()`` → ``platform._win32_ver()``
→ ``platform._wmi_query()``, which shells out to WMI. When the local WMI
service is unhealthy that call hangs forever, freezing every entry point
(``server.py``, ``shimmer.py``, the diag scripts) before they ever bind a
socket — which manifests as ``Shimmer.bat`` "starting" but the browser
never seeing a response.

We neutralise ``platform._wmi_query`` so it raises ``OSError`` immediately.
The CPython ``_win32_ver`` implementation already wraps WMI calls in
``try/except OSError``, so it falls back cleanly to the registry-based
version detection.

This module has no public API. Just ``import _winfix`` (as early as
possible, before any scipy import) and the patch is installed as a side
effect. It is idempotent and a no-op on non-Windows platforms.
"""

from __future__ import annotations

import sys


def _install() -> None:
    if sys.platform != "win32":
        return
    import platform as _platform

    if getattr(_platform, "_shimmer_wmi_patched", False):
        return
    if not hasattr(_platform, "_wmi_query"):
        return

    def _wmi_query_disabled(*_args, **_kwargs):
        raise OSError("WMI disabled by Shimmer to avoid platform.uname() hang")

    _platform._wmi_query = _wmi_query_disabled  # type: ignore[attr-defined]
    _platform._shimmer_wmi_patched = True  # type: ignore[attr-defined]


_install()
