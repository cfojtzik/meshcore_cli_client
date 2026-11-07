"""Repeater and remote-administration view."""

import curses
from typing import Any, Callable, Optional

from ...backend.executor import MeshCoreBackend
from ...config import Config
from ..async_task import BackgroundTask, run_with_progress
from ..colors import COLOR_DIM, COLOR_HEADER, COLOR_NORMAL, COLOR_SUCCESS, get_color
from ..widgets import display_scrollable_text, draw_box, draw_header, draw_status_bar, prompt_input, read_key, safe_addstr, show_message


def run_repeaters_view(stdscr: curses.window, backend: MeshCoreBackend, config: Config) -> None:
    """Run repeater operations serially in one background worker."""
    active_repeater = ""
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
            sub_info = f"Eingeloggt bei: {active_repeater}" if active_repeater else "Kein Repeater ausgewählt"
            draw_header(stdscr, "Repeater & Fernverwaltung", sub_info)
            draw_status_bar(
                stdscr,
                "[1] Login [2] Logout [3] Remote [4] Status [5] Nachbarn [6] Traceroute [Esc] Zurück",
                "Repeater Admin",
            )
            view_h = max(0, max_y - 3)
            draw_box(stdscr, 1, 0, view_h, max_x, "Infrastruktur-Knoten & Repeater")
            items = [
                ("1", "Am Repeater einloggen", "login <name> <passwort>"),
                ("2", "Vom Repeater abmelden", "logout <name>"),
                ("3", "Remote-Befehl an Repeater senden", "cmd <name> <befehl>"),
                ("4", "Repeater-Status abfragen (Batterie/Solar/Uptime)", "req_status <name>"),
                ("5", "Nachbarschaftsliste anfordern (Neighbours)", "req_neighbours <name>"),
                ("6", "Traceroute durchführen", "trace <pfad>"),
            ]
            safe_addstr(stdscr, 3, 3, "Wähle eine Aktion aus:", get_color(COLOR_HEADER) | curses.A_BOLD)
            for idx, (number, title, cmd_hint) in enumerate(items):
                y = 5 + idx * 2
                safe_addstr(stdscr, y, 4, f"[{number}] {title}", get_color(COLOR_NORMAL) | curses.A_BOLD)
                safe_addstr(stdscr, y + 1, 8, f"meshcli: {cmd_hint}", get_color(COLOR_DIM))
            if active_repeater:
                safe_addstr(stdscr, max(1, view_h - 3), 3, f"Aktiver Repeater: [{active_repeater}]", get_color(COLOR_SUCCESS) | curses.A_BOLD)

            stdscr.refresh()
            key = read_key(stdscr)
            if key is None or key == curses.KEY_RESIZE:
                continue
            if key in (27, ord("q"), ord("Q")):
                break
            if key in (ord("1"), ord("l"), ord("L")):
                rep = prompt_input(stdscr, "Repeater Login", "Name des Repeaters:", default=active_repeater)
                if rep:
                    pwd = prompt_input(stdscr, f"Passwort für '{rep}'", "Passwort:")
                    if pwd is not None:
                        result = run_io("Repeater Login", lambda rep=rep, pwd=pwd: backend.run_cli(["login", rep, pwd], timeout=15))
                        if result is not None:
                            ok, res = result
                            if ok:
                                active_repeater = rep
                            show_message(stdscr, "Repeater Login", res, is_error=not ok)
            elif key == ord("2"):
                rep = active_repeater or prompt_input(stdscr, "Repeater Logout", "Name des Repeaters:")
                if rep:
                    result = run_io("Repeater Logout", lambda rep=rep: backend.run_cli(["logout", rep]))
                    if result is not None:
                        ok, res = result
                        if ok and active_repeater == rep:
                            active_repeater = ""
                        show_message(stdscr, "Repeater Logout", res, is_error=not ok)
            elif key in (ord("3"), ord("c"), ord("C")):
                rep = active_repeater or prompt_input(stdscr, "Remote-Befehl", "Name des Ziel-Repeaters:")
                if rep:
                    cmd_str = prompt_input(stdscr, f"Befehl an '{rep}'", "Befehl (z.B. ver, status, reboot):")
                    if cmd_str:
                        result = run_io("Remote-Befehl", lambda rep=rep, cmd_str=cmd_str: backend.run_cli(["cmd", rep, cmd_str], timeout=15))
                        if result is not None:
                            ok, res = result
                            display_scrollable_text(stdscr, f"Antwort von {rep}" + ("" if ok else " – Fehler"), res)
            elif key in (ord("4"), ord("s"), ord("S")):
                rep = active_repeater or prompt_input(stdscr, "Repeater Status", "Name des Repeaters:")
                if rep:
                    result = run_io("Repeater Status", lambda rep=rep: backend.run_cli(["req_status", rep], timeout=15))
                    if result is not None:
                        ok, res = result
                        show_message(stdscr, f"Status: {rep}", res, is_error=not ok)
            elif key in (ord("5"), ord("n"), ord("N")):
                rep = active_repeater or prompt_input(stdscr, "Repeater Nachbarn", "Name des Repeaters:")
                if rep:
                    result = run_io("Repeater Nachbarn", lambda rep=rep: backend.run_cli(["req_neighbours", rep], timeout=15))
                    if result is not None:
                        ok, res = result
                        display_scrollable_text(stdscr, f"Nachbarn von {rep}" + ("" if ok else " – Fehler"), res)
            elif key in (ord("6"), ord("t"), ord("T")):
                path = prompt_input(stdscr, "Traceroute", "Pfad kommagetrennt (z.B. Rep1,Rep2):")
                if path:
                    result = run_io("Traceroute", lambda path=path: backend.run_cli(["trace", path], timeout=20))
                    if result is not None:
                        ok, res = result
                        display_scrollable_text(stdscr, f"Traceroute: {path}" + ("" if ok else " – Fehler"), res)
    finally:
        task.close()
