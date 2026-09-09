"""Integration between tqdm progress bars and logging."""

import sys
from typing import Any

from tqdm.auto import tqdm as tqdm_auto


class LoggingTqdm(tqdm_auto):
    """tqdm wrapper that works with logging output.

    Automatically detects Jupyter vs terminal and redirects writes
    to avoid conflicts with log output.
    """

    def __init__(self, *args: Any, **kwargs: Any):
        """Initialize the LoggingTqdm."""
        # Force file to stdout to work with logging
        kwargs.setdefault('file', sys.stdout)
        kwargs.setdefault('dynamic_ncols', True)
        super().__init__(*args, **kwargs)
