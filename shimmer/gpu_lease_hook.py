r"""Optional wiring to a machine-wide GPU lease, for a developer's own system.

Some machines run several AI tools on one GPU and have them take turns
through a small lease library, `gpu_lease.py`, that lives outside Shimmer.
When that library is present, Shimmer's GPU work (the stem split, which the
Remix tab and the Vocal grain card's vocal mode use, and the training
scripts) holds the lease while it uses the GPU and waits its turn. Anywhere
else this module does nothing at all: nothing is imported, and there is no
setting, message or wait. Public installs behave exactly as before.

Where it looks: the folder named by GPU_LEASE_HOME, or D:\LLMVault\GpuLease
when that is unset. Point GPU_LEASE_HOME at a folder without gpu_lease.py
to switch it off.

Standard library only, and it imports nothing from the rest of Shimmer:
stems_runner.py and the training scripts run in the separate stems
environment, and load this file by its path (importlib).
"""
from __future__ import annotations

import contextlib
import os
import sys

DEFAULT_HOME = r"D:\LLMVault\GpuLease"
TOOL = "Shimmer"


def lease_home() -> str:
    return os.environ.get("GPU_LEASE_HOME") or DEFAULT_HOME


def available() -> bool:
    """True when the lease library is present on this machine."""
    return os.path.isfile(os.path.join(lease_home(), "gpu_lease.py"))


def gpu_lease(purpose: str, vram_gb: float, on_wait=None):
    """A context manager that holds the GPU lease for `purpose`, or a no-op
    one when the library is not present. `on_wait(message)` hears who holds
    the GPU while this waits for its turn."""
    if not available():
        return contextlib.nullcontext()
    home = lease_home()
    if home not in sys.path:
        sys.path.insert(0, home)
    from gpu_lease import GpuLease  # the owner's library, outside Shimmer
    return GpuLease(tool=TOOL, purpose=purpose, vram_gb=float(vram_gb), on_wait=on_wait)
