"""Reusable curses UI widgets and helper functions."""

import curses
import textwrap
from typing import List, Optional, Tuple, Union

from .colors import (
    COLOR_DIM,
    COLOR_ERROR,
    COLOR_HEADER,
    COLOR_NORMAL,
    COLOR_SELECTED,
    COLOR_STATUS,
    get_color,
)

Key = Union[int, str]


def read_key(win: curses.window) -> Optional[Key]:
    """Read a key with ``get_wch`` so printable Unicode is not decoded bytewise.

    ASCII characters are normalized to their traditional curses integer codes;
    non-ASCII printable characters remain one-character strings.  ``None`` is
    returned when a window using a timeout has no input available.
    """
    try:
        key = win.get_wch()
    except AttributeError:  # Small fake windows and very old Python builds.
        key = win.getch()
    except curses.error:
        return None

    if key == -1:
        return None
    if isinstance(key, str) and len(key) == 1 and ord(key) < 128:
        return ord(key)
    return key


def key_to_text(key: Optional[Key]) -> Optional[str]:
    """Return a printable character for a key, excluding curses function keys."""
    if isinstance(key, str):
        return key if len(key) == 1 and key.isprintable() else None
    if isinstance(key, int) and (32 <= key <= 126 or 160 <= key <= 255):
        char = chr(key)
        return char if char.isprintable() else None
    return None


def safe_curs_set(visibility: int) -> None:
    """Set cursor visibility on terminals which support it."""
    try:
        curses.curs_set(visibility)
    except curses.error:
        pass


def safe_move(win: curses.window, y: int, x: int) -> None:
    """Move the hardware cursor only when the position is inside the window."""
    max_y, max_x = win.getmaxyx()
    if 0 <= y < max_y and 0 <= x < max_x:
        try:
            win.move(y, x)
        except curses.error:
            pass


def ensure_visible(
    selected: int,
    offset: int,
    visible_count: int,
    item_count: Optional[int] = None,
) -> int:
    """Return a scroll offset which contains *selected* and stays in bounds."""
    if visible_count <= 0:
        return 0
    selected = max(0, selected)
    if item_count is not None:
        selected = min(selected, max(0, item_count - 1))
    max_offset = max(0, (item_count - visible_count) if item_count is not None else selected)
    start = max(0, min(offset, max_offset))
    if selected < start:
        start = selected
    elif selected >= start + visible_count:
        start = selected - visible_count + 1
    if item_count is not None:
        start = min(start, max(0, item_count - visible_count))
    return max(0, start)


def wrap_text_lines(text: str, width: int) -> List[str]:
    """Wrap long logical lines, including unbroken URIs, without dropping lines."""
    if width <= 0:
        return []
    logical_lines = text.splitlines() or [""]
    wrapped: List[str] = []
    for line in logical_lines:
        if not line:
            wrapped.append("")
            continue
        wrapped.extend(
            textwrap.wrap(
                line,
                width=width,
                break_long_words=True,
                break_on_hyphens=False,
                replace_whitespace=False,
            )
            or [""]
        )
    return wrapped


def dialog_geometry(max_y: int, max_x: int, desired_w: int, desired_h: int) -> Tuple[int, int, int, int]:
    """Calculate a bounded ``(y, x, height, width)`` even for tiny windows."""
    if max_y <= 0 or max_x <= 0:
        return 0, 0, 0, 0
    width = min(desired_w, max_x - 4 if max_x > 4 else max_x)
    height = min(desired_h, max_y - 2 if max_y > 2 else max_y)
    width = max(1, width)
    height = max(1, height)
    return (max_y - height) // 2, (max_x - width) // 2, height, width


def safe_addstr(win: curses.window, y: int, x: int, text: str, attr: int = 0) -> None:
    """Safely write a string to a window, clipping to prevent curses.error."""
    max_y, max_x = win.getmaxyx()
    if y < 0 or y >= max_y or x < 0 or x >= max_x:
        return

    available_width = max_x - x
    if available_width <= 0:
        return

    to_write = text[:available_width]
    try:
        win.addstr(y, x, to_write, attr)
    except curses.error:
        pass


def draw_header(stdscr: curses.window, title: str, subtitle: str = "") -> None:
    """Draw top header banner."""
    _, max_x = stdscr.getmaxyx()
    safe_addstr(stdscr, 0, 0, " " * max_x, get_color(COLOR_SELECTED))

    brand = " ⚡ MeshCore Terminal Client "
    safe_addstr(stdscr, 0, 0, brand, get_color(COLOR_SELECTED) | curses.A_BOLD)

    sub = f"[{title}] {subtitle}" if subtitle else f"[{title}]"
    if len(brand) + len(sub) + 2 < max_x:
        safe_addstr(stdscr, 0, max_x - len(sub) - 2, sub, get_color(COLOR_SELECTED))


def draw_status_bar(stdscr: curses.window, left_text: str, right_text: str = "") -> None:
    """Draw bottom status bar."""
    max_y, max_x = stdscr.getmaxyx()
    y = max_y - 1
    safe_addstr(stdscr, y, 0, " " * max(0, max_x - 1), get_color(COLOR_STATUS))
    safe_addstr(stdscr, y, 1, left_text, get_color(COLOR_STATUS))
    if right_text:
        x_right = max(0, max_x - len(right_text) - 2)
        safe_addstr(stdscr, y, x_right, right_text, get_color(COLOR_STATUS) | curses.A_BOLD)


def draw_box(stdscr: curses.window, y: int, x: int, h: int, w: int, title: str = "") -> None:
    """Draw border box with title if the complete, sensible box fits."""
    max_y, max_x = stdscr.getmaxyx()
    if h < 2 or w < 2 or y < 0 or x < 0 or y + h > max_y or x + w > max_x:
        return

    for col in range(x, x + w):
        safe_addstr(stdscr, y, col, "─", get_color(COLOR_DIM))
        safe_addstr(stdscr, y + h - 1, col, "─", get_color(COLOR_DIM))

    for row in range(y, y + h):
        safe_addstr(stdscr, row, x, "│", get_color(COLOR_DIM))
        safe_addstr(stdscr, row, x + w - 1, "│", get_color(COLOR_DIM))

    safe_addstr(stdscr, y, x, "┌", get_color(COLOR_DIM))
    safe_addstr(stdscr, y, x + w - 1, "┐", get_color(COLOR_DIM))
    safe_addstr(stdscr, y + h - 1, x, "└", get_color(COLOR_DIM))
    safe_addstr(stdscr, y + h - 1, x + w - 1, "┘", get_color(COLOR_DIM))

    if title and w > 4:
        safe_addstr(stdscr, y, x + 2, f" {title} "[: w - 4], get_color(COLOR_HEADER) | curses.A_BOLD)


def prompt_input(stdscr: curses.window, title: str, label: str, default: str = "") -> Optional[str]:
    """Modal Unicode text input dialog. Returns string or None if cancelled."""
    safe_curs_set(1)
    buffer = list(default)
    cursor_pos = len(buffer)

    try:
        while True:
            max_y, max_x = stdscr.getmaxyx()
            dlg_y, dlg_x, dlg_h, dlg_w = dialog_geometry(max_y, max_x, 60, 7)
            if dlg_h == 0 or dlg_w == 0:
                return None

            for i in range(dlg_h):
                safe_addstr(stdscr, dlg_y + i, dlg_x, " " * dlg_w, get_color(COLOR_NORMAL))

            draw_box(stdscr, dlg_y, dlg_x, dlg_h, dlg_w, title)
            safe_addstr(stdscr, dlg_y + 2, dlg_x + 2, label, get_color(COLOR_NORMAL))

            field_w = max(1, dlg_w - 6)
            if dlg_w >= 6:
                safe_addstr(stdscr, dlg_y + 3, dlg_x + 2, "[" + " " * max(0, field_w - 2) + "]", get_color(COLOR_DIM))
            input_text = "".join(buffer)
            visible_w = max(1, field_w - 2)
            start = max(0, cursor_pos - visible_w + 1) if cursor_pos >= visible_w else 0
            visible_text = input_text[start : start + visible_w]
            safe_addstr(stdscr, dlg_y + 3, dlg_x + 3, visible_text, get_color(COLOR_NORMAL) | curses.A_BOLD)

            safe_addstr(
                stdscr,
                dlg_y + 5,
                dlg_x + 2,
                "[Enter] Bestätigen   [Esc] Abbrechen",
                get_color(COLOR_DIM),
            )

            safe_move(stdscr, dlg_y + 3, dlg_x + 3 + min(visible_w - 1, cursor_pos - start))
            stdscr.refresh()

            key = read_key(stdscr)
            if key is None or key == curses.KEY_RESIZE:
                continue
            if key == 27:
                return None
            if key in (10, 13, curses.KEY_ENTER):
                return "".join(buffer).strip()
            if key in (curses.KEY_BACKSPACE, 127, 8):
                if cursor_pos > 0:
                    buffer.pop(cursor_pos - 1)
                    cursor_pos -= 1
            elif key == curses.KEY_DC:
                if cursor_pos < len(buffer):
                    buffer.pop(cursor_pos)
            elif key == curses.KEY_LEFT:
                cursor_pos = max(0, cursor_pos - 1)
            elif key == curses.KEY_RIGHT:
                cursor_pos = min(len(buffer), cursor_pos + 1)
            elif key == curses.KEY_HOME:
                cursor_pos = 0
            elif key == curses.KEY_END:
                cursor_pos = len(buffer)
            else:
                char = key_to_text(key)
                if char is not None:
                    buffer.insert(cursor_pos, char)
                    cursor_pos += 1
    finally:
        safe_curs_set(0)


def show_message(stdscr: curses.window, title: str, message: str, is_error: bool = False) -> None:
    """Modal, wrapping and scrollable message dialog."""
    safe_curs_set(0)
    offset = 0

    while True:
        max_y, max_x = stdscr.getmaxyx()
        dlg_y, dlg_x, dlg_h, dlg_w = dialog_geometry(max_y, max_x, 70, max_y)
        content_w = max(1, dlg_w - 4)
        content_h = max(0, dlg_h - 4)
        lines = wrap_text_lines(message.strip(), content_w) or [""]
        max_offset = max(0, len(lines) - content_h)
        offset = max(0, min(offset, max_offset))

        for i in range(dlg_h):
            safe_addstr(stdscr, dlg_y + i, dlg_x, " " * dlg_w, get_color(COLOR_NORMAL))
        draw_box(stdscr, dlg_y, dlg_x, dlg_h, dlg_w, title)

        for idx, line in enumerate(lines[offset : offset + content_h]):
            safe_addstr(stdscr, dlg_y + 2 + idx, dlg_x + 2, line, get_color(COLOR_NORMAL))

        footer = "[↑/↓/PgUp/PgDn] Scrollen | [Enter/Esc] Schließen"
        safe_addstr(stdscr, dlg_y + dlg_h - 2, dlg_x + 2, footer, get_color(COLOR_DIM))
        stdscr.refresh()

        key = read_key(stdscr)
        if key is None or key == curses.KEY_RESIZE:
            continue
        if key in (10, 13, 27, ord(" "), ord("q"), ord("Q")):
            break
        if key in (curses.KEY_UP, ord("k")):
            offset = max(0, offset - 1)
        elif key in (curses.KEY_DOWN, ord("j")):
            offset = min(max_offset, offset + 1)
        elif key == curses.KEY_PPAGE:
            offset = max(0, offset - max(1, content_h))
        elif key == curses.KEY_NPAGE:
            offset = min(max_offset, offset + max(1, content_h))
        elif key == curses.KEY_HOME:
            offset = 0
        elif key == curses.KEY_END:
            offset = max_offset


def prompt_confirm(stdscr: curses.window, title: str, question: str) -> bool:
    """Modal yes/no confirmation dialog with monochrome-visible selection."""
    safe_curs_set(0)
    selected = True

    while True:
        max_y, max_x = stdscr.getmaxyx()
        dlg_y, dlg_x, dlg_h, dlg_w = dialog_geometry(max_y, max_x, 60, 7)

        for i in range(dlg_h):
            safe_addstr(stdscr, dlg_y + i, dlg_x, " " * dlg_w, get_color(COLOR_NORMAL))
        draw_box(stdscr, dlg_y, dlg_x, dlg_h, dlg_w, title)
        safe_addstr(stdscr, dlg_y + 2, dlg_x + 2, question, get_color(COLOR_NORMAL) | curses.A_BOLD)

        yes_attr = get_color(COLOR_SELECTED) | curses.A_REVERSE if selected else get_color(COLOR_NORMAL)
        no_attr = get_color(COLOR_SELECTED) | curses.A_REVERSE if not selected else get_color(COLOR_NORMAL)
        safe_addstr(stdscr, dlg_y + 4, dlg_x + 10, "  [ Ja ]  ", yes_attr)
        safe_addstr(stdscr, dlg_y + 4, dlg_x + 26, "  [ Nein ]  ", no_attr)

        stdscr.refresh()
        key = read_key(stdscr)
        if key is None or key == curses.KEY_RESIZE:
            continue
        if key in (curses.KEY_LEFT, curses.KEY_RIGHT, ord("\t")):
            selected = not selected
        elif key in (ord("j"), ord("J"), ord("y"), ord("Y")):
            return True
        elif key in (ord("n"), ord("N"), 27):
            return False
        elif key in (10, 13, curses.KEY_ENTER, ord(" ")):
            return selected


def display_scrollable_text(stdscr: curses.window, title: str, text: str) -> None:
    """Display long text with wrapping, resize handling and scroll support."""
    safe_curs_set(0)
    offset = 0

    while True:
        max_y, max_x = stdscr.getmaxyx()
        stdscr.clear()
        view_h = max(0, max_y - 3)
        content_w = max(1, max_x - 4)
        content_h = max(0, view_h - 2)
        lines = wrap_text_lines(text or "(Keine Daten vorhanden)", content_w) or [""]
        max_offset = max(0, len(lines) - content_h)
        offset = max(0, min(offset, max_offset))

        draw_header(stdscr, title, f"Zeilen: {len(lines)}")
        draw_status_bar(
            stdscr,
            "[↑/↓/PgUp/PgDn/Home/End] Scrollen | [Esc/q/Enter] Zurück",
            f"Zeile {min(len(lines), offset + 1)}/{len(lines)}",
        )
        draw_box(stdscr, 1, 0, view_h, max_x, title)
        for idx, line in enumerate(lines[offset : offset + content_h]):
            safe_addstr(stdscr, 2 + idx, 2, line, get_color(COLOR_NORMAL))

        stdscr.refresh()
        key = read_key(stdscr)
        if key is None or key == curses.KEY_RESIZE:
            continue
        if key in (27, ord("q"), ord("Q"), 10, 13, curses.KEY_ENTER):
            break
        if key == curses.KEY_UP:
            offset = max(0, offset - 1)
        elif key == curses.KEY_DOWN:
            offset = min(max_offset, offset + 1)
        elif key in (curses.KEY_PPAGE, ord("b")):
            offset = max(0, offset - max(1, content_h))
        elif key in (curses.KEY_NPAGE, ord(" ")):
            offset = min(max_offset, offset + max(1, content_h))
        elif key == curses.KEY_HOME:
            offset = 0
        elif key == curses.KEY_END:
            offset = max_offset
