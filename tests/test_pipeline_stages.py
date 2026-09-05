"""
Chain stage reporting (pipeline.clean_and_master stage_callback).

The progress modal shows where the audio is in the chain, so the stages
must arrive in chain order, with the keys the Signal Chain phases use,
and only for the stages that actually run.

Run:  .venv\\Scripts\\python.exe -m pytest tests/test_pipeline_stages.py -q
"""

from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shimmer.eq import EqBand, EqParams
from shimmer.params import MasterParams
from shimmer.pipeline import clean_and_master
from shimmer.presets import get_preset

SR = 44100


def _signal(dur: float = 2.5, seed: int = 3) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(SR * dur)
    t = np.arange(n) / SR
    x = 0.2 * np.sin(2 * np.pi * 220 * t) + 0.02 * rng.standard_normal(n)
    return np.stack([x, x * 0.9], axis=1).astype(np.float32)


def _dedupe(keys):
    out = []
    for k in keys:
        if not out or out[-1] != k:
            out.append(k)
    return out


def test_stages_arrive_in_chain_order_with_mastering():
    seen = []
    p = get_preset("generic")
    clean_and_master(_signal(), SR, p, master_params=MasterParams(enabled=True),
                     eq_params=EqParams(enabled=True, bands=[EqBand(freq_hz=300, gain_db=-1.0)]),
                     stage_callback=lambda k, label, detail: seen.append((k, label, detail)))
    keys = _dedupe([k for k, _l, _d in seen])
    # Mid and Side each get fine/engine; the order between them is
    # fine, engine, fine, engine (or engine, engine without a fine pass).
    core = [k for k in keys if k not in ("fine", "engine")]
    assert core == ["repair", "pre", "split", "recombine", "post", "master"], keys
    assert keys.index("split") < keys.index("engine") < keys.index("recombine")
    labels = {k: l for k, l, _d in seen}
    assert labels["post"].endswith("your EQ")
    details = {k: d for k, _l, d in seen}
    assert "1 band" in details["post"]
    assert "LUFS" in details["master"]
    channels = [d for k, _l, d in seen if k == "engine"]
    assert channels[0].startswith("Mid") and channels[-1].startswith("Side")


def test_stages_skip_what_does_not_run():
    seen = []
    p = get_preset("generic")
    clean_and_master(_signal(), SR, p, master_params=None,
                     stage_callback=lambda k, label, detail: seen.append(k))
    keys = _dedupe(seen)
    assert "pre" not in keys and "master" not in keys
    assert keys[0] == "repair" and keys[-1] == "post"


def test_no_callback_is_a_no_op():
    p = get_preset("generic")
    y, removed, report = clean_and_master(_signal(), SR, p, master_params=None)
    assert y.shape[0] == _signal().shape[0]
