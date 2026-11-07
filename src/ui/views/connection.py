"""Connection view for selecting USB serial port and configuration."""

import curses
from typing import Any, Callable, Optional

from ...backend.executor import MeshCoreBackend
from ...config import Config
from ..async_task import BackgroundTask, run_with_progress
from ..colors import COLOR_DIM, COLOR_ERROR, COLOR_HEADER, COLOR_NORMAL, COLOR_SELECTED, COLOR_SUCCESS, COLOR_WARNING, get_color
from ..widgets import draw_box, draw_header, draw_status_bar, ensure_visible, prompt_input, read_key, safe_addstr, show_message

BAUD_RATES = [115200, 9600, 19200, 38400, 57600, 230400, 921600]
REFRESH_INTERVALS = [2, 5, 10, 30, 60]


def run_connection_view(stdscr: curses.window, backend: MeshCoreBackend, config: Config) -> None:
    """Connection setup view with a bounded, scrolling port list."""
    task = BackgroundTask()

    def run_io(title: str, func: Callable[[], Any]) -> Optional[Any]:
        result = run_with_progress(stdscr, task, title, func)
        if not result.success:
            show_message(stdscr, title, str(result.value), is_error=True)
            return None
        return result.value

    ports = run_io("Serielle Ports suchen", backend.list_serial_ports) or []
    selected_index = 0
    list_offset = 0

    try:
        while True:
            max_y, max_x = stdscr.getmaxyx()
            stdscr.clear()
            selected_index = min(selected_index, max(0, len(ports) - 1))
            status_text = "Modus: SIMULATION" if config.simulation_mode else f"Port: {config.port} ({config.baudrate} Baud)"
            refresh_interval = getattr(config, "refresh_interval", 5)
            draw_header(stdscr, "Verbindungseinstellungen", status_text)
            draw_status_bar(
                stdscr,
                "[1] Port [2] Baudrate [3] Manuell [4] Simulation [5] Testen [6] Auto-Refresh [R] Scan [Esc] Zurück",
                f"Auto: {refresh_interval}s | Gefundene Ports: {len(ports)}",
            )
            view_h = max(0, max_y - 3)
            draw_box(stdscr, 1, 0, view_h, max_x, "Serielle USB-Schnittstellen")
            safe_addstr(stdscr, 2, 2, "Aktueller Port:    " + config.port, get_color(COLOR_HEADER) | curses.A_BOLD)
            safe_addstr(stdscr, 3, 2, f"Aktuelle Baudrate: {config.baudrate}", get_color(COLOR_HEADER))
            sim_color = COLOR_WARNING if config.simulation_mode else COLOR_SUCCESS
            sim_str = "AKTIV (Testen ohne USB-Hardware)" if config.simulation_mode else "INAKTIV (Echter USB-Betrieb)"
            safe_addstr(stdscr, 4, 2, "Simulationsmodus:  " + sim_str, get_color(sim_color) | curses.A_BOLD)
            safe_addstr(
                stdscr,
                5,
                2,
                f"Auto-Refresh:     {refresh_interval} Sekunden ([6] wechseln)",
                get_color(COLOR_HEADER),
            )
            safe_addstr(stdscr, 6, 2, "Verfügbare Geräte ([Enter] wählen):", get_color(COLOR_DIM))

            list_y = 8
            visible_count = max(0, view_h - 10)
            if not ports:
                safe_addstr(stdscr, list_y, 4, "Keine seriellen Schnittstellen gefunden!", get_color(COLOR_ERROR))
            else:
                list_offset = ensure_visible(selected_index, list_offset, visible_count, len(ports))
                for row, port in enumerate(ports[list_offset : list_offset + visible_count]):
                    idx = list_offset + row
                    is_selected = idx == selected_index
                    is_active = port["device"] == config.port
                    prefix = "▶ " if is_active else "  "
                    tag = "[USB]" if port["is_usb"] else "[SER]"
                    line_text = f"{prefix}{port['device']:<16} {tag} {port['description']}"
                    attr = get_color(COLOR_SELECTED) | curses.A_REVERSE if is_selected else get_color(COLOR_NORMAL)
                    if is_active and not is_selected:
                        attr |= curses.A_BOLD
                    safe_addstr(stdscr, list_y + row, 4, line_text, attr)

            stdscr.refresh()
            key = read_key(stdscr)
            if key is None or key == curses.KEY_RESIZE:
                continue
            if key in (27, ord("q"), ord("Q")):
                break
            if key == curses.KEY_UP:
                selected_index = max(0, selected_index - 1)
            elif key == curses.KEY_DOWN:
                selected_index = min(max(0, len(ports) - 1), selected_index + 1)
            elif key in (10, 13, curses.KEY_ENTER, ord("1")):
                if ports:
                    config.port = ports[selected_index]["device"]
            elif key in (ord("2"), ord("b"), ord("B")):
                try:
                    curr_idx = BAUD_RATES.index(config.baudrate)
                    config.baudrate = BAUD_RATES[(curr_idx + 1) % len(BAUD_RATES)]
                except ValueError:
                    config.baudrate = 115200
            elif key in (ord("3"), ord("m"), ord("M")):
                custom = prompt_input(stdscr, "Port manuell eingeben", "Gerätepfad (z.B. /dev/ttyUSB0):", default=config.port)
                if custom:
                    config.port = custom
            elif key in (ord("4"), ord("s"), ord("S")):
                config.simulation_mode = not config.simulation_mode
            elif key in (ord("5"), ord("t"), ord("T")):
                result = run_io("Verbindungstest", backend.test_connection)
                if result is not None:
                    ok, msg = result
                    show_message(stdscr, "Verbindungstest", msg, is_error=not ok)
            elif key == ord("6"):
                try:
                    current = REFRESH_INTERVALS.index(refresh_interval)
                except ValueError:
                    current = -1
                # The Config property persists each newly selected interval.
                config.refresh_interval = REFRESH_INTERVALS[(current + 1) % len(REFRESH_INTERVALS)]
            elif key in (ord("r"), ord("R")):
                result = run_io("Serielle Ports suchen", backend.list_serial_ports)
                if result is not None:
                    ports = result
                    selected_index = 0
                    list_offset = 0
    finally:
        task.close()
