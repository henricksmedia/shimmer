"""
Signal Chain description (chain.py, POST /api/chain).

The chain view is generated from the same Params / MasterParams /
options a run would use, so these tests pin the things that used to
drift when the view was a hand-written list: stage order equals the
engine registry, preset-dependent numbers (crossover, Mid scale, bands)
come from the preset, strength scaling shows up in the badges, and both
ends of the chain (Trim, Preserve volume, Export) are present.

Run:  .venv\\Scripts\\python.exe -m pytest tests/test_chain.py -q
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shimmer.chain import build_chain  # noqa: E402
from shimmer.engine import STAGE_REGISTRY  # noqa: E402
from shimmer.mastering import master_params_from_json  # noqa: E402
from shimmer.params import apply_preset_strength  # noqa: E402
from shimmer.presets import get_preset  # noqa: E402

STAGE_IDS = ["expander", "denoise", "deres", "shimmer", "deharsh",
             "flicker", "decheck", "tonekill", "resynth"]


def _ids(chain):
    return [m["id"] for m in chain["modules"]]


def _mod(chain, mid):
    return next(m for m in chain["modules"] if m["id"] == mid)


def _mp(enabled=True, target="streaming"):
    return master_params_from_json({"enabled": enabled, "target": target})


class TestOrder:
    def test_stft_stages_follow_registry_order(self):
        chain = build_chain(get_preset("generic"), _mp())
        ids = _ids(chain)
        stft = [i for i in ids if i in STAGE_IDS]
        assert stft == STAGE_IDS
        assert len(STAGE_IDS) == len(STAGE_REGISTRY)

    def test_ends_and_backbone_are_present_in_order(self):
        ids = _ids(build_chain(get_preset("generic"), _mp()))
        backbone = ["trim", "tone", "xover", "ms", "premask", "expander",
                    "resynth", "swc", "mix", "post", "eq", "preserve",
                    "m-hp", "m-gain", "m-clip", "m-limit", "export"]
        pos = [ids.index(b) for b in backbone]
        assert pos == sorted(pos)
        assert ids[0] == "trim" and ids[-1] == "export"


class TestPresetNumbers:
    def test_vocal_glaze_crossover_and_mid_scale(self):
        chain = build_chain(get_preset("vocal_glaze"), _mp())
        assert "300 Hz" in _mod(chain, "xover")["badges"]
        assert "Mid 0.5×" in _mod(chain, "ms")["badges"]
        assert chain["gates"]["low_band_bypass_hz"] == 300.0

    def test_generic_defaults(self):
        chain = build_chain(get_preset("generic"), _mp())
        assert "4500 Hz" in _mod(chain, "xover")["badges"]
        assert "Mid 0.2×" in _mod(chain, "ms")["badges"]
        assert _mod(chain, "expander")["active"] is False
        assert _mod(chain, "denoise")["active"] is False
        assert _mod(chain, "tonekill")["active"] is True

    def test_echo_sheen_enables_expander_and_two_passes(self):
        chain = build_chain(get_preset("echo_sheen"), _mp())
        assert _mod(chain, "expander")["active"] is True
        assert chain["summary"]["iterations"] == 2

    def test_deep_scrub_pre_analyze(self):
        chain = build_chain(get_preset("deep_scrub"), _mp())
        assert _mod(chain, "premask")["active"] is True
        assert "Mid 0.45×" in _mod(chain, "ms")["badges"]

    def test_strength_scaling_shows_in_badges(self):
        p = get_preset("suno_hash")
        apply_preset_strength(p, 0.5)
        chain = build_chain(p, _mp())
        # denoise 0.35 -> 0.175 at half strength
        assert "18%" in _mod(chain, "denoise")["badges"]


class TestOptions:
    def test_mastering_off_uses_preserve_volume(self):
        chain = build_chain(get_preset("generic"), _mp(enabled=False),
                            preserve_volume=True)
        assert _mod(chain, "tone")["active"] is False
        assert _mod(chain, "preserve")["active"] is True
        for mid in ("m-hp", "m-gain", "m-clip", "m-limit"):
            assert _mod(chain, mid)["active"] is False

    def test_mastering_on_skips_preserve(self):
        chain = build_chain(get_preset("generic"), _mp(enabled=True),
                            preserve_volume=True)
        assert _mod(chain, "preserve")["active"] is False
        assert _mod(chain, "tone")["active"] is True
        assert "-14 LUFS" in _mod(chain, "m-gain")["badges"]

    def test_export_format_ceiling_and_trim(self):
        mp = _mp()
        mp.ceiling_dbtp = -1.5
        chain = build_chain(get_preset("generic"), mp, output_format="mp3",
                            trim_silence=True)
        assert "-1.5 dBTP" in _mod(chain, "m-limit")["badges"]
        assert "MP3" in _mod(chain, "export")["badges"]
        assert any("silence trim" in b for b in _mod(chain, "export")["badges"])

    def test_trim_and_eq_flags(self):
        chain = build_chain(get_preset("generic"), _mp(), eq_bands=3, trim_armed=True)
        assert _mod(chain, "trim")["active"] is True
        assert "3 bands" in _mod(chain, "eq")["badges"]
        chain2 = build_chain(get_preset("generic"), _mp())
        assert _mod(chain2, "trim")["active"] is False
        assert _mod(chain2, "eq")["active"] is False


class TestEndpoint:
    def test_api_chain_matches_builder(self):
        from fastapi.testclient import TestClient
        from shimmer.server import app
        with TestClient(app) as client:
            r = client.post("/api/chain", json={
                "preset": "vocal_glaze", "preset_strength": 1.0,
                "mastering": {"enabled": False},
                "preserve_volume": True, "output_format": "wav",
            })
        assert r.status_code == 200
        data = r.json()
        assert "300 Hz" in _mod(data, "xover")["badges"]
        assert _mod(data, "preserve")["active"] is True
        assert data["summary"]["mastering"] is False
