"""How a long run says where it is, and learns that it should stop.

render() and export() report each stage by key (the chain the screen
lights up) and check for cancel at every stage boundary. A cancelled run
stops at the next boundary by raising Cancelled; nothing half-written is
left behind (export writes under a temporary name).
"""
from __future__ import annotations

import threading
from typing import Callable, Optional


class Cancelled(Exception):
    """The run was cancelled."""


class Progress:
    def __init__(self, on_stage: Optional[Callable[[str, str, str], None]] = None,
                 on_fraction: Optional[Callable[[float], None]] = None) -> None:
        self._on_stage = on_stage
        self._on_fraction = on_fraction
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def check(self) -> None:
        if self._cancel.is_set():
            raise Cancelled()

    def stage(self, key: str, label: str, detail: str = "") -> None:
        self.check()
        if self._on_stage:
            self._on_stage(key, label, detail)

    def fraction(self, value: float) -> None:
        self.check()
        if self._on_fraction:
            self._on_fraction(float(value))
