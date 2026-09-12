"""The web layer talks to the engine through one door, and the screens read
the rules instead of copying them.

The old server called DSP code directly from six places, and the browser kept
its own copies of at least twelve engine rules (ARCHITECTURE §5, §7). These
tests hold the new layout to docs/ARCHITECTURE.md §18.3:
    - shimmer/api/* imports only shimmer.core (its public names), never DSP
      libraries or old engine modules
    - shimmer/core/* never imports the web layer or the old engine
    - GET /api/rules serves the loudness choices, formats, EQ limits and
      cards straight from shimmer.core.catalog
    - no screen hard-codes the loudness choices again (Step 6)
"""
import ast
import importlib
import importlib.util
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
BANNED_LIBS = {"scipy", "soundfile", "pyloudnorm"}
WEB_LIBS = {"fastapi", "starlette", "uvicorn"}
# 1.x modules the plan keeps as they are (ARCHITECTURE §16: Keep). The web
# layer may call them until they move; the old engine stays off limits.
KEPT = {"stems", "projects_store", "settings_store"}


def _missing(name):
    try:
        return importlib.util.find_spec(name) is None
    except ModuleNotFoundError:
        return True


def needs(*modules):
    """Same gate as tests/core/_contract.py: expected to fail, strictly,
    until these modules exist, and only by a failed import."""
    gone = [m for m in modules if _missing(m)]
    return pytest.mark.xfail(bool(gone), reason="not built yet: " + ", ".join(gone),
                             raises=ImportError, strict=True)


def _imports(path, package):
    """(absolute module, names) for every import in a file, with relative
    imports resolved against the file's package."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                yield a.name, []
        elif isinstance(node, ast.ImportFrom):
            names = [a.name for a in node.names]
            if node.level:
                base = package.split(".")
                base = base[:len(base) - (node.level - 1)]
                if not base:
                    yield "<outside the package>", names
                    continue
                yield ".".join(base + ([node.module] if node.module else [])), names
            else:
                yield node.module or "", names


def _package_of(path, root_pkg, root_dir):
    """The package a file's relative imports start from: its folder."""
    return ".".join([root_pkg] + list(path.relative_to(root_dir).parts[:-1]))


def _files(pkg):
    mod = importlib.import_module(pkg)
    d = pathlib.Path(mod.__file__).parent
    files = sorted(d.rglob("*.py"))
    assert files
    return d, files


@needs("shimmer.api")
def test_the_web_layer_imports_only_the_engines_public_face():
    d, files = _files("shimmer.api")
    for f in files:
        for module, names in _imports(f, _package_of(f, "shimmer.api", d)):
            top = module.split(".")[0]
            assert top not in BANNED_LIBS, f"{f.name} imports {module}"
            if module == "shimmer":
                assert set(names) <= {"core"} | KEPT, f"{f.name} imports {names} from shimmer"
            elif module.startswith("shimmer"):
                assert (module == "shimmer.core" or module.startswith("shimmer.api")
                        or module in {f"shimmer.{k}" for k in KEPT}), \
                    f"{f.name} imports {module}; the web layer may only use shimmer.core"
            assert module != "<outside the package>", f"{f.name} reaches outside shimmer.api"


@needs("shimmer.core")
def test_the_engine_never_imports_the_web_layer_or_the_old_engine():
    d, files = _files("shimmer.core")
    for f in files:
        for module, _ in _imports(f, _package_of(f, "shimmer.core", d)):
            assert module.split(".")[0] not in WEB_LIBS, f"{f.name} imports {module}"
            if module.startswith("shimmer"):
                assert module.startswith("shimmer.core"), \
                    f"{f.name} imports {module}; the new engine carries nothing from the old one"


@needs("shimmer.api", "shimmer.core.catalog")
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


# Each pattern matches a copy found in the screens on 2026-09-12:
# single.js:859, remix.js:463, visualizer.js:293, index.html:348-350 (x3).
COPIES = [
    re.compile(r"\b(streaming|loud|cd)['\"]?\s*:\s*['\"]?[-−]\s?\d"),
    re.compile(r"\btargetLufs\s*:\s*-?\d"),
    re.compile(r"<option[^>]*value=['\"](streaming|loud|cd)['\"]"),
]


@pytest.mark.xfail(reason="the screens are re-wired to /api/rules in Step 6; remove this mark then",
                   raises=AssertionError, strict=True)
def test_the_screens_do_not_copy_the_loudness_choices():
    static = ROOT / "static"
    files = sorted((static / "js").rglob("*.js")) + [static / "index.html"]
    offenders = [f"{p.relative_to(static)}:{n}"
                 for p in files
                 for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
                 if any(c.search(line) for c in COPIES)]
    assert offenders == []
