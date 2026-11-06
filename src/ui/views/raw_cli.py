"""Raw CLI & Console View allowing direct execution of any meshcore-cli command."""

import curses
import shlex

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


def run_raw_cli_view(stdscr: curses.window, backend: MeshCoreBackend, config: Config) -> None:
    """Raw CLI view for 100% coverage of any arbitrary command."""
    history = [
        "Willkommen in der direkten MeshCore-Konsole.",
        f"Verbindung über: {config.port} ({config.baudrate} Baud).",
        "Gib einen beliebigen Befehl ein (z.B. 'infos', 'contacts', '?cmd', 'ver').",
    ]

    while True:
        max_y, max_x = stdscr.getmaxyx()
        stdscr.clear()

        draw_header(stdscr, "Direkte MeshCore Konsole (100% CLI Zugriff)", f"Port: {config.port}")
        draw_status_bar(
            stdscr,
            "[Enter] Befehl ausführen [H] Hilfe anzeigen [C] Verlauf leeren [Esc] Zurück",
            "CLI-Modus",
        )

        view_h = max_y - 3
        draw_box(stdscr, 1, 0, view_h, max_x, "Terminal-Ausgabe")

        visible_lines = history[-(view_h - 4) :]
        for idx, line in enumerate(visible_lines):
            safe_addstr(stdscr, 2 + idx, 2, line[: max_x - 4], get_color(COLOR_NORMAL))

        stdscr.refresh()
        key = stdscr.getch()

        if key in (27, ord("q"), ord("Q")):
            break
        elif key in (10, 13, curses.KEY_ENTER, ord(" ")):
            cmd = prompt_input(
                stdscr,
                "MeshCore Befehl ausführen",
                "Befehl eingeben (z.B. 'infos', 'self_telemetry', 'contacts'):",
            )
            if cmd:
                history.append(f"> meshcli {cmd}")
                safe_addstr(stdscr, max_y - 2, 2, f"Führe '{cmd}' aus...", get_color(COLOR_WARNING))
                stdscr.refresh()

                try:
                    args = shlex.split(cmd)
                except Exception:
                    args = cmd.split()

                ok, res = backend.run_cli(args)
                for line in res.splitlines():
                    history.append(line)

                # Keep history reasonable
                if len(history) > 300:
                    history = history[-300:]
        elif key in (ord("h"), ord("H")):
            safe_addstr(stdscr, max_y - 2, 2, "Lade CLI-Hilfe...", get_color(COLOR_WARNING))
            stdscr.refresh()
            ok, res = backend.run_cli(["-h"])
            display_scrollable_text(stdscr, "meshcli Hilfe", res)
        elif key in (ord("c"), ord("C")):
            history = ["(Verlauf geleert)"]
