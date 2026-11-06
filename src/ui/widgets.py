"""Reusable curses UI widgets and helper functions."""

import curses
from typing import List, Optional

from .colors import (
    COLOR_DIM,
    COLOR_ERROR,
    COLOR_HEADER,
    COLOR_NORMAL,
    COLOR_SELECTED,
    COLOR_STATUS,
    COLOR_SUCCESS,
    COLOR_WARNING,
    get_color,
)


def safe_addstr(win: curses.window, y: int, x: int, text: str, attr: int = 0) -> None:
    """Safely write a string to a window, clipping to prevent curses.error."""
    max_y, max_x = win.getmaxyx()
    if y < 0 or y >= max_y or x < 0 or x >= max_x:
        return

    # Maximum length that fits on this line
    available_width = max_x - x
    if available_width <= 0:
        return

    to_write = text[:available_width]
    # If writing to the very bottom-right corner, curses might raise an error on write-and-advance
    try:
        win.addstr(y, x, to_write, attr)
    except curses.error:
        pass


def draw_header(stdscr: curses.window, title: str, subtitle: str = "") -> None:
    """Draw top header banner."""
    max_y, max_x = stdscr.getmaxyx()
    header_bar = " " * max_x
    safe_addstr(stdscr, 0, 0, header_bar, get_color(COLOR_SELECTED))
    
    brand = " ⚡ MeshCore Terminal Client "
    safe_addstr(stdscr, 0, 0, brand, get_color(COLOR_SELECTED) | curses.A_BOLD)
    
    sub = f"[{title}] {subtitle}" if subtitle else f"[{title}]"
    if len(brand) + len(sub) + 2 < max_x:
        safe_addstr(stdscr, 0, max_x - len(sub) - 2, sub, get_color(COLOR_SELECTED))


def draw_status_bar(stdscr: curses.window, left_text: str, right_text: str = "") -> None:
    """Draw bottom status bar."""
    max_y, max_x = stdscr.getmaxyx()
    y = max_y - 1
    safe_addstr(stdscr, y, 0, " " * (max_x - 1), get_color(COLOR_STATUS))
    safe_addstr(stdscr, y, 1, left_text, get_color(COLOR_STATUS))
    if right_text:
        x_right = max(0, max_x - len(right_text) - 2)
        safe_addstr(stdscr, y, x_right, right_text, get_color(COLOR_STATUS) | curses.A_BOLD)


def draw_box(stdscr: curses.window, y: int, x: int, h: int, w: int, title: str = "") -> None:
    """Draw border box with title."""
    max_y, max_x = stdscr.getmaxyx()
    if y + h > max_y or x + w > max_x:
        return

    # Horizontal lines
    for col in range(x, x + w):
        safe_addstr(stdscr, y, col, "─", get_color(COLOR_DIM))
        safe_addstr(stdscr, y + h - 1, col, "─", get_color(COLOR_DIM))

    # Vertical lines
    for row in range(y, y + h):
        safe_addstr(stdscr, row, x, "│", get_color(COLOR_DIM))
        safe_addstr(stdscr, row, x + w - 1, "│", get_color(COLOR_DIM))

    # Corners
    safe_addstr(stdscr, y, x, "┌", get_color(COLOR_DIM))
    safe_addstr(stdscr, y, x + w - 1, "┐", get_color(COLOR_DIM))
    safe_addstr(stdscr, y + h - 1, x, "└", get_color(COLOR_DIM))
    safe_addstr(stdscr, y + h - 1, x + w - 1, "┘", get_color(COLOR_DIM))

    if title:
        t_str = f" {title} "
        safe_addstr(stdscr, y, x + 2, t_str[: w - 4], get_color(COLOR_HEADER) | curses.A_BOLD)


def prompt_input(stdscr: curses.window, title: str, label: str, default: str = "") -> Optional[str]:
    """Modal text input dialog. Returns string or None if cancelled."""
    curses.curs_set(1)
    max_y, max_x = stdscr.getmaxyx()

    dlg_w = min(60, max_x - 4)
    dlg_h = 7
    dlg_y = max(1, (max_y - dlg_h) // 2)
    dlg_x = max(1, (max_x - dlg_w) // 2)

    buffer = list(default)
    cursor_pos = len(buffer)

    while True:
        # Clear dialog area
        for i in range(dlg_h):
            safe_addstr(stdscr, dlg_y + i, dlg_x, " " * dlg_w, get_color(COLOR_NORMAL))

        draw_box(stdscr, dlg_y, dlg_x, dlg_h, dlg_w, title)
        safe_addstr(stdscr, dlg_y + 2, dlg_x + 2, label[: dlg_w - 4], get_color(COLOR_NORMAL))

        # Input field box
        field_w = dlg_w - 6
        safe_addstr(stdscr, dlg_y + 3, dlg_x + 2, "[" + " " * (field_w - 2) + "]", get_color(COLOR_DIM))
        input_text = "".join(buffer)
        visible_text = input_text[-(field_w - 2):] if len(input_text) > (field_w - 2) else input_text
        safe_addstr(stdscr, dlg_y + 3, dlg_x + 3, visible_text, get_color(COLOR_NORMAL) | curses.A_BOLD)

        safe_addstr(
            stdscr,
            dlg_y + 5,
            dlg_x + 2,
            "[Enter] Bestätigen   [Esc] Abbrechen",
            get_color(COLOR_DIM),
        )

        # Place hardware cursor
        curr_x = dlg_x + 3 + min(cursor_pos, field_w - 3)
        stdscr.move(dlg_y + 3, curr_x)
        stdscr.refresh()

        key = stdscr.getch()
        if key in (27,):  # ESC
            curses.curs_set(0)
            return None
        elif key in (10, 13, curses.KEY_ENTER):  # Enter
            curses.curs_set(0)
            return "".join(buffer).strip()
        elif key in (curses.KEY_BACKSPACE, 127, 8):
            if cursor_pos > 0:
                buffer.pop(cursor_pos - 1)
                cursor_pos -= 1
        elif key == curses.KEY_DC:  # Delete
            if cursor_pos < len(buffer):
                buffer.pop(cursor_pos)
        elif key == curses.KEY_LEFT:
            if cursor_pos > 0:
                cursor_pos -= 1
        elif key == curses.KEY_RIGHT:
            if cursor_pos < len(buffer):
                cursor_pos += 1
        elif 32 <= key <= 126:  # Printable ASCII
            buffer.insert(cursor_pos, chr(key))
            cursor_pos += 1


def show_message(stdscr: curses.window, title: str, message: str, is_error: bool = False) -> None:
    """Modal popup dialog to display message/alert."""
    curses.curs_set(0)
    lines = message.strip().splitlines()
    max_y, max_x = stdscr.getmaxyx()

    dlg_w = min(70, max_x - 4)
    dlg_h = min(len(lines) + 6, max_y - 2)
    dlg_y = max(1, (max_y - dlg_h) // 2)
    dlg_x = max(1, (max_x - dlg_w) // 2)

    color_title = COLOR_ERROR if is_error else COLOR_HEADER

    while True:
        for i in range(dlg_h):
            safe_addstr(stdscr, dlg_y + i, dlg_x, " " * dlg_w, get_color(COLOR_NORMAL))

        draw_box(stdscr, dlg_y, dlg_x, dlg_h, dlg_w, title)

        content_lines = lines[: dlg_h - 4]
        for idx, line in enumerate(content_lines):
            safe_addstr(stdscr, dlg_y + 2 + idx, dlg_x + 2, line[: dlg_w - 4], get_color(COLOR_NORMAL))

        safe_addstr(
            stdscr,
            dlg_y + dlg_h - 2,
            dlg_x + 2,
            "Drücke [Enter] oder [Esc] zum Schließen...",
            get_color(COLOR_DIM),
        )
        stdscr.refresh()

        key = stdscr.getch()
        if key in (10, 13, 27, ord(" "), ord("q"), ord("Q")):
            break


def prompt_confirm(stdscr: curses.window, title: str, question: str) -> bool:
    """Modal yes/no confirmation dialog."""
    curses.curs_set(0)
    max_y, max_x = stdscr.getmaxyx()

    dlg_w = min(60, max_x - 4)
    dlg_h = 7
    dlg_y = max(1, (max_y - dlg_h) // 2)
    dlg_x = max(1, (max_x - dlg_w) // 2)

    selected = True  # True = Ja, False = Nein

    while True:
        for i in range(dlg_h):
            safe_addstr(stdscr, dlg_y + i, dlg_x, " " * dlg_w, get_color(COLOR_NORMAL))

        draw_box(stdscr, dlg_y, dlg_x, dlg_h, dlg_w, title)
        safe_addstr(stdscr, dlg_y + 2, dlg_x + 2, question[: dlg_w - 4], get_color(COLOR_NORMAL) | curses.A_BOLD)

        # Buttons
        yes_attr = get_color(COLOR_SELECTED) if selected else get_color(COLOR_NORMAL)
        no_attr = get_color(COLOR_SELECTED) if not selected else get_color(COLOR_NORMAL)

        safe_addstr(stdscr, dlg_y + 4, dlg_x + 10, "  [ Ja ]  ", yes_attr)
        safe_addstr(stdscr, dlg_y + 4, dlg_x + 26, "  [ Nein ]  ", no_attr)

        stdscr.refresh()
        key = stdscr.getch()

        if key in (curses.KEY_LEFT, curses.KEY_RIGHT, ord("\t")):
            selected = not selected
        elif key in (ord("j"), ord("J"), ord("y"), ord("Y")):
            return True
        elif key in (ord("n"), ord("N"), 27):
            return False
        elif key in (10, 13, curses.KEY_ENTER, ord(" ")):
            return selected


def display_scrollable_text(stdscr: curses.window, title: str, text: str) -> None:
    """Display long text with scroll support."""
    curses.curs_set(0)
    lines = text.splitlines() or ["(Keine Daten vorhanden)"]
    offset = 0

    while True:
        max_y, max_x = stdscr.getmaxyx()
        stdscr.clear()

        draw_header(stdscr, title, f"Zeilen: {len(lines)}")
        draw_status_bar(stdscr, "[↑/↓/PgUp/PgDn] Scrollen | [Esc/q/Enter] Zurück", f"Zeile {offset + 1}/{len(lines)}")

        view_h = max_y - 3
        draw_box(stdscr, 1, 0, view_h, max_x, title)

        visible_lines = lines[offset : offset + view_h - 2]
        for idx, line in enumerate(visible_lines):
            safe_addstr(stdscr, 2 + idx, 2, line[: max_x - 4], get_color(COLOR_NORMAL))

        stdscr.refresh()

        key = stdscr.getch()
        if key in (27, ord("q"), ord("Q"), 10, 13):
            break
        elif key == curses.KEY_UP:
            if offset > 0:
                offset -= 1
        elif key == curses.KEY_DOWN:
            if offset + view_h - 2 < len(lines):
                offset += 1
        elif key in (curses.KEY_PPAGE, ord("b")):  # Page Up
            offset = max(0, offset - (view_h - 2))
        elif key in (curses.KEY_NPAGE, ord(" ")):  # Page Down
            if offset + view_h - 2 < len(lines):
                offset = min(len(lines) - 1, offset + (view_h - 2))
        elif key == curses.KEY_HOME:
            offset = 0
        elif key == curses.KEY_END:
            offset = max(0, len(lines) - (view_h - 2))
