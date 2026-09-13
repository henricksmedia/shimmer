"""Moved: Suggested EQ (the Tone step) now lives in
shimmer.core.analyze.tone_plan, and shimmer.core.tone_plan() runs it the way
the engine renders. This name stays, pointing there, until Step 7 deletes
the retired modules (docs/REBUILD-TRACKER.md)."""
from .core.analyze.tone_plan import *  # noqa: F401,F403
