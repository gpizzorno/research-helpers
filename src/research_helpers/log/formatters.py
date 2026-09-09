"""Custom formatters for console and file output."""

from typing import Any

from colorama import Fore, Style, init
from structlog.types import EventDict

# Initialize colorama for cross-platform color support
init(autoreset=True)


class ColoredConsoleRenderer:
    """Colored console renderer with intuitive formatting."""

    LEVEL_COLORS = {
        'debug': Fore.CYAN,
        'info': Fore.GREEN,
        'warning': Fore.YELLOW,
        'error': Fore.RED,
        'critical': Fore.RED + Style.BRIGHT,
    }

    def __call__(self, _logger: Any, _name: str, event_dict: EventDict) -> str:
        """Render a colored console message."""
        level = event_dict.pop('level', 'info')
        timestamp = event_dict.pop('timestamp', '')
        module = event_dict.pop('module', 'unknown')
        event = event_dict.pop('event', '')

        # Choose color
        color = self.LEVEL_COLORS.get(level, '')

        # Format level
        level_str = f'{color}[{level.upper():8s}]{Style.RESET_ALL}'

        # Format timestamp (just time portion for brevity)
        time_str = timestamp.split('T')[1][:8] if timestamp else '00:00:00'

        # Format module (abbreviate if too long)
        if len(module) > 30:  # noqa: PLR2004
            parts = module.split('.')
            if len(parts) > 2:  # noqa: PLR2004
                module = f'{parts[0]}...{parts[-1]}'
        module_str = f'{Fore.BLUE}{module}{Style.RESET_ALL}'

        # Build message
        parts = [level_str, time_str, module_str, event]

        # Add extra context
        if event_dict:
            context_parts = [f'{k}={v}' for k, v in event_dict.items() if not k.startswith('_')]
            if context_parts:
                parts.append(f'({", ".join(context_parts)})')

        return ' '.join(parts)


class PlainFileRenderer:
    """Plain text renderer for file output (no colors)."""

    def __call__(self, _logger: Any, _name: str, event_dict: EventDict) -> str:
        """Render a plain text message for file output."""
        level = event_dict.pop('level', 'info')
        timestamp = event_dict.pop('timestamp', '')
        module = event_dict.pop('module', 'unknown')
        event = event_dict.pop('event', '')

        # Build message
        parts = [f'[{level.upper():8s}]', timestamp, module, event]

        # Add extra context
        if event_dict:
            context_parts = [f'{k}={v}' for k, v in event_dict.items() if not k.startswith('_')]
            if context_parts:
                parts.append(f'({", ".join(context_parts)})')

        return ' '.join(parts)
