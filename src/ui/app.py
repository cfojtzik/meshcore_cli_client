"""Main Curses Application Controller and Menu."""

import curses
from pathlib import Path

from ..backend.executor import MeshCoreBackend
from ..config import Config, DEFAULT_CONFIG
from .colors import COLOR_HEADER, COLOR_NORMAL, COLOR_SELECTED, get_color, init_colors
from .views import (
    run_chat_view,
    run_connection_view,
    run_contacts_view,
    run_messaging_view,
    run_node_info_view,
    run_raw_cli_view,
    run_repeaters_view,
    run_settings_view,
)
from .widgets import draw_box, draw_header, draw_status_bar, ensure_visible, prompt_confirm, read_key, safe_addstr, safe_curs_set

MENU_ITEMS = [
    ("1", "🔌 Verbindung & USB-Ports", "Port auswählen, Baudrate, Simulation und Verbindungstest"),
    ("2", "ℹ️  Node-Status & Telemetrie", "Firmware-Version, Batterie, Hardware und Uhrzeit-Sync"),
    ("3", "💬 Chatfenster & Verlauf", "Interaktives Chatfenster für Kanäle und Direktnachrichten"),
    ("4", "👥 Gehörte Nodes & Kontakte", "Gehörte Nodes interaktiv anzeigen und in Kontakte speichern"),
    ("5", "📡 Repeater & Admin", "Repeater-Login, Remote-Befehle, Status und Traceroute"),
    ("6", "📻 Kanal- & Scope-Verwaltung", "Kanäle 0-7 einrichten, Verschlüsselung, Flood-Scope"),
    ("7", "⚙️  Node-Einstellungen", "Radio-Parameter lesen/setzen, Advertisements senden"),
    ("8", "💻 Direkte MeshCore Konsole", "Unbegrenzter CLI-Zugriff auf alle meshcli Befehle"),
    ("9", "❌ Beenden", "Programm sicher beenden"),
]


class MeshCoreTUIApp:
    def __init__(self, auto_select_port: bool = True) -> None:
        self.config = Config()
        self.backend = MeshCoreBackend(self.config)
        self.auto_select_port = auto_select_port
        self.selected_index = 0
        self.menu_offset = 0

    def run(self) -> None:
        try:
            curses.wrapper(self._main_loop)
        finally:
            self.backend.close()

    def _main_loop(self, stdscr: curses.window) -> None:
        safe_curs_set(0)
        init_colors()
        stdscr.timeout(-1)

        # Only replace an unavailable factory default. Explicit -s arguments and
        # custom paths saved through the connection view must always be preserved.
        if self.auto_select_port and self.config.port == DEFAULT_CONFIG["port"]:
            if not Path(self.config.port).exists():
                available_ports = self.backend.list_serial_ports()
                usb_ports = [p["device"] for p in available_ports if p["is_usb"]]
                if usb_ports:
                    self.config.port = usb_ports[0]

        while True:
            max_y, max_x = stdscr.getmaxyx()
            stdscr.clear()
            mode_tag = "SIMULATION" if self.config.simulation_mode else self.config.port
            draw_header(stdscr, "Hauptmenü", f"Status: {mode_tag}")
            draw_status_bar(
                stdscr,
                "[↑/↓] Navigieren | [Enter / 1-8] Auswählen | [q] Beenden",
                "x86 32/64-Bit Ready",
            )

            box_h = min(len(MENU_ITEMS) * 2 + 5, max(0, max_y - 4))
            box_w = min(74, max(0, max_x - 2))
            box_y = max(0, (max_y - box_h) // 2)
            box_x = max(0, (max_x - box_w) // 2)
            draw_box(stdscr, box_y, box_x, box_h, box_w, "MeshCore Navigation")

            visible_items = max(0, (box_h - 3) // 2)
            self.menu_offset = ensure_visible(
                self.selected_index, self.menu_offset, visible_items, len(MENU_ITEMS)
            )
            visible = MENU_ITEMS[self.menu_offset : self.menu_offset + visible_items]
            for row, (num, title, desc) in enumerate(visible):
                idx = self.menu_offset + row
                item_y = box_y + 2 + row * 2
                is_selected = idx == self.selected_index
                line_text = f" [{num}] {title}"
                if is_selected:
                    safe_addstr(
                        stdscr,
                        item_y,
                        box_x + 2,
                        line_text.ljust(max(0, box_w - 4)),
                        get_color(COLOR_SELECTED) | curses.A_BOLD | curses.A_REVERSE,
                    )
                else:
                    safe_addstr(stdscr, item_y, box_x + 2, line_text, get_color(COLOR_NORMAL) | curses.A_BOLD)
                if is_selected and item_y + 1 < box_y + box_h - 1:
                    safe_addstr(
                        stdscr,
                        item_y + 1,
                        box_x + 2,
                        f"     ↳ {desc}",
                        get_color(COLOR_HEADER),
                    )

            stdscr.refresh()
            key = read_key(stdscr)
            if key is None or key == curses.KEY_RESIZE:
                continue
            if key in (curses.KEY_UP, ord("k"), ord("K")):
                self.selected_index = (self.selected_index - 1) % len(MENU_ITEMS)
            elif key in (curses.KEY_DOWN, ord("j"), ord("J")):
                self.selected_index = (self.selected_index + 1) % len(MENU_ITEMS)
            elif key in (10, 13, curses.KEY_ENTER, ord(" ")):
                if not self._dispatch_action(stdscr, self.selected_index):
                    break
            elif isinstance(key, int) and ord("1") <= key <= ord("9"):
                idx = key - ord("1")
                self.selected_index = idx
                if not self._dispatch_action(stdscr, idx):
                    break
            elif key in (ord("q"), ord("Q"), 27):
                if prompt_confirm(stdscr, "Programm beenden", "Möchtest du den MeshCore Client wirklich beenden?"):
                    break

    def _dispatch_action(self, stdscr: curses.window, index: int) -> bool:
        """Dispatch to chosen view. Returns False if user chooses to exit."""
        if index == 0:
            run_connection_view(stdscr, self.backend, self.config)
        elif index == 1:
            run_node_info_view(stdscr, self.backend, self.config)
        elif index == 2:
            run_chat_view(stdscr, self.backend, self.config)
        elif index == 3:
            run_contacts_view(stdscr, self.backend, self.config)
        elif index == 4:
            run_repeaters_view(stdscr, self.backend, self.config)
        elif index == 5:
            run_messaging_view(stdscr, self.backend, self.config)
        elif index == 6:
            run_settings_view(stdscr, self.backend, self.config)
        elif index == 7:
            run_raw_cli_view(stdscr, self.backend, self.config)
        elif index == 8:
            return not prompt_confirm(stdscr, "Programm beenden", "Möchtest du den MeshCore Client wirklich beenden?")
        return True
