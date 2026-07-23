"""Shimmer — clean AI-generation artifacts, then master for release.

Importing this package installs the Windows WMI workaround before anything
pulls in scipy/numpy. `_winfix` must come first; see its docstring.
"""

from . import _winfix  # noqa: F401  # must precede any scipy/numpy import

__version__ = "1.1.1"
__all__ = ["__version__"]
