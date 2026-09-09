"""Progress bars."""

from __future__ import annotations

import sys
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from tqdm.auto import tqdm as tqdm_auto
from tqdm.contrib.logging import logging_redirect_tqdm

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = ['LoggingTqdm', 'progress']


class LoggingTqdm(tqdm_auto):  # ty: ignore[unsupported-base]
    """A tqdm writing to stdout and sizing itself to the terminal."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Create a progress bar, defaulting to stdout so it shares a stream with log output."""
        kwargs.setdefault('file', sys.stdout)
        kwargs.setdefault('dynamic_ncols', True)
        super().__init__(*args, **kwargs)


@contextmanager
def progress() -> Iterator[None]:
    """Route log output through 'tqdm.write' for the duration."""
    with logging_redirect_tqdm():
        yield
