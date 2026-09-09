"""Event rendering for a console or a file."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from colorama import Fore, Style

if TYPE_CHECKING:
    from structlog.types import EventDict

__all__ = ['Renderer']

# a dotted module name longer than this is abbreviated to its first and last components
MAX_MODULE = 30
MIN_PARTS = 2

# 'HH:MM:SS' from an ISO timestamp
CLOCK = 8


class Renderer:
    """Render one event as a line, with any traceback on the lines after it."""

    LEVEL_COLOURS = {
        'debug': Fore.CYAN,
        'info': Fore.GREEN,
        'warning': Fore.YELLOW,
        'error': Fore.RED,
        'critical': Fore.RED + Style.BRIGHT,
    }

    def __init__(self, *, colours: bool = False, clock_only: bool = False) -> None:
        """Create a renderer.

        Arguments:
            colours: colour the level and module.
            clock_only: show the time alone rather than the full timestamp.

        """
        self.colours = colours
        self.clock_only = clock_only

    def __call__(self, _logger: Any, _name: str, event_dict: EventDict) -> str:
        """Render an event."""
        level = str(event_dict.pop('level', 'info'))
        timestamp = str(event_dict.pop('timestamp', ''))
        event = str(event_dict.pop('event', ''))
        # 'module' is set by add_module_name from the logger name
        module = str(event_dict.pop('module', 'unknown'))
        event_dict.pop('logger', None)
        # the traceback goes below the line, not inside its context
        exception = event_dict.pop('exception', None)

        parts = [
            self._level(level),
            self._time(timestamp),
            self._module(module),
            event,
        ]
        context = ', '.join(f'{key}={value}' for key, value in event_dict.items() if not key.startswith('_'))
        if context:
            parts.append(f'({context})')

        line = ' '.join(part for part in parts if part)
        return f'{line}\n{exception}' if exception else line

    def _level(self, level: str) -> str:
        text = f'[{level.upper():8s}]'
        if not self.colours:
            return text
        return f'{self.LEVEL_COLOURS.get(level, "")}{text}{Style.RESET_ALL}'

    def _time(self, timestamp: str) -> str:
        if not timestamp:
            return ''
        if not self.clock_only:
            return timestamp
        # fall back to the whole string if it is not an ISO timestamp
        _, separator, time = timestamp.partition('T')
        return (time if separator else timestamp)[:CLOCK]

    def _module(self, module: str) -> str:
        if len(module) > MAX_MODULE:
            parts = module.split('.')
            if len(parts) > MIN_PARTS:
                module = f'{parts[0]}...{parts[-1]}'
        return f'{Fore.BLUE}{module}{Style.RESET_ALL}' if self.colours else module
