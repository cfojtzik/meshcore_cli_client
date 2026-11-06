"""Node Information and Diagnostics View."""

import curses

from ...backend.executor import MeshCoreBackend
from ...config import Config
from ..colors import (
    COLOR_DIM,
    COLOR_ERROR,
    COLOR_HEADER,
    COLOR_NORMAL,
    COLOR_SELECTED,
    COLOR_SUCCESS,
    COLOR_WARNING,
    get_color,
)
from ..widgets import (
    display_scrollable_text,
    draw_box,
    draw_header,
    draw_status_bar,
    prompt_confirm,
    safe_addstr,
    show_message,
)


def run_node_info_view(stdscr: curses.window, backend: MeshCoreBackend, config: Config) -> None:
    """Node info view with actions."""
    cached_info = "Lade Node-Informationen..."
    loading = True

    while True:
        max_y, max_x = stdscr.getmaxyx()
        stdscr.clear()

        draw_header(stdscr, "Node-Informationen & Status", f"Port: {config.port}")
        draw_status_bar(
            stdscr,
            "[1] Refresh [2] Firmware [3] Telemetrie [4] Uhrzeit-Sync [5] Reboot [Esc] Zurück",
            "MeshCore",
        )

        view_h = max_y - 3
        draw_box(stdscr, 1, 0, view_h, max_x, "Geräte-Status & Parameter")

        if loading:
            safe_addstr(stdscr, 3, 4, "Frage Node über USB ab... bitte warten...", get_color(COLOR_WARNING))
            stdscr.refresh()
            ok, res = backend.run_cli(["infos"])
            cached_info = res if ok else f"Fehler beim Abrufen der Node-Infos:\n{res}"
            loading = False

        # Render content lines
        lines = cached_info.splitlines()
        visible_lines = lines[: view_h - 4]
        for idx, line in enumerate(visible_lines):
            color = COLOR_HEADER if any(k in line for k in ("Node Name", "MeshCore", "Hardware")) else COLOR_NORMAL
            safe_addstr(stdscr, 3 + idx, 4, line[: max_x - 8], get_color(color))

        stdscr.refresh()
        key = stdscr.getch()

        if key in (27, ord("q"), ord("Q")):
            break
        elif key in (ord("1"), ord("r"), ord("R")):
            loading = True
        elif key in (ord("2"), ord("v"), ord("V")):
            ok, res = backend.run_cli(["ver"])
            show_message(stdscr, "Firmware-Version", res, is_error=not ok)
        elif key in (ord("3"), ord("t"), ord("T")):
            ok, res = backend.run_cli(["self_telemetry"])
            display_scrollable_text(stdscr, "Eigene Telemetrie", res)
        elif key in (ord("4"), ord("c"), ord("C")):
            ok, res = backend.run_cli(["clock", "sync"])
            show_message(stdscr, "Uhrzeit-Synchronisation", res, is_error=not ok)
        elif key in (ord("5"),):
            if prompt_confirm(stdscr, "Node Reboot", "Soll der MeshCore-Companion wirklich neu gestartet werden?"):
                ok, res = backend.run_cli(["reboot"])
                show_message(stdscr, "Reboot", res, is_error=not ok)
                loading = True
