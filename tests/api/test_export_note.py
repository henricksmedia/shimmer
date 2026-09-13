"""The provenance note an export writes into the comment tag names every
fix that ran, not only Fixed tones (shimmer/api/render.py _note)."""
import numpy as np

from shimmer import core
from shimmer.api import render as api_render


def _rendered(fixes, mastering=None):
    report = {"fixes": fixes, "mastering": mastering or {"enabled": False}}
    return core.Rendered(np.zeros((10, 2), dtype=np.float32), 48000, report, core.Settings())


def test_every_fix_that_ran_is_named():
    note = api_render._note("pass 1", _rendered({
        "tones": {"enabled": True, "notches": 2},
        "sibilance": {"enabled": True, "amount": 0.5, "tool": "deesser"},
        "shimmer": {"enabled": True, "amount": 1.0, "tool": "hash_remover"},
        "phasiness": "not built yet",
    }), [])
    assert "pass 1, Fixed tones 2 notches, Sibilance 50%, Shimmer 100%, cleaning only" in note


def test_a_fix_without_fixed_tones_is_not_called_no_fixes():
    note = api_render._note("pass 1", _rendered({"harshness": {"enabled": True, "amount": 0.3}}), [])
    assert "Harshness 30%" in note and "no fixes" not in note


def test_nothing_on_says_no_fixes():
    assert "pass 1, no fixes, cleaning only" in api_render._note("pass 1", _rendered({}), [])
