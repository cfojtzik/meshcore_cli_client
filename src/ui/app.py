"""Main Curses Application Controller and Menu."""

import curses
import sys

from ..backend.executor import MeshCoreBackend
from ..config import Config
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
    init_colors,
)
from .views import (
    run_connection_view,
    run_contacts_view,
    run_messaging_view,
    run_node_info_view,
    run_raw_cli_view,
    run_repeaters_view,
    run_settings_view,
)
from .widgets import draw_box, draw_header, draw_status_bar, prompt_confirm, safe_addstr

MENU_ITEMS = [
    ("1", "🔌 Verbindung & USB-Ports", "Port auswählen, Baudrate, Simulation und Verbindungstest"),
    ("2", "ℹ️  Node-Status & Telemetrie", "Firmware-Version, Batterie, Hardware und Uhrzeit-Sync"),
    ("3", "💬 Nachrichten & Kanäle", "Broadcast, Direktnachrichten, Kanäle 0-7, Scope"),
    ("4", "👥 Kontakte & Pfade", "Kontaktliste, Signalstärke, Pfadsuche und Export/Import"),
    ("5", "📡 Repeater & Admin", "Repeater-Login, Remote-Befehle, Status und Traceroute"),
    ("6", "⚙️  Node-Einstellungen", "Radio-Parameter lesen/setzen, Advertisements senden"),
    ("7", "💻 Direkte MeshCore Konsole", "Unbegrenzter CLI-Zugriff auf alle meshcli Befehle"),
    ("8", "❌ Beenden", "Programm sicher beenden"),
]


class MeshCoreTUIApp:
    def __init__(self) -> None:
        self.config = Config()
        self.backend = MeshCoreBackend(self.config)
        self.selected_index = 0

    def run(self) -> None:
        curses.wrapper(self._main_loop)

    def _main_loop(self, stdscr: curses.window) -> None:
        curses.curs_set(0)
        init_colors()
        stdscr.timeout(-1)  # Blocking input

        # If default port does not exist and no simulation mode is explicitly configured,
        # try to auto-select an available USB port or offer simulation mode
        available_ports = self.backend.list_serial_ports()
        usb_ports = [p["device"] for p in available_ports if p["is_usb"]]
        if usb_ports and self.config.port not in usb_ports:
            self.config.port = usb_ports[0]

        while True:
            max_y, max_x = stdscr.getmaxyx()
            stdscr.clear()

            # Header info
            mode_tag = "SIMULATION" if self.config.simulation_mode else self.config.port
            draw_header(stdscr, "Hauptmenü", f"Status: {mode_tag}")
            draw_status_bar(
                stdscr,
                "[↑/↓] Navigieren | [Enter / 1-8] Auswählen | [q] Beenden",
                "x86 32/64-Bit Ready",
            )

            # Draw Menu Box
            box_h = min(len(MENU_ITEMS) * 2 + 5, max_y - 4)
            box_w = min(74, max_x - 2)
            box_y = max(1, (max_y - box_h) // 2)
            box_x = max(1, (max_x - box_w) // 2)

            draw_box(stdscr, box_y, box_x, box_h, box_w, "MeshCore Navigation")

            # Render Menu Items
            for idx, (num, title, desc) in enumerate(MENU_ITEMS):
                item_y = box_y + 2 + idx * 2
                if item_y >= box_y + box_h - 1:
                    break

                is_selected = idx == self.selected_index
                line_text = f" [{num}] {title}"

                if is_selected:
                    safe_addstr(stdscr, item_y, box_x + 2, line_text.ljust(box_w - 4), get_color(COLOR_SELECTED) | curses.A_BOLD)
                else:
                    safe_addstr(stdscr, item_y, box_x + 2, line_text, get_color(COLOR_NORMAL) | curses.A_BOLD)

                # Show description underneath if space permits
                if is_selected and item_y + 1 < box_y + box_h - 1:
                    desc_text = f"     ↳ {desc}"
                    safe_addstr(stdscr, item_y + 1, box_x + 2, desc_text[: box_w - 6], get_color(COLOR_HEADER))

            stdscr.refresh()
            key = stdscr.getch()

            if key in (curses.KEY_UP, ord("k"), ord("K")):
                self.selected_index = (self.selected_index - 1) % len(MENU_ITEMS)
            elif key in (curses.KEY_DOWN, ord("j"), ord("J")):
                self.selected_index = (self.selected_index + 1) % len(MENU_ITEMS)
            elif key in (10, 13, curses.KEY_ENTER, ord(" ")):
                if not self._dispatch_action(stdscr, self.selected_index):
                    break
            elif ord("1") <= key <= ord("8"):
                idx = key - ord("1")
                self.selected_index = idx
                if not self._dispatch_action(stdscr, idx):
                    break
            elif key in (ord("q"), ord("Q"), 27):
                if prompt_confirm(stdscr, "Programm beenden", "Möchtest du den MeshCore Client wirklich beenden?"):
                    break
            elif key == curses.KEY_RESIZE:
                # Handled on next iteration
                pass

    def _dispatch_action(self, stdscr: curses.window, index: int) -> bool:
        """Dispatch to chosen view. Returns False if user chooses to exit."""
        if index == 0:
            run_connection_view(stdscr, self.backend, self.config)
        elif index == 1:
            run_node_info_view(stdscr, self.backend, self.config)
        elif index == 2:
            run_messaging_view(stdscr, self.backend, self.config)
        elif index == 3:
            run_contacts_view(stdscr, self.backend, self.config)
        elif index == 4:
            run_repeaters_view(stdscr, self.backend, self.config)
        elif index == 5:
            run_settings_view(stdscr, self.backend, self.config)
        elif index == 6:
            run_raw_cli_view(stdscr, self.backend, self.config)
        elif index == 7:
            return not prompt_confirm(stdscr, "Programm beenden", "Möchtest du den MeshCore Client wirklich beenden?")
        return True
