"""GET /api/rules — the rules the screens show, from the engine's catalog.

The browser kept its own copies of the Loudness choices, format ceilings,
EQ limits and more (docs/ARCHITECTURE.md §7). The screens read them from
here instead (docs/API.md §7), so the two can never disagree again.
"""
from __future__ import annotations

import dataclasses
from typing import Any, Dict

from fastapi import APIRouter

from ..core import catalog

router = APIRouter()


def rules() -> Dict[str, Any]:
    return {
        "loudness_targets": [dataclasses.asdict(t) for t in catalog.LOUDNESS_TARGETS],
        "default_loudness": catalog.DEFAULT_LOUDNESS,
        "formats": [dataclasses.asdict(f) for f in catalog.FORMATS],
        "default_format": catalog.DEFAULT_FORMAT,
        "cards": [dataclasses.asdict(c) for c in catalog.CARDS],
        "tools": list(catalog.TOOLS),
        "default_amount": catalog.DEFAULT_AMOUNT,
        "eq_limits": dict(catalog.EQ_LIMITS),
        "eq_types": list(catalog.EQ_TYPES),
    }


@router.get("/api/rules")
def get_rules() -> Dict[str, Any]:
    return rules()
