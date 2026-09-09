"""Custom logging handlers."""

import logging
from pathlib import Path


class MultiFileHandler(logging.Handler):
    """Handler that can route logs to different files based on logger name or context."""

    def __init__(self, base_dir: Path, level: str = 'DEBUG'):
        """Initialize the MultiFileHandler."""
        super().__init__(level=getattr(logging, level.upper()))
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

        # Map logger names to specific files
        self._file_mapping: dict[str, Path] = {}

        # Default file for all logs
        self._default_file = self.base_dir / 'app.log'
        self._default_handler = logging.FileHandler(self._default_file, mode='a')
        self._default_handler.setLevel(self.level)

        # Cache of file handlers
        self._handlers: dict[Path, logging.FileHandler] = {self._default_file: self._default_handler}

    def set_target_file(self, logger_name: str, filename: str) -> None:
        """Map a logger name to a specific file."""
        filepath = self.base_dir / filename
        self._file_mapping[logger_name] = filepath

        if filepath not in self._handlers:
            handler = logging.FileHandler(filepath, mode='a')
            handler.setLevel(self.level)
            if self.formatter:
                handler.setFormatter(self.formatter)
            self._handlers[filepath] = handler

    def emit(self, record: logging.LogRecord) -> None:
        """Emit a record to the appropriate file."""
        # Determine target file
        target_file = self._file_mapping.get(record.name, self._default_file)

        # Get or create handler
        if target_file not in self._handlers:
            handler = logging.FileHandler(target_file, mode='a')
            handler.setLevel(self.level)
            if self.formatter:
                handler.setFormatter(self.formatter)
            self._handlers[target_file] = handler

        # Emit to target handler
        self._handlers[target_file].emit(record)

    def setFormatter(self, fmt: logging.Formatter | None) -> None:  # noqa: N802
        """Set formatter for all handlers."""
        super().setFormatter(fmt)
        for handler in self._handlers.values():
            handler.setFormatter(fmt)

    def close(self) -> None:
        """Close all file handlers."""
        for handler in self._handlers.values():
            handler.close()
        super().close()
