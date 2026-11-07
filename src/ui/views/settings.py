"""Node settings and radio-parameter view."""

import curses
from typing import Any, Callable, Optional

from ...backend.executor import MeshCoreBackend
from ...config import Config
from ..async_task import BackgroundTask, run_with_progress
from ..colors import COLOR_DIM, COLOR_HEADER, COLOR_NORMAL, get_color
from ..widgets import display_scrollable_text, draw_box, draw_header, draw_status_bar, prompt_input, read_key, safe_addstr, show_message


def run_settings_view(stdscr: curses.window, backend: MeshCoreBackend, config: Config) -> None:
    """Get and set node parameters without blocking resize during backend I/O."""
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
            draw_header(stdscr, "Node-Einstellungen & Parameter", f"Port: {config.port}")
            draw_status_bar(
                stdscr,
                "[1] Get [2] Set [3] Hilfe [4] Advert [5] Flood [6] URI Card [Esc] Zurück",
                "Settings",
            )
            view_h = max(0, max_y - 3)
            draw_box(stdscr, 1, 0, view_h, max_x, "Konfiguration")
            items = [
                ("1", "Parameter abfragen", "get <parameter>"),
                ("2", "Parameter ändern", "set <parameter> <wert>"),
                ("3", "Parameter-Hilfeliste anzeigen", "get help"),
                ("4", "Advertisement senden (Direkte Umgebung)", "advert"),
                ("5", "Flood-Advertisement senden (Ganzes Mesh)", "floodadv"),
                ("6", "Eigene Node-URI / Card exportieren", "card"),
            ]
            safe_addstr(stdscr, 3, 3, "Wähle eine Aktion aus:", get_color(COLOR_HEADER) | curses.A_BOLD)
            for idx, (number, title, cmd_hint) in enumerate(items):
                y = 5 + idx * 2
                safe_addstr(stdscr, y, 4, f"[{number}] {title}", get_color(COLOR_NORMAL) | curses.A_BOLD)
                safe_addstr(stdscr, y + 1, 8, f"meshcli: {cmd_hint}", get_color(COLOR_DIM))

            stdscr.refresh()
            key = read_key(stdscr)
            if key is None or key == curses.KEY_RESIZE:
                continue
            if key in (27, ord("q"), ord("Q")):
                break
            if key in (ord("1"), ord("g"), ord("G")):
                param = prompt_input(stdscr, "Parameter abfragen", "Name des Parameters (oder 'help'):", default="name")
                if param:
                    result = run_io("Parameter abfragen", lambda param=param: backend.run_cli(["get", param]))
                    if result is not None:
                        ok, res = result
                        show_message(stdscr, f"Parameter: {param}", res, is_error=not ok)
            elif key in (ord("2"), ord("s"), ord("S")):
                param = prompt_input(stdscr, "Parameter ändern", "Name des Parameters:")
                if param:
                    val = prompt_input(stdscr, f"Wert für '{param}'", "Neuer Wert:")
                    if val is not None:
                        result = run_io("Parameter setzen", lambda param=param, val=val: backend.run_cli(["set", param, val]))
                        if result is not None:
                            ok, res = result
                            show_message(stdscr, f"Parameter {param} setzen", res, is_error=not ok)
            elif key == ord("3"):
                result = run_io("Parameterliste", lambda: backend.run_cli(["get", "help"]))
                if result is not None:
                    ok, res = result
                    display_scrollable_text(stdscr, "Verfügbare Node-Parameter" + ("" if ok else " – Fehler"), res)
            elif key in (ord("4"), ord("a"), ord("A")):
                result = run_io("Advertisement", lambda: backend.run_cli(["advert"]))
                if result is not None:
                    ok, res = result
                    show_message(stdscr, "Advertisement", res, is_error=not ok)
            elif key in (ord("5"), ord("f"), ord("F")):
                result = run_io("Flood Advertisement", lambda: backend.run_cli(["floodadv"]))
                if result is not None:
                    ok, res = result
                    show_message(stdscr, "Flood Advertisement", res, is_error=not ok)
            elif key in (ord("6"), ord("c"), ord("C")):
                result = run_io("Node Card", lambda: backend.run_cli(["card"]))
                if result is not None:
                    ok, res = result
                    show_message(stdscr, "Node Card / URI", res, is_error=not ok)
    finally:
        task.close()
