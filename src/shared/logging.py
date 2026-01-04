from __future__ import annotations

from rich.console import Console
from rich.panel import Panel

console = Console()
DEBUG_MODE = False


def set_debug_mode(enabled: bool) -> None:
    """Enable or disable debug logging.

    Args:
        enabled: True to enable debug logs.
    """
    global DEBUG_MODE
    DEBUG_MODE = enabled


def debug_log(title: str, content: str, style: str = 'cyan') -> None:
    """Print debug info if debug mode is enabled.

    Args:
        title: Panel title.
        content: Panel body content.
        style: Rich color style for the panel.
    """
    if DEBUG_MODE:
        console.print(
            Panel(
                content,
                title=f'🔍 {title}',
                border_style=style,
                padding=(1, 2),
            )
        )
