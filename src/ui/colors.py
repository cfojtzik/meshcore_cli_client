"""Curses color definitions and setup."""

import curses
from typing import Optional, Set

COLOR_NORMAL = 1
COLOR_HEADER = 2
COLOR_SELECTED = 3
COLOR_SUCCESS = 4
COLOR_WARNING = 5
COLOR_ERROR = 6
COLOR_STATUS = 7
COLOR_DIM = 8

# ``None`` means initialization has not run (useful for embedders/tests).
_initialized_pairs: Optional[Set[int]] = None


def init_colors() -> None:
    """Initialize color pairs, including terminals without default colors."""
    global _initialized_pairs
    _initialized_pairs = set()
    if not curses.has_colors():
        return

    try:
        curses.start_color()
    except curses.error:
        return

    background = curses.COLOR_BLACK
    try:
        curses.use_default_colors()
        background = -1
    except curses.error:
        # Some valid monochrome/limited color terminals reject -1 colors.
        pass

    pairs = [
        (COLOR_NORMAL, -1 if background == -1 else curses.COLOR_WHITE, background),
        (COLOR_HEADER, curses.COLOR_CYAN, background),
        (COLOR_SELECTED, curses.COLOR_BLACK, curses.COLOR_CYAN),
        (COLOR_SUCCESS, curses.COLOR_GREEN, background),
        (COLOR_WARNING, curses.COLOR_YELLOW, background),
        (COLOR_ERROR, curses.COLOR_RED, background),
        (COLOR_STATUS, curses.COLOR_BLACK, curses.COLOR_WHITE),
        (COLOR_DIM, curses.COLOR_WHITE, background),
    ]
    for pair_id, foreground, bg in pairs:
        try:
            curses.init_pair(pair_id, foreground, bg)
            _initialized_pairs.add(pair_id)
        except curses.error:
            # Pair count/color support varies; unaffected pairs remain usable.
            continue


def get_color(color_id: int) -> int:
    """Return a usable color attribute and a reverse-video selection fallback."""
    selection_attr = curses.A_REVERSE if color_id == COLOR_SELECTED else curses.A_NORMAL
    try:
        colors_available = curses.has_colors()
    except curses.error:
        colors_available = False
    if colors_available and (_initialized_pairs is None or color_id in _initialized_pairs):
        try:
            return curses.color_pair(color_id) | selection_attr
        except curses.error:
            pass
    return selection_attr
