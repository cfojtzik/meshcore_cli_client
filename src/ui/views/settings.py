"""Node Settings, Configuration & Radio Parameters View."""

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
    prompt_input,
    safe_addstr,
    show_message,
)


def run_settings_view(stdscr: curses.window, backend: MeshCoreBackend, config: Config) -> None:
    """Settings view for getting and setting radio and node parameters."""
    while True:
        max_y, max_x = stdscr.getmaxyx()
        stdscr.clear()

        draw_header(stdscr, "Node-Einstellungen & Parameter", f"Port: {config.port}")
        draw_status_bar(
            stdscr,
            "[1] Parameter lesen [2] Parameter setzen [3] Hilfe-Parameter [4] Advert [5] Flood-Advert [6] URI Card [Esc] Zurück",
            "Settings",
        )

        view_h = max_y - 3
        draw_box(stdscr, 1, 0, view_h, max_x, "Konfiguration")

        items = [
            ("1", "Parameter abfragen", "get <parameter>"),
            ("2", "Parameter ändern", "set <parameter> <wert>"),
            ("3", "Parameter-Hilfeliste anzeigen", "get help"),
            ("4", "Advertisement senden (Direkte Umgebung)", "advert"),
            ("5", "Flood-Advertisement senden (Ganzes Mesh)", "floodadv"),
            ("6", "Eigene Node-URI / Card exportieren", "card"),
        ]

        safe_addstr(stdscr, 3, 3, "Wähle eine Aktion aus (Zifferntaste 1-6 drücken):", get_color(COLOR_HEADER) | curses.A_BOLD)

        for idx, (key, title, cmd_hint) in enumerate(items):
            y = 5 + idx * 2
            safe_addstr(stdscr, y, 4, f"[{key}] {title}", get_color(COLOR_NORMAL) | curses.A_BOLD)
            safe_addstr(stdscr, y + 1, 8, f"meshcli: {cmd_hint}", get_color(COLOR_DIM))

        stdscr.refresh()
        key = stdscr.getch()

        if key in (27, ord("q"), ord("Q")):
            break
        elif key in (ord("1"), ord("g"), ord("G")):
            param = prompt_input(stdscr, "Parameter abfragen", "Name des Parameters (oder 'help'):", default="name")
            if param:
                ok, res = backend.run_cli(["get", param])
                show_message(stdscr, f"Parameter: {param}", res, is_error=not ok)
        elif key in (ord("2"), ord("s"), ord("S")):
            param = prompt_input(stdscr, "Parameter ändern", "Name des Parameters:")
            if param:
                val = prompt_input(stdscr, f"Wert für '{param}'", "Neuer Wert:")
                if val is not None:
                    ok, res = backend.run_cli(["set", param, val])
                    show_message(stdscr, f"Parameter {param} setzen", res, is_error=not ok)
        elif key == ord("3"):
            safe_addstr(stdscr, max_y - 2, 2, "Lade Parameterliste...", get_color(COLOR_WARNING))
            stdscr.refresh()
            ok, res = backend.run_cli(["get", "help"])
            display_scrollable_text(stdscr, "Verfügbare Node-Parameter", res)
        elif key in (ord("4"), ord("a"), ord("A")):
            safe_addstr(stdscr, max_y - 2, 2, "Sende Advert...", get_color(COLOR_WARNING))
            stdscr.refresh()
            ok, res = backend.run_cli(["advert"])
            show_message(stdscr, "Advertisement", res, is_error=not ok)
        elif key in (ord("5"), ord("f"), ord("F")):
            safe_addstr(stdscr, max_y - 2, 2, "Sende Flood Advertisement...", get_color(COLOR_WARNING))
            stdscr.refresh()
            ok, res = backend.run_cli(["floodadv"])
            show_message(stdscr, "Flood Advertisement", res, is_error=not ok)
        elif key in (ord("6"), ord("c"), ord("C")):
            ok, res = backend.run_cli(["card"])
            show_message(stdscr, "Node Card / URI", res, is_error=not ok)
