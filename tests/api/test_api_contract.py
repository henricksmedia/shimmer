"""The web layer talks to the engine through one door, and the screens read
the rules instead of copying them.

The old server called DSP code directly from six places, and the browser kept
its own copies of at least twelve engine rules (ARCHITECTURE §5, §7). These
tests hold the new layout to docs/ARCHITECTURE.md §18.3:
    - shimmer/api/* imports only shimmer.core (its public names), never DSP
      libraries or old engine modules
    - GET /api/rules serves the loudness choices, formats, EQ limits and
      cards straight from shimmer.core.catalog
    - no JS file under static/js hard-codes the loudness choices again
"""
import ast
import importlib.util
import pathlib
import re

import pytest

pytestmark = pytest.mark.xfail(importlib.util.find_spec("shimmer.api") is None,
                               reason="shimmer.api is not built yet (rebuild Step 4)",
                               strict=True)

ROOT = pathlib.Path(__file__).resolve().parents[2]
BANNED_LIBS = {"scipy", "soundfile", "pyloudnorm"}


def _imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                yield a.name, 0
        elif isinstance(node, ast.ImportFrom):
            yield node.module or "", node.level


def test_the_web_layer_imports_only_the_engines_public_face():
    import shimmer.api
    api_dir = pathlib.Path(shimmer.api.__file__).parent
    files = sorted(api_dir.glob("*.py"))
    assert files
    for f in files:
        for module, level in _imports(f):
            top = module.split(".")[0]
            assert top not in BANNED_LIBS, f"{f.name} imports {module}"
            if level == 0 and module.startswith("shimmer"):
                assert module in ("shimmer.core",) or module.startswith("shimmer.api"), \
                    f"{f.name} imports {module}; the web layer may only use shimmer.core"
            if level > 1:
                raise AssertionError(f"{f.name} reaches outside shimmer.api with a relative import")


def test_the_rules_route_serves_the_engines_rules():
    from fastapi.testclient import TestClient
    from shimmer.core import catalog
    from shimmer.server import app
    r = TestClient(app).get("/api/rules")
    assert r.status_code == 200
    d = r.json()
    assert {t["key"]: t["lufs"] for t in d["loudness_targets"]} == \
        {t.key: t.lufs for t in catalog.LOUDNESS_TARGETS}
    assert {f["key"]: f["ceiling_dbtp"] for f in d["formats"]} == \
        {f.key: f.ceiling_dbtp for f in catalog.FORMATS}
    assert {c["key"] for c in d["cards"]} == {c.key for c in catalog.CARDS}
    assert d["eq_limits"] == catalog.EQ_LIMITS


def test_the_screens_do_not_copy_the_loudness_choices():
    copied = re.compile(r"streaming\s*:\s*-14")
    offenders = [p.name for p in (ROOT / "static" / "js").glob("*.js")
                 if copied.search(p.read_text(encoding="utf-8"))]
    assert offenders == []
