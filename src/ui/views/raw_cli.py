"""Raw CLI console with asynchronous execution and scrollable history."""

import curses
import shlex
from typing import Any, Callable, Optional

from ...backend.executor import MeshCoreBackend
from ...config import Config
from ..async_task import BackgroundTask, run_with_progress
from ..colors import COLOR_DIM, COLOR_HEADER, COLOR_NORMAL, get_color
from ..widgets import (
    display_scrollable_text,
    draw_box,
    draw_header,
    draw_status_bar,
    prompt_input,
    read_key,
    safe_addstr,
    show_message,
    wrap_text_lines,
)


def run_raw_cli_view(stdscr: curses.window, backend: MeshCoreBackend, config: Config) -> None:
    """Raw CLI view for arbitrary commands with persistent in-view scroll state."""
    history = [
        "Willkommen in der direkten MeshCore-Konsole.",
        f"Verbindung über: {config.port} ({config.baudrate} Baud).",
        "Gib einen beliebigen Befehl ein (z.B. 'infos', 'contacts', '?cmd', 'ver').",
    ]
    scroll_offset = 0  # Lines upwards from the newest output.
    task = BackgroundTask()

    def run_io(title: str, func: Callable[[], Any]) -> Optional[Any]:
        result = run_with_progress(stdscr, task, title, func)
        if not result.success:
            show_message(stdscr, title, str(result.value), is_error=True)
            return None
        return result.value

    try:
        while True:
            max_y, max_x = stdscr.getmaxyx()
            stdscr.clear()
            draw_header(stdscr, "Direkte MeshCore Konsole (100% CLI Zugriff)", f"Port: {config.port}")
            draw_status_bar(
                stdscr,
                "[Enter] Ausführen [↑/↓/PgUp/PgDn/Home/End] Verlauf [H] Hilfe [C] Leeren [Esc] Zurück",
                f"Scroll: {scroll_offset}",
            )
            view_h = max(0, max_y - 3)
            draw_box(stdscr, 1, 0, view_h, max_x, "Terminal-Ausgabe")
            content_h = max(0, view_h - 2)
            lines = wrap_text_lines("\n".join(history), max(1, max_x - 4))
            max_scroll = max(0, len(lines) - content_h)
            scroll_offset = max(0, min(scroll_offset, max_scroll))
            start = max(0, len(lines) - content_h - scroll_offset)
            for idx, line in enumerate(lines[start : start + content_h]):
                safe_addstr(stdscr, 2 + idx, 2, line, get_color(COLOR_NORMAL))
            if scroll_offset:
                safe_addstr(stdscr, 1, max(2, max_x - 18), f" ↑ {scroll_offset} ältere ", get_color(COLOR_HEADER))

            stdscr.refresh()
            key = read_key(stdscr)
            if key is None or key == curses.KEY_RESIZE:
                continue
            if key in (27, ord("q"), ord("Q")):
                break
            if key == curses.KEY_UP:
                scroll_offset = min(max_scroll, scroll_offset + 1)
            elif key == curses.KEY_DOWN:
                scroll_offset = max(0, scroll_offset - 1)
            elif key == curses.KEY_PPAGE:
                scroll_offset = min(max_scroll, scroll_offset + max(1, content_h))
            elif key == curses.KEY_NPAGE:
                scroll_offset = max(0, scroll_offset - max(1, content_h))
            elif key == curses.KEY_HOME:
                scroll_offset = max_scroll
            elif key == curses.KEY_END:
                scroll_offset = 0
            elif key in (10, 13, curses.KEY_ENTER, ord(" ")):
                cmd = prompt_input(
                    stdscr,
                    "MeshCore Befehl ausführen",
                    "Befehl eingeben (z.B. 'infos', 'self_telemetry', 'contacts'):",
                )
                if cmd:
                    history.append(f"> meshcli {cmd}")
                    try:
                        args = shlex.split(cmd)
                    except ValueError:
                        args = cmd.split()
                    result = run_io("MeshCore Befehl", lambda args=args: backend.run_cli(args))
                    if result is not None:
                        ok, res = result
                        if not ok:
                            history.append("[Fehler beim Befehl]")
                        history.extend(res.splitlines() or [str(res)])
                        if len(history) > 300:
                            history = history[-300:]
                        scroll_offset = 0
            elif key in (ord("h"), ord("H")):
                result = run_io("meshcli Hilfe", lambda: backend.run_cli(["-h"]))
                if result is not None:
                    ok, res = result
                    display_scrollable_text(stdscr, "meshcli Hilfe" + ("" if ok else " – Fehler"), res)
            elif key in (ord("c"), ord("C")):
                history = ["(Verlauf geleert)"]
                scroll_offset = 0
    finally:
        task.close()
