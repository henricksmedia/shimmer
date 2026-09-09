"""The marketing kit must not drift away from the app.

static/marketing/ holds the message reference, the plan and the ten
posts. Every number on those pages is quoted from the app, which is the
whole reason they are trustworthy. These tests fail when the app changes
and the pages do not, so a stale claim cannot reach anyone.
"""
from __future__ import annotations

import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MARKETING = os.path.join(ROOT, "static", "marketing")
PAGES = ("index.html", "plan.html", "posts.html")


def read(*parts: str) -> str:
    return open(os.path.join(*parts), encoding="utf-8").read()


class TestMarketingKit:
    def test_pages_exist_and_share_the_app_styling(self):
        for page in PAGES:
            html = read(MARKETING, page)
            # The app's own tokens, so the kit tracks the product's colours.
            assert '<link rel="stylesheet" href="../css/tokens.css">' in html, page
            assert '<link rel="stylesheet" href="marketing.css">' in html, page
            assert '<script src="marketing.js"></script>' in html, page
        # Relative, so the pages work served by the app and opened off disk.
        assert os.path.exists(os.path.join(ROOT, "static", "css", "tokens.css"))
        assert os.path.exists(os.path.join(MARKETING, "marketing.css"))
        assert os.path.exists(os.path.join(MARKETING, "marketing.js"))

    def test_preset_count_matches_the_app(self):
        from shimmer.presets import VISIBLE_PRESETS

        html = read(MARKETING, "index.html")
        posts = read(MARKETING, "posts.html")
        n = len(VISIBLE_PRESETS)
        # The message reference quotes the count in its numbers table, and
        # post 6 repeats it. Both have to move when a preset is added.
        assert f"<td>{n}</td>" in html, f"message page does not say {n} presets"
        assert f"all {n} cleanup presets" in posts, f"post 6 does not say {n} presets"

    def test_loudness_targets_match_the_app(self):
        app = read(ROOT, "static", "index.html")
        page = read(MARKETING, "index.html")
        posts = read(MARKETING, "posts.html")
        for target in ("−14", "−11", "−9"):
            assert target in app, f"the app no longer offers {target} LUFS"
            assert target in page, f"the message page is missing {target}"
        # Post 7 quotes all three.
        assert "−14 LUFS" in posts and "−11" in posts and "−9" in posts

    def test_true_peak_ceilings_match_the_readme(self):
        readme = read(ROOT, "README.md")
        page = read(MARKETING, "index.html")
        for ceiling in ("−1.0", "−1.5"):
            assert ceiling in readme, f"the README no longer states {ceiling} dBTP"
            assert ceiling in page, f"the message page is missing {ceiling} dBTP"

    def test_ten_posts_and_every_one_is_copyable(self):
        html = read(MARKETING, "posts.html")
        assert len(re.findall(r'<article class="mk-post"', html)) == 10
        assert len(re.findall(r"data-copy-post", html)) == 10
        # Each post is anchored so a single one can be linked.
        for n in range(1, 11):
            assert f'id="post-{n}"' in html
        # Bulk sharing.
        assert 'id="copy-all"' in html and 'id="save-all"' in html

    @pytest.mark.parametrize("claim", [
        "AI powered",          # the cleanup path uses no machine learning
        "Removes every artifact",
        "Better than paid mastering",
    ])
    def test_forbidden_claims_appear_only_as_warnings(self, claim):
        # These phrases live on the message page as things never to say.
        # They must not turn up in the posts, which are what gets sent.
        posts = read(MARKETING, "posts.html")
        assert claim.lower() not in posts.lower(), \
            f"a post makes the claim the kit forbids: {claim}"

    def test_cleanup_path_really_has_no_machine_learning(self):
        # The kit's strongest accuracy claim: the cleaning engine is plain
        # signal processing. If that ever stops being true, the pages lie.
        import shimmer.engine as engine
        import shimmer.chain as chain

        for module in (engine, chain):
            source = read(module.__file__)
            for banned in ("import torch", "from torch", "onnxruntime",
                           "tensorflow", "sklearn"):
                assert banned not in source, \
                    f"{os.path.basename(module.__file__)} now imports {banned}"


def test_folder_urls_serve_their_index():
    """/static/marketing/ must work, not just .../index.html.

    The static mount had html=False, so a folder URL returned FastAPI's
    {"detail":"Not Found"} and only the spelled-out index.html worked. That
    is not what the CHANGELOG advertised, not what anyone types, and the
    existing tests missed it because they read the files from disk rather
    than over HTTP.
    """
    from fastapi.testclient import TestClient
    from shimmer.server import app
    client = TestClient(app)
    for url in ("/static/marketing/", "/static/references/"):
        r = client.get(url)
        assert r.status_code == 200, f"{url} returned {r.status_code}"
        assert b"<html" in r.content.lower()
