"""Logging configuration and setup."""

import logging
import sys
from contextvars import ContextVar
from pathlib import Path
from typing import Any, TextIO

import structlog
from structlog.types import EventDict, WrappedLogger

from .formatters import ColoredConsoleRenderer, PlainFileRenderer
from .handlers import MultiFileHandler

# Context-local configuration using contextvars
_console_handler_var: ContextVar[logging.StreamHandler[TextIO | Any] | None] = ContextVar(
    'console_handler',
    default=None,
)
_file_handler_var: ContextVar[MultiFileHandler | None] = ContextVar('file_handler', default=None)
_configured_var: ContextVar[bool] = ContextVar('configured', default=False)


def add_module_name(_logger: WrappedLogger, _method_name: str, event_dict: EventDict) -> EventDict:
    """Add module name from logger name."""
    record = event_dict.get('_record')
    if record:
        event_dict['module'] = record.name
    return event_dict


def setup_logging(
    *,
    console_level: str = 'INFO',
    file_level: str = 'DEBUG',
    log_dir: Path | str | None = None,
    enable_colors: bool = True,
    jupyter_mode: bool = False,  # noqa: ARG001
) -> None:
    """Set up unified logging system.

    Arguments:
        console_level: Minimum level for console output (DEBUG, INFO, WARNING, ERROR)
        file_level: Minimum level for file output
        log_dir: Directory for log files (None = no file logging)
        enable_colors: Whether to use colors in console output
        jupyter_mode: Whether running in Jupyter (affects tqdm behavior)

    """
    _console_handler = _console_handler_var.get()
    _file_handler = _file_handler_var.get()
    _configured = _configured_var.get()

    if _configured:
        return

    # Setup stdlib logging
    logging.basicConfig(
        format='%(message)s',
        level=logging.DEBUG,
        stream=sys.stdout,
    )

    processors: list[structlog.types.Processor] = [
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt='iso', utc=True),
        add_module_name,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    # Console renderer
    console_renderer = ColoredConsoleRenderer() if enable_colors else structlog.dev.ConsoleRenderer(colors=False)

    # Setup console handler
    _console_handler = logging.StreamHandler(sys.stdout)
    _console_handler.setLevel(getattr(logging, console_level.upper()))
    _console_handler_var.set(_console_handler)

    # Setup file handler if requested
    if log_dir:
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)
        _file_handler = MultiFileHandler(base_dir=log_path, level=file_level)

    # Configure structlog
    structlog.configure(
        processors=[*processors, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Setup formatters
    console_formatter = structlog.stdlib.ProcessorFormatter(
        processor=console_renderer,
        foreign_pre_chain=processors,
    )

    if _file_handler:
        file_formatter = structlog.stdlib.ProcessorFormatter(
            processor=PlainFileRenderer(),
            foreign_pre_chain=processors,
        )
        _file_handler.setFormatter(file_formatter)
        _file_handler_var.set(_file_handler)

    _console_handler.setFormatter(console_formatter)

    # Attach handlers to root logger
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(_console_handler)
    if _file_handler:
        root_logger.addHandler(_file_handler)

    _configured = True


def get_logger(name: str | None = None, **context: Any) -> structlog.stdlib.BoundLogger:
    """Get a logger instance with optional context.

    Arguments:
        name: Logger name (typically __name__)
        **context: Additional context fields (e.g., task="entity_resolution")

    Returns:
        Configured logger instance

    """
    _configured = _configured_var.get()

    if not _configured:
        setup_logging()

    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)

    if context:
        logger = logger.bind(**context)

    return logger


def set_log_file(logger: structlog.stdlib.BoundLogger, filename: str) -> None:
    """Set a specific log file for this logger's output.

    Arguments:
        logger: Logger instance
        filename: Name of the log file (relative to log_dir)

    """
    _file_handler = _file_handler_var.get()
    if _file_handler and isinstance(_file_handler, MultiFileHandler):
        _file_handler.set_target_file(logger._context.get('_logger').name, filename)  # type: ignore [union-attr]  # noqa: SLF001
        _file_handler_var.set(_file_handler)
