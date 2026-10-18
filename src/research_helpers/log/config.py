"""Set up structured logging over the standard library's logging module."""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING, Any, TextIO

import structlog

from research_helpers.log.formatters import Renderer
from research_helpers.log.handlers import MultiFileHandler
from research_helpers.project import current_project, resolve

if TYPE_CHECKING:
    from pathlib import Path

    from structlog.types import EventDict, WrappedLogger

__all__ = ['add_module_name', 'get_logger', 'reset_logging', 'set_log_file', 'setup_logging']

# handlers installed by this module
_console_handler: logging.Handler | None = None
_file_handler: MultiFileHandler | None = None
_configured = False

# loggers requested through get_logger take the project's level
# every other logger inherits the root's, which is set to the library level
_project_loggers: set[str] = set()
_project_level = logging.NOTSET


def _level(value: int | str) -> int:
    """Return a logging level as an int, whether given as one or as a name.

    Raises:
        ValueError: if the name is not a level.

    """
    if isinstance(value, int):
        return value
    # getLevelName() answers 'Level TRACE' for an unknown name rather than failing
    levels = logging.getLevelNamesMapping()
    name = value.upper()
    if name not in levels:
        msg = f'{value!r} is not a logging level. Expected one of {", ".join(levels)}, or an int'
        raise ValueError(msg)
    return levels[name]


def _wants_colour(choice: str, stream: TextIO) -> bool:
    """Decide whether to colour output, given the setting and where it is going."""
    if choice == 'never':
        return False
    if choice == 'always':
        return True
    return hasattr(stream, 'isatty') and stream.isatty()


def add_module_name(_logger: WrappedLogger, _method_name: str, event_dict: EventDict) -> EventDict:
    """Record which logger an event came from."""
    record = event_dict.get('_record')
    name = record.name if record is not None else event_dict.get('logger')
    if name:
        event_dict['module'] = name
    return event_dict


def _processors() -> list[structlog.types.Processor]:
    """Return the chain shared by console output, file output, and foreign records.

    It holds no level filter: a foreign record reaches the chain with no logger to ask (structlog
    passes None), and the standard library has already filtered it by level by then.
    """
    return [
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt='iso', utc=True),
        add_module_name,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]


def setup_logging(  # noqa: PLR0913
    *,
    console_level: int | str | None = None,
    file_level: int | str | None = None,
    library_level: int | str | None = None,
    directory: Path | str | None = None,
    colour: str | None = None,
    stream: TextIO | None = None,
) -> None:
    """Configure logging, replacing any configuration this module made earlier.

    Arguments:
        console_level: minimum level shown on the console.
        file_level: minimum level written to file.
        library_level: minimum level of every logger not obtained from 'get_logger'.
            A library given a level of its own with 'logging.getLogger(name).setLevel' keeps it.
        directory: where to write log files. None means console output only.
        colour: 'auto' to colour only a terminal, or 'always' / 'never'.
        stream: where console output goes, defaulting to stdout.

    """
    global _console_handler, _file_handler, _configured, _project_level  # noqa: PLW0603

    settings = resolve(
        current_project().log,
        console_level=console_level,
        file_level=file_level,
        library_level=library_level,
        directory=directory,
        colour=colour,
    )
    console = _level(settings.console_level)
    to_file = _level(settings.file_level)
    libraries = _level(settings.library_level)
    output = stream if stream is not None else sys.stdout

    reset_logging()

    structlog.configure(
        # level filtering here only: this chain runs for structlog's own events
        processors=[
            structlog.stdlib.filter_by_level,
            *_processors(),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    colours = _wants_colour(settings.colour, output)
    if colours and sys.platform == 'win32':  # pragma: no cover - platform specific
        from colorama import just_fix_windows_console  # noqa: PLC0415

        just_fix_windows_console()

    _console_handler = logging.StreamHandler(output)
    _console_handler.setLevel(console)
    _console_handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processor=Renderer(colours=colours, clock_only=True),
            foreign_pre_chain=_processors(),
        ),
    )

    root = logging.getLogger()
    root.addHandler(_console_handler)

    if settings.directory is not None:
        _file_handler = MultiFileHandler(settings.directory, level=to_file)
        _file_handler.setFormatter(
            structlog.stdlib.ProcessorFormatter(
                processor=Renderer(),
                foreign_pre_chain=_processors(),
            ),
        )
        root.addHandler(_file_handler)

    root.setLevel(libraries)
    _project_level = min(console, to_file) if settings.directory is not None else console
    # loggers obtained before this call, e.g. at import time, take the levels
    for name in tuple(_project_loggers):
        logging.getLogger(name).setLevel(_project_level)
    _configured = True


def reset_logging() -> None:
    """Remove the handlers this module installed, and the levels assigned to loggers from 'get_logger'."""
    global _console_handler, _file_handler, _configured, _project_level  # noqa: PLW0603

    root = logging.getLogger()
    for handler in (_console_handler, _file_handler):
        if handler is not None:
            root.removeHandler(handler)
            handler.close()
    _console_handler = _file_handler = None
    # the names are kept, so that the next setup gives them the project's level again
    for name in tuple(_project_loggers):
        logging.getLogger(name).setLevel(logging.NOTSET)
    _project_level = logging.NOTSET
    _configured = False


def get_logger(name: str | None = None, **context: Any) -> structlog.stdlib.BoundLogger:
    """Return a logger at the project's level.

    Arguments:
        name: logger name, normally '__name__'. None names the calling module.
        **context: fields bound to every event from this logger, e.g. task='resolution'.

    Returns:
        The logger.

    """
    if not _configured:
        setup_logging()

    if name is None:
        # the name structlog would infer at the first event
        name = str(sys._getframe(1).f_globals.get('__name__', '__main__'))  # noqa: SLF001
    _project_loggers.add(name)
    logging.getLogger(name).setLevel(_project_level)

    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger.bind(**context) if context else logger


def set_log_file(name: str, filename: str) -> Path:
    """Route one logger's records to their own file.

    Arguments:
        name: the logger name, as passed to 'get_logger' (normally a module's '__name__').
        filename: the file, relative to the configured log directory.

    Returns:
        The path records will be written to.

    Raises:
        RuntimeError: if file logging is not configured.

    """
    if _file_handler is None:
        msg = 'no log directory is configured. Pass directory= to setup_logging() or set it in pyproject.toml'
        raise RuntimeError(msg)
    return _file_handler.set_target_file(name, filename)
