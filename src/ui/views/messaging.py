"""Messaging and channel management backed by the persistent ChatStore."""

import curses
from typing import Any, Callable, Optional

from ...backend.chat_store import ChatStore, ChatTarget
from ...backend.executor import MeshCoreBackend
from ...config import Config
from ..async_task import BackgroundTask, run_with_progress
from ..colors import COLOR_DIM, COLOR_HEADER, COLOR_NORMAL, COLOR_SUCCESS, get_color
from ..widgets import (
    display_scrollable_text,
    draw_box,
    draw_header,
    draw_status_bar,
    prompt_confirm,
    prompt_input,
    read_key,
    safe_addstr,
    show_message,
)
from .chat_view import run_chat_view


def _channel_target(store: ChatStore, channel_num: int) -> ChatTarget:
    for target in store.targets:
        if target.is_channel and target.channel_num == channel_num:
            return target
    name = "Public (0)" if channel_num == 0 else f"Kanal {channel_num}"
    return store.get_or_create_target(name, True, channel_num)


def run_messaging_view(stdscr: curses.window, backend: MeshCoreBackend, config: Config) -> None:
    """Messaging menu; sends and syncs exclusively through ``ChatStore``."""
    message_log: list = []
    chat_store = ChatStore()
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
            draw_header(stdscr, "Kanal- & Scope-Verwaltung", f"Port: {config.port}")
            draw_status_bar(
                stdscr,
                "[0] Chat [1] Broadcast [2] Direkt [3/c] Kanal [4] Sync [5] Kanäle [6] Setup [7] Scope [8] Löschen [Esc] Zurück",
                "Persistenter Verlauf",
            )
            view_h = max(0, max_y - 3)
            draw_box(stdscr, 1, 0, view_h, max_x, "Kanal- und Scope-Zentrum")
            options = [
                ("0", "💬 Interaktives Chatfenster öffnen (Live-Chat & Verlauf)", "ChatStore"),
                ("1", "Öffentliche Nachricht senden (Kanal 0 Broadcast)", "public <text>"),
                ("2", "Direktnachricht an Kontakt senden", "msg <kontakt> <text>"),
                ("3/c", "Nachricht an bestimmten Kanal senden (0-7)", "chan <nummer> <text>"),
                ("4", "Neue Nachrichten vom Node synchronisieren", "ChatStore.sync_from_backend"),
                ("5", "Konfigurierte Kanäle anzeigen", "get_channels"),
                ("6", "Kanal konfigurieren (Nummer, Name, Schlüssel)", "set_channel <nr> <name> [key]"),
                ("7", "Flood-Scope konfigurieren", "scope <region>"),
                ("8", "Kanal löschen (Companion + lokaler Verlauf)", "remove_channel <nr>"),
            ]
            safe_addstr(stdscr, 3, 3, "Wähle eine Aktion aus:", get_color(COLOR_HEADER) | curses.A_BOLD)
            for idx, (key, title, cmd_hint) in enumerate(options):
                y = 5 + idx * 2
                safe_addstr(stdscr, y, 4, f"[{key}] {title}", get_color(COLOR_NORMAL) | curses.A_BOLD)
                safe_addstr(stdscr, y + 1, 8, f"meshcli: {cmd_hint}", get_color(COLOR_DIM))

            if message_log:
                safe_addstr(stdscr, max(1, view_h - 4), 3, "Letzte Aktivität:", get_color(COLOR_HEADER))
                safe_addstr(stdscr, max(1, view_h - 3), 5, message_log[-1], get_color(COLOR_SUCCESS))

            stdscr.refresh()
            ch = read_key(stdscr)
            if ch is None or ch == curses.KEY_RESIZE:
                continue
            if ch in (27, ord("q"), ord("Q")):
                break
            if ch == ord("0"):
                run_chat_view(stdscr, backend, config, chat_store=chat_store)
            elif ch in (ord("1"), ord("p"), ord("P")):
                text = prompt_input(stdscr, "Öffentliche Nachricht (Broadcast)", "Nachricht eingeben:")
                if text:
                    target = _channel_target(chat_store, 0)
                    result = run_io(
                        "Öffentliche Nachricht",
                        lambda text=text, target=target: chat_store.send_message(backend, target, text),
                    )
                    if result is not None:
                        ok, res = result
                        message_log.append(f"Public ({'OK' if ok else 'Fehler'}): {text}")
                        show_message(stdscr, "Öffentliche Nachricht", res, is_error=not ok)
            elif ch in (ord("2"), ord("d"), ord("D")):
                target_name = prompt_input(stdscr, "Direktnachricht", "Name oder ID des Kontakts:")
                if target_name:
                    text = prompt_input(stdscr, f"Nachricht an '{target_name}'", "Nachrichtentext:")
                    if text:
                        target = chat_store.get_or_create_target(target_name, False)
                        result = run_io(
                            f"Direktnachricht an {target_name}",
                            lambda text=text, target=target: chat_store.send_message(backend, target, text),
                        )
                        if result is not None:
                            ok, res = result
                            message_log.append(f"DM an {target_name} ({'OK' if ok else 'Fehler'}): {text}")
                            show_message(stdscr, f"Direktnachricht an {target_name}", res, is_error=not ok)
            elif ch in (ord("3"), ord("c"), ord("C")):
                ch_num_text = prompt_input(stdscr, "Kanalnachricht", "Kanalnummer (0-7):", default="0")
                if ch_num_text:
                    try:
                        ch_num = int(ch_num_text)
                        if not 0 <= ch_num <= 7:
                            raise ValueError
                    except ValueError:
                        show_message(stdscr, "Kanalnachricht", "Kanalnummer muss zwischen 0 und 7 liegen.", is_error=True)
                        continue
                    text = prompt_input(stdscr, f"Nachricht für Kanal {ch_num}", "Nachrichtentext:")
                    if text:
                        target = _channel_target(chat_store, ch_num)
                        result = run_io(
                            f"Kanal {ch_num}",
                            lambda text=text, target=target: chat_store.send_message(backend, target, text),
                        )
                        if result is not None:
                            ok, res = result
                            message_log.append(f"CH {ch_num} ({'OK' if ok else 'Fehler'}): {text}")
                            show_message(stdscr, f"Kanal {ch_num}", res, is_error=not ok)
            elif ch in (ord("4"), ord("s"), ord("S")):
                new_count = run_io("Nachrichten synchronisieren", lambda: chat_store.sync_from_backend(backend))
                if new_count is not None:
                    lines = [f"Sync abgeschlossen: {new_count} neue Nachricht(en).", ""]
                    for target in chat_store.targets:
                        history = chat_store.get_history(target.id)
                        if history:
                            lines.append(f"{target.display_tag}: {len(history)} Nachricht(en) im persistenten Verlauf")
                    display_scrollable_text(stdscr, "Synchronisierte Nachrichten", "\n".join(lines))
            elif ch in (ord("5"), ord("k"), ord("K")):
                result = run_io("Kanäle laden", lambda: backend.run_cli(["get_channels"]))
                if result is not None:
                    ok, res = result
                    display_scrollable_text(stdscr, "Kanäle" if ok else "Kanäle – Fehler", res)
            elif ch == ord("6"):
                ch_num = prompt_input(stdscr, "Kanal einrichten", "Kanalnummer (1-7):", default="1")
                if ch_num:
                    name = prompt_input(stdscr, "Kanalname", "Name für den Kanal:")
                    if name:
                        key_val = prompt_input(stdscr, "Schlüssel (optional)", "Verschlüsselungsschlüssel (oder leer für Standard):")
                        args = ["set_channel", ch_num, name]
                        if key_val:
                            args.append(key_val)
                        result = run_io("Kanal einrichten", lambda: backend.run_cli(args))
                        if result is not None:
                            ok, res = result
                            show_message(stdscr, "Kanal eingerichtet", res, is_error=not ok)
            elif ch == ord("7"):
                scope = prompt_input(
                    stdscr,
                    "Flood Scope",
                    "Scope Region (z.B. 0 für Standard, * für Unscoped, oder #Region):",
                    default="0",
                )
                if scope:
                    result = run_io("Flood Scope", lambda: backend.run_cli(["scope", scope]))
                    if result is not None:
                        ok, res = result
                        show_message(stdscr, "Flood Scope", res, is_error=not ok)
            elif ch == ord("8"):
                ch_num_text = prompt_input(stdscr, "Kanal löschen", "Kanalnummer (1-7):", default="1")
                if ch_num_text:
                    try:
                        ch_num = int(ch_num_text)
                        if not 1 <= ch_num <= 7:
                            raise ValueError
                    except ValueError:
                        show_message(stdscr, "Kanal löschen", "Kanalnummer muss zwischen 1 und 7 liegen.", is_error=True)
                        continue
                    target = _channel_target(chat_store, ch_num)
                    if prompt_confirm(
                        stdscr,
                        "Kanal auf Companion und lokal löschen",
                        f"Kanal {ch_num} und seinen gesamten lokalen Verlauf wirklich löschen?",
                    ):
                        result = run_io(
                            "Kanal löschen",
                            lambda target=target: chat_store.delete_channel(backend, target),
                        )
                        if result is not None:
                            ok, res = result
                            message_log.append(f"Kanal {ch_num} ({'gelöscht' if ok else 'Fehler'})")
                            show_message(stdscr, "Kanal löschen", res, is_error=not ok)
    finally:
        task.close()
