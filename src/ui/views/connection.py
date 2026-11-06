"""Connection view for selecting USB serial port and configuration."""

import curses
from typing import List

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
    draw_box,
    draw_header,
    draw_status_bar,
    prompt_input,
    safe_addstr,
    show_message,
)

BAUD_RATES = [115200, 9600, 19200, 38400, 57600, 230400, 921600]


def run_connection_view(stdscr: curses.window, backend: MeshCoreBackend, config: Config) -> None:
    """Connection setup view."""
    ports = backend.list_serial_ports()
    selected_index = 0

    while True:
        max_y, max_x = stdscr.getmaxyx()
        stdscr.clear()

        status_text = (
            "Modus: SIMULATION" if config.simulation_mode else f"Port: {config.port} ({config.baudrate} Baud)"
        )
        draw_header(stdscr, "Verbindungseinstellungen", status_text)
        draw_status_bar(
            stdscr,
            "[1] Port wählen [2] Baudrate [3] Manuell eingeben [4] Simulation [5] Testen [R] Scan [Esc] Zurück",
            f"Gefundene Ports: {len(ports)}",
        )

        # Draw main box
        view_h = max_y - 3
        draw_box(stdscr, 1, 0, view_h, max_x, "Serielle USB-Schnittstellen")

        safe_addstr(
            stdscr,
            2,
            2,
            "Aktueller Port:    " + config.port,
            get_color(COLOR_HEADER) | curses.A_BOLD,
        )
        safe_addstr(
            stdscr,
            3,
            2,
            f"Aktuelle Baudrate: {config.baudrate}",
            get_color(COLOR_HEADER),
        )
        sim_color = COLOR_WARNING if config.simulation_mode else COLOR_SUCCESS
        sim_str = "AKTIV (Testen ohne USB-Hardware)" if config.simulation_mode else "INAKTIV (Echter USB-Betrieb)"
        safe_addstr(stdscr, 4, 2, "Simulationsmodus:  " + sim_str, get_color(sim_color) | curses.A_BOLD)

        safe_addstr(
            stdscr,
            6,
            2,
            "Verfügbare Geräte (mit Pfeiltasten navigieren, [Enter] zum Auswählen):",
            get_color(COLOR_DIM),
        )

        # List ports
        list_y = 8
        visible_count = view_h - 10
        if not ports:
            safe_addstr(
                stdscr,
                list_y,
                4,
                "Keine seriellen Schnittstellen gefunden! Bitte USB-Companion anschließen.",
                get_color(COLOR_ERROR),
            )
        else:
            for idx, p in enumerate(ports[:visible_count]):
                cur_y = list_y + idx
                is_selected = idx == selected_index
                is_active = p["device"] == config.port

                prefix = "▶ " if is_active else "  "
                tag = "[USB]" if p["is_usb"] else "[SER]"
                line_text = f"{prefix}{p['device']:<16} {tag} {p['description']}"

                attr = get_color(COLOR_SELECTED) if is_selected else get_color(COLOR_NORMAL)
                if is_active and not is_selected:
                    attr |= curses.A_BOLD

                safe_addstr(stdscr, cur_y, 4, line_text[: max_x - 8], attr)

        stdscr.refresh()
        key = stdscr.getch()

        if key in (27, ord("q"), ord("Q")):
            break
        elif key == curses.KEY_UP:
            if selected_index > 0:
                selected_index -= 1
        elif key == curses.KEY_DOWN:
            if selected_index < len(ports) - 1:
                selected_index += 1
        elif key in (10, 13, curses.KEY_ENTER, ord("1")):
            if ports:
                config.port = ports[selected_index]["device"]
        elif key in (ord("2"), ord("b"), ord("B")):
            # Cycle through baud rates
            try:
                curr_idx = BAUD_RATES.index(config.baudrate)
                config.baudrate = BAUD_RATES[(curr_idx + 1) % len(BAUD_RATES)]
            except ValueError:
                config.baudrate = 115200
        elif key in (ord("3"), ord("m"), ord("M")):
            custom = prompt_input(
                stdscr,
                "Port manuell eingeben",
                "Gerätepfad eingeben (z.B. /dev/ttyUSB0 oder /dev/ttyACM0):",
                default=config.port,
            )
            if custom:
                config.port = custom
        elif key in (ord("4"), ord("s"), ord("S")):
            config.simulation_mode = not config.simulation_mode
        elif key in (ord("5"), ord("t"), ord("T")):
            safe_addstr(stdscr, max_y - 2, 2, "Teste Verbindung... bitte warten...", get_color(COLOR_WARNING))
            stdscr.refresh()
            ok, msg = backend.test_connection()
            show_message(stdscr, "Verbindungstest", msg, is_error=not ok)
        elif key in (ord("r"), ord("R")):
            ports = backend.list_serial_ports()
            selected_index = 0
