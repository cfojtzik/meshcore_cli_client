"""Node information and diagnostics with asynchronous backend access."""

import curses
from typing import Any, Callable, Optional

from ...backend.executor import MeshCoreBackend
from ...config import Config
from ..async_task import BackgroundTask, run_with_progress
from ..colors import COLOR_HEADER, COLOR_NORMAL, get_color
from ..widgets import (
    display_scrollable_text,
    draw_box,
    draw_header,
    draw_status_bar,
    prompt_confirm,
    read_key,
    safe_addstr,
    show_message,
    wrap_text_lines,
)


def run_node_info_view(stdscr: curses.window, backend: MeshCoreBackend, config: Config) -> None:
    """Show scrollable node information without blocking curses during I/O."""
    task = BackgroundTask()

    def run_io(title: str, func: Callable[[], Any]) -> Optional[Any]:
        result = run_with_progress(stdscr, task, title, func)
        if not result.success:
            show_message(stdscr, title, str(result.value), is_error=True)
            return None
        return result.value

    result = run_io("Node-Informationen", lambda: backend.run_cli(["infos"]))
    if result is None:
        cached_info = "Node-Informationen konnten nicht geladen werden."
    else:
        ok, res = result
        cached_info = res if ok else f"Fehler beim Abrufen der Node-Infos:\n{res}"
    info_offset = 0

    try:
        while True:
            max_y, max_x = stdscr.getmaxyx()
            stdscr.clear()
            draw_header(stdscr, "Node-Informationen & Status", f"Port: {config.port}")
            draw_status_bar(
                stdscr,
                "[↑/↓/PgUp/PgDn/Home/End] Scrollen [1] Refresh [2] Firmware [3] Telemetrie [4] Uhrzeit [5] Reboot [Esc] Zurück",
                f"Zeile {info_offset + 1}",
            )
            view_h = max(0, max_y - 3)
            draw_box(stdscr, 1, 0, view_h, max_x, "Geräte-Status & Parameter")
            content_h = max(0, view_h - 4)
            lines = wrap_text_lines(cached_info, max(1, max_x - 8))
            max_offset = max(0, len(lines) - content_h)
            info_offset = max(0, min(info_offset, max_offset))
            for idx, line in enumerate(lines[info_offset : info_offset + content_h]):
                color = COLOR_HEADER if any(k in line for k in ("Node Name", "MeshCore", "Hardware")) else COLOR_NORMAL
                safe_addstr(stdscr, 3 + idx, 4, line, get_color(color))

            stdscr.refresh()
            key = read_key(stdscr)
            if key is None or key == curses.KEY_RESIZE:
                continue
            if key in (27, ord("q"), ord("Q")):
                break
            if key == curses.KEY_UP:
                info_offset = max(0, info_offset - 1)
            elif key == curses.KEY_DOWN:
                info_offset = min(max_offset, info_offset + 1)
            elif key == curses.KEY_PPAGE:
                info_offset = max(0, info_offset - max(1, content_h))
            elif key == curses.KEY_NPAGE:
                info_offset = min(max_offset, info_offset + max(1, content_h))
            elif key == curses.KEY_HOME:
                info_offset = 0
            elif key == curses.KEY_END:
                info_offset = max_offset
            elif key in (ord("1"), ord("r"), ord("R")):
                result = run_io("Node-Informationen", lambda: backend.run_cli(["infos"]))
                if result is not None:
                    ok, res = result
                    cached_info = res if ok else f"Fehler beim Abrufen der Node-Infos:\n{res}"
                    info_offset = 0
            elif key in (ord("2"), ord("v"), ord("V")):
                result = run_io("Firmware-Version", lambda: backend.run_cli(["ver"]))
                if result is not None:
                    ok, res = result
                    show_message(stdscr, "Firmware-Version", res, is_error=not ok)
            elif key in (ord("3"), ord("t"), ord("T")):
                result = run_io("Eigene Telemetrie", lambda: backend.run_cli(["self_telemetry"]))
                if result is not None:
                    ok, res = result
                    display_scrollable_text(stdscr, "Eigene Telemetrie" + ("" if ok else " – Fehler"), res)
            elif key in (ord("4"), ord("c"), ord("C")):
                result = run_io("Uhrzeit-Synchronisation", lambda: backend.run_cli(["clock", "sync"]))
                if result is not None:
                    ok, res = result
                    show_message(stdscr, "Uhrzeit-Synchronisation", res, is_error=not ok)
            elif key == ord("5"):
                if prompt_confirm(stdscr, "Node Reboot", "Soll der MeshCore-Companion wirklich neu gestartet werden?"):
                    result = run_io("Reboot", lambda: backend.run_cli(["reboot"]))
                    if result is not None:
                        ok, res = result
                        show_message(stdscr, "Reboot", res, is_error=not ok)
    finally:
        task.close()
