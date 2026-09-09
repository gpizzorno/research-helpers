"""Helpers for managing a code-intensive research project and its accompanying paper.

Submodules are deliberately not imported here. Most of them carry optional dependencies
(matplotlib and seaborn for figures, structlog for logging), so importing this package must
stay free of them.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version('research-helpers')
except PackageNotFoundError:  # not installed, e.g. running from a source checkout
    __version__ = '0.0.0.dev0'

__all__ = ['__version__']
