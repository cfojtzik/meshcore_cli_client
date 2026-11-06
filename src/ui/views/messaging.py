"""Messaging and Channels View."""

import curses

from ...backend.executor import MeshCoreBackend
from ...config import Config
from .chat_view import run_chat_view
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


def run_messaging_view(stdscr: curses.window, backend: MeshCoreBackend, config: Config) -> None:
    """Messaging and channels management menu."""
    message_log: list = []

    while True:
        max_y, max_x = stdscr.getmaxyx()
        stdscr.clear()

        draw_header(stdscr, "Kanal- & Scope-Verwaltung", f"Port: {config.port}")
        draw_status_bar(
            stdscr,
            "[0] Chatfenster [1] Broadcast [2] Direkt [3] Kanal-Msg [4] Sync [5] Kanäle [6] Setup [7] Scope [Esc] Zurück",
            "Kanäle",
        )

        view_h = max_y - 3
        draw_box(stdscr, 1, 0, view_h, max_x, "Kanal- und Scope-Zentrum")

        # Menu options
        options = [
            ("0", "💬 Interaktives Chatfenster öffnen (Live-Chat & Verlauf)", "Volles Chatfenster für Kanäle und DMs"),
            ("1", "Öffentliche Nachricht senden (Kanal 0 Broadcast)", "public <text>"),
            ("2", "Direktnachricht an Kontakt senden", "msg <kontakt> <text> [wait_ack]"),
            ("3", "Nachricht an bestimmten Kanal senden (1-7)", "chan <nummer> <text>"),
            ("4", "Neue Nachrichten vom Node synchronisieren", "sync_msgs"),
            ("5", "Konfigurierte Kanäle anzeigen", "get_channels"),
            ("6", "Kanal konfigurieren (Nummer, Name, Schlüssel)", "set_channel <nr> <name> [key]"),
            ("7", "Flood-Scope konfigurieren", "scope <region>"),
        ]

        safe_addstr(stdscr, 3, 3, "Wähle eine Aktion aus (Zifferntaste 1-7 drücken):", get_color(COLOR_HEADER) | curses.A_BOLD)

        for idx, (key, title, cmd_hint) in enumerate(options):
            y = 5 + idx * 2
            safe_addstr(stdscr, y, 4, f"[{key}] {title}", get_color(COLOR_NORMAL) | curses.A_BOLD)
            safe_addstr(stdscr, y + 1, 8, f"meshcli: {cmd_hint}", get_color(COLOR_DIM))

        # Recent messages preview if any
        if message_log:
            safe_addstr(stdscr, view_h - 4, 3, "Letzte Aktivität:", get_color(COLOR_HEADER))
            safe_addstr(stdscr, view_h - 3, 5, message_log[-1][: max_x - 10], get_color(COLOR_SUCCESS))

        stdscr.refresh()
        ch = stdscr.getch()

        if ch in (27, ord("q"), ord("Q")):
            break
        elif ch in (ord("0"), ord("c"), ord("C")):
            run_chat_view(stdscr, backend, config)
        elif ch in (ord("1"), ord("p"), ord("P")):
            text = prompt_input(stdscr, "Öffentliche Nachricht (Broadcast)", "Nachricht eingeben:")
            if text:
                safe_addstr(stdscr, max_y - 2, 2, "Sende Broadcast...", get_color(COLOR_WARNING))
                stdscr.refresh()
                ok, res = backend.run_cli(["public", text])
                message_log.append(f"Public: {text}")
                show_message(stdscr, "Öffentliche Nachricht", res, is_error=not ok)
        elif ch in (ord("2"), ord("d"), ord("D")):
            target = prompt_input(stdscr, "Direktnachricht", "Name oder ID des Kontakts:")
            if target:
                text = prompt_input(stdscr, f"Nachricht an '{target}'", "Nachrichtentext:")
                if text:
                    safe_addstr(stdscr, max_y - 2, 2, f"Sende an {target}...", get_color(COLOR_WARNING))
                    stdscr.refresh()
                    ok, res = backend.run_cli(["msg", target, text, "wait_ack"])
                    message_log.append(f"DM an {target}: {text}")
                    show_message(stdscr, f"Direktnachricht an {target}", res, is_error=not ok)
        elif ch in (ord("3"), ord("c"), ord("C")):
            ch_num = prompt_input(stdscr, "Kanalnachricht", "Kanalnummer (0-7):", default="0")
            if ch_num:
                text = prompt_input(stdscr, f"Nachricht für Kanal {ch_num}", "Nachrichtentext:")
                if text:
                    ok, res = backend.run_cli(["chan", ch_num, text])
                    message_log.append(f"CH {ch_num}: {text}")
                    show_message(stdscr, f"Kanal {ch_num}", res, is_error=not ok)
        elif ch in (ord("4"), ord("s"), ord("S")):
            safe_addstr(stdscr, max_y - 2, 2, "Lade Nachrichten vom Node...", get_color(COLOR_WARNING))
            stdscr.refresh()
            ok, res = backend.run_cli(["sync_msgs"])
            display_scrollable_text(stdscr, "Synchronisierte Nachrichten", res)
        elif ch in (ord("5"), ord("k"), ord("K")):
            safe_addstr(stdscr, max_y - 2, 2, "Lade Kanäle...", get_color(COLOR_WARNING))
            stdscr.refresh()
            ok, res = backend.run_cli(["get_channels"])
            display_scrollable_text(stdscr, "Kanäle", res)
        elif ch == ord("6"):
            ch_num = prompt_input(stdscr, "Kanal einrichten", "Kanalnummer (1-7):", default="1")
            if ch_num:
                name = prompt_input(stdscr, "Kanalname", "Name für den Kanal:")
                if name:
                    key_val = prompt_input(stdscr, "Schlüssel (optional)", "Verschlüsselungsschlüssel (oder leer für Standard):")
                    args = ["set_channel", ch_num, name]
                    if key_val:
                        args.append(key_val)
                    ok, res = backend.run_cli(args)
                    show_message(stdscr, "Kanal eingerichtet", res, is_error=not ok)
        elif ch == ord("7"):
            scope = prompt_input(stdscr, "Flood Scope", "Scope Region (z.B. 0 für Standard, * für Unscoped, oder #Region):", default="0")
            if scope:
                ok, res = backend.run_cli(["scope", scope])
                show_message(stdscr, "Flood Scope", res, is_error=not ok)
