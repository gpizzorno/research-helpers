"""Handler for routing records to files by logger name."""

from __future__ import annotations

import logging
from pathlib import Path

__all__ = ['DEFAULT_FILENAME', 'MultiFileHandler']

DEFAULT_FILENAME = 'app.log'


class MultiFileHandler(logging.Handler):
    """Write each record to the file its logger is mapped to or to a shared default."""

    def __init__(self, base_dir: Path | str, level: int = logging.DEBUG) -> None:
        """Create a handler writing under 'base_dir'.

        Arguments:
            base_dir: directory for the log files, created if absent.
            level: minimum level written.

        """
        super().__init__(level=level)
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

        self._targets: dict[str, Path] = {}
        self._default = self.base_dir / DEFAULT_FILENAME
        self._handlers: dict[Path, logging.FileHandler] = {self._default: self._open(self._default)}

    def _open(self, path: Path) -> logging.FileHandler:
        """Return a handler for 'path'."""
        handler = logging.FileHandler(path, mode='a', delay=True)
        handler.setLevel(self.level)
        if self.formatter:
            handler.setFormatter(self.formatter)
        return handler

    def set_target_file(self, logger_name: str, filename: str) -> Path:
        """Route one logger's records to 'filename'.

        Arguments:
            logger_name: the logger to route, as passed to 'get_logger'.
            filename: name of the file, relative to the handler's directory.

        Returns:
            The path records will be written to.

        """
        path = self.base_dir / filename
        self._targets[logger_name] = path
        if path not in self._handlers:
            self._handlers[path] = self._open(path)
        return path

    def emit(self, record: logging.LogRecord) -> None:
        """Write a record to the file its logger is mapped to."""
        self._handlers[self._targets.get(record.name, self._default)].emit(record)

    def setFormatter(self, fmt: logging.Formatter | None) -> None:  # noqa: N802
        """Set the formatter on this handler and every file it writes."""
        super().setFormatter(fmt)
        for handler in self._handlers.values():
            handler.setFormatter(fmt)

    def close(self) -> None:
        """Close every open file."""
        for handler in self._handlers.values():
            handler.close()
        self._handlers.clear()
        super().close()
