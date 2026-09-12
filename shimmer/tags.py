"""tags.py — now lives in shimmer.core.tags (the new engine).

This name stays so the 1.x server, the scripts and the tests keep working
until Step 7 retires the old modules. There is one copy of the code.
"""
from .core import tags as _core
from .core.tags import *  # noqa: F401,F403

# The private helpers too, for anything that reaches for them.
globals().update({k: v for k, v in vars(_core).items()
                  if k.startswith("_") and not k.startswith("__")})
