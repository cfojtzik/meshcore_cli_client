"""Curses color definitions and setup."""

import curses

COLOR_NORMAL = 1
COLOR_HEADER = 2
COLOR_SELECTED = 3
COLOR_SUCCESS = 4
COLOR_WARNING = 5
COLOR_ERROR = 6
COLOR_STATUS = 7
COLOR_DIM = 8


def init_colors() -> None:
    """Initialize curses color pairs safely."""
    if not curses.has_colors():
        return

    curses.start_color()
    curses.use_default_colors()

    # Pair 1: Normal text
    curses.init_pair(COLOR_NORMAL, -1, -1)

    # Pair 2: Header / Brand
    curses.init_pair(COLOR_HEADER, curses.COLOR_CYAN, -1)

    # Pair 3: Selected menu item
    curses.init_pair(COLOR_SELECTED, curses.COLOR_BLACK, curses.COLOR_CYAN)

    # Pair 4: Success / Online
    curses.init_pair(COLOR_SUCCESS, curses.COLOR_GREEN, -1)

    # Pair 5: Warning
    curses.init_pair(COLOR_WARNING, curses.COLOR_YELLOW, -1)

    # Pair 6: Error / Offline
    curses.init_pair(COLOR_ERROR, curses.COLOR_RED, -1)

    # Pair 7: Status bar
    curses.init_pair(COLOR_STATUS, curses.COLOR_BLACK, curses.COLOR_WHITE)

    # Pair 8: Dim / Borders
    curses.init_pair(COLOR_DIM, curses.COLOR_WHITE, -1)


def get_color(color_id: int) -> int:
    """Return color attribute or 0 if terminal has no color support."""
    if curses.has_colors():
        return curses.color_pair(color_id)
    return curses.A_NORMAL
