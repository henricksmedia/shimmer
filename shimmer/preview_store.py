"""preview_store.py — now lives in shimmer.api.sessions (the new engine).

This name stays so the 1.x routes and their tests keep working until Step 7
retires the old modules. There is one session store: PREVIEW_STORE is the
new store itself.
"""
from .api.sessions import (MAX_SECONDS_CACHED, SESSION_TTL_SECONDS, SESSIONS,  # noqa: F401
                           Session, SessionStore, clamp_samples_for_preview)

PREVIEW_STORE = SESSIONS
PreviewSession = Session
PreviewStore = SessionStore
