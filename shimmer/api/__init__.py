"""shimmer.api — the web layer of the new engine.

Each module holds the routes for one area and talks to the engine only
through shimmer.core (tests/api/test_api_contract.py). Routes keep the paths
the screens already call (docs/API.md); shimmer/server.py includes each
router as its area moves to the new engine.
"""
