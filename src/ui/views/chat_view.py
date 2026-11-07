"""Interactive, non-blocking chat window for channels and direct messages."""

import curses
import time
from typing import List, Optional, Tuple

from ...backend.chat_store import ChatMessage, ChatStore, ChatTarget
from ...backend.executor import MeshCoreBackend
from ...config import Config
from ..async_task import BackgroundTask
from ..colors import (
    COLOR_DIM,
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
    ensure_visible,
    key_to_text,
    prompt_confirm,
    prompt_input,
    read_key,
    safe_addstr,
    safe_curs_set,
    safe_move,
    show_message,
    wrap_text_lines,
)

FOCUS_INPUT = 0
FOCUS_ROOMS = 1
FOCUS_HISTORY = 2

HistoryEntry = Tuple[str, int, int]


class ChatSyncScheduler:
    """Schedule the next automatic sync relative to completed backend work."""

    def __init__(self, refresh_interval: float) -> None:
        try:
            interval = float(refresh_interval)
        except (TypeError, ValueError):
            interval = 5.0
        # A malformed zero/negative setting must not create a busy loop.
        self.interval = max(0.1, interval)
        self.next_sync_at: Optional[float] = None

    def schedule(self, completed_at: float) -> None:
        """Schedule one sync a full interval after *completed_at*."""
        self.next_sync_at = completed_at + self.interval

    def start_if_due(self, now: float) -> bool:
        """Claim a due sync; a new deadline is set only after it completes."""
        if self.next_sync_at is None or now < self.next_sync_at:
            return False
        self.next_sync_at = None
        return True


def format_history_entries(history: List[ChatMessage], width: int) -> List[HistoryEntry]:
    """Return wrapped ``(text, color, message_index)`` entries for rendering."""
    formatted: List[HistoryEntry] = []
    for message_index, msg in enumerate(history):
        time_tag = f"[{msg.timestamp}]"
        status_tag = f" {msg.status}" if msg.status else ""
        if msg.is_outgoing:
            header = f"{time_tag} <Ich>{status_tag}: "
            color = COLOR_SUCCESS
        else:
            header = f"{time_tag} <{msg.sender}>{status_tag}: "
            color = COLOR_WARNING if msg.sender.startswith("Sensor") else COLOR_HEADER
        for line in wrap_text_lines(header + msg.text, width):
            formatted.append((line, color, message_index))
    return formatted


def format_history_lines(history: List[ChatMessage], width: int) -> List[Tuple[str, int]]:
    """Format and wrap messages without losing continuation lines."""
    return [(text, color) for text, color, _ in format_history_entries(history, width)]


def update_message_selection(
    selected: Optional[int],
    previous_count: int,
    current_count: int,
    follow_latest: bool,
) -> Optional[int]:
    """Keep a message selection valid without moving it while reading history."""
    if current_count <= 0:
        return None
    if current_count > previous_count and follow_latest:
        return current_count - 1
    if selected is None:
        return current_count - 1
    return max(0, min(selected, current_count - 1))


def ensure_history_message_visible(
    entries: List[HistoryEntry],
    selected: Optional[int],
    visible_count: int,
    scroll_offset: int,
) -> int:
    """Return a newest-relative offset which contains the selected message."""
    total_lines = len(entries)
    max_scroll = max(0, total_lines - max(0, visible_count))
    offset = max(0, min(scroll_offset, max_scroll))
    if selected is None or visible_count <= 0 or total_lines <= visible_count:
        return offset

    selected_lines = [index for index, entry in enumerate(entries) if entry[2] == selected]
    if not selected_lines:
        return offset

    viewport_start = total_lines - visible_count - offset
    first, last = selected_lines[0], selected_lines[-1]
    if first < viewport_start:
        viewport_start = first
    elif last >= viewport_start + visible_count:
        viewport_start = last - visible_count + 1
        # For a message taller than the viewport, show its beginning.
        if viewport_start > first:
            viewport_start = first

    viewport_start = max(0, min(viewport_start, total_lines - visible_count))
    return total_lines - visible_count - viewport_start


def run_chat_view(
    stdscr: curses.window,
    backend: MeshCoreBackend,
    config: Config,
    initial_target: Optional[str] = None,
    chat_store: Optional[ChatStore] = None,
) -> None:
    """Run chat while one background worker performs all serial operations."""
    chat_store = chat_store or ChatStore()
    worker = BackgroundTask()
    sync_scheduler = ChatSyncScheduler(getattr(config, "refresh_interval", 5))
    pending_action = "init"
    pending_send: Optional[Tuple[ChatTarget, str]] = None
    exit_when_done = False

    active_target_idx = 0
    if initial_target:
        clean_name = initial_target.lstrip("@#").strip()
        is_chan = initial_target.startswith("#")
        ch_num = None
        if is_chan:
            try:
                ch_num = int(clean_name.split("(")[-1].strip(")"))
            except ValueError:
                pass
        target = chat_store.get_or_create_target(clean_name, is_chan, ch_num)
        active_target_idx = chat_store.targets.index(target)

    def initialize() -> int:
        # One worker: populate and sync are never concurrent serial commands.
        chat_store.populate_targets_from_backend(backend)
        return chat_store.sync_from_backend(backend)

    worker.start(initialize)
    status_notice = "Initialisiere Räume und Nachrichten …"
    focus = FOCUS_INPUT
    input_buffer: List[str] = []
    cursor_pos = 0
    scroll_offset = 0  # Offset from the newest history line.
    room_offset = 0
    selected_message_idx: Optional[int] = None
    selection_follow_latest = True
    history_target_id: Optional[str] = None
    history_message_count = 0
    selection_scroll_pending = False
    stdscr.timeout(100)

    try:
        while True:
            completed = worker.poll()
            if completed is not None:
                action = pending_action
                pending_action = ""
                if action in ("init", "sync", "auto_sync"):
                    # Base the next deadline on completion, never on start time.
                    sync_scheduler.schedule(time.monotonic())
                if action == "init":
                    if completed.success:
                        status_notice = f"Initialisierung abgeschlossen: {completed.value} neue Nachricht(en)."
                    else:
                        status_notice = f"Initialisierung fehlgeschlagen: {completed.value}"
                elif action in ("sync", "auto_sync"):
                    automatic = action == "auto_sync"
                    label = "Auto-Sync" if automatic else "Sync"
                    if completed.success:
                        status_notice = f"{label} abgeschlossen: {completed.value} neue Nachricht(en)."
                        # Preserve an older-history viewport; follow-latest stays at zero.
                    else:
                        status_notice = f"{label} fehlgeschlagen: {completed.value}"
                        if not automatic and not exit_when_done:
                            show_message(stdscr, "Synchronisierungsfehler", str(completed.value), is_error=True)
                elif action == "send":
                    sent = pending_send
                    pending_send = None
                    ok = completed.success and bool(completed.value[0])
                    response = completed.value[1] if completed.success else str(completed.value)
                    if ok:
                        status_notice = "✓ Nachricht gesendet."
                        scroll_offset = 0
                    else:
                        status_notice = f"✗ Senden fehlgeschlagen: {response}"
                        # The failed draft and anything typed while sending are kept.
                        if sent is not None:
                            current = "".join(input_buffer)
                            restored = sent[1] + (f" {current}" if current else "")
                            input_buffer = list(restored)
                            cursor_pos = len(input_buffer)
                        if not exit_when_done:
                            show_message(stdscr, "Sendefehler", str(response), is_error=True)

                # Normal exits wait for the writer, preventing an older store
                # instance from overwriting a newly opened chat later on.
                if exit_when_done:
                    break

            if not worker.busy and not exit_when_done and sync_scheduler.start_if_due(time.monotonic()):
                if worker.start(lambda: chat_store.sync_from_backend(backend)):
                    pending_action = "auto_sync"
                    status_notice = "Auto-Sync läuft …"
                else:
                    # Do not spin if another owner won the worker in between.
                    sync_scheduler.schedule(time.monotonic())

            max_y, max_x = stdscr.getmaxyx()
            stdscr.clear()

            targets = list(chat_store.targets)
            if not targets:
                targets = [chat_store.get_or_create_target("Public (0)", True, 0)]
            active_target_idx = max(0, min(active_target_idx, len(targets) - 1))
            active_target = targets[active_target_idx]
            # The open chat is visible, so its new messages count as read.
            chat_store.mark_read(active_target.id)
            history = list(chat_store.get_history(active_target.id))
            unread_elsewhere = [
                (target, count)
                for target, count in chat_store.unread_targets()
                if target.id != active_target.id
            ]

            if history_target_id != active_target.id:
                history_target_id = active_target.id
                history_message_count = 0
                selected_message_idx = None
                selection_follow_latest = True
                scroll_offset = 0
            selected_message_idx = update_message_selection(
                selected_message_idx,
                history_message_count,
                len(history),
                follow_latest=selection_follow_latest and scroll_offset == 0,
            )
            history_message_count = len(history)

            input_h = min(3, max(0, max_y - 2))
            main_h = max(0, max_y - 2 - input_h)
            if max_x >= 50:
                sidebar_w = min(26, max(18, max_x // 3))
            else:
                sidebar_w = min(18, max(0, max_x // 3))
            chat_x = sidebar_w
            chat_w = max(0, max_x - sidebar_w)

            mode_text = "SIMULATION" if config.simulation_mode else f"USB: {config.port}"
            draw_header(stdscr, "MeshCore Chatfenster", f"Raum: {active_target.display_tag} | {mode_text}")
            focus_labels = {
                FOCUS_INPUT: "Eingabe",
                FOCUS_ROOMS: "Raumliste",
                FOCUS_HISTORY: "Verlauf",
            }
            if focus == FOCUS_HISTORY:
                status_left = "[↑/↓] Nachricht | [PgUp/PgDn] Scroll | [Entf/X] lokal löschen | [L] lokal leeren"
            elif focus == FOCUS_ROOMS:
                status_left = "[↑/↓] Chat | [Enter] öffnen | [Entf/X] Chat + Verlauf lokal löschen | [L] nur leeren"
            else:
                status_left = f"[Tab] {focus_labels[focus]} | [Enter] Senden | [R] Sync | [N] Neu | [Esc] Menü"
            if status_notice:
                status_right = status_notice
            elif focus == FOCUS_HISTORY and selected_message_idx is not None:
                status_right = f"Nachricht {selected_message_idx + 1}/{len(history)}"
            else:
                status_right = f"Nachrichten: {len(history)}"
            if unread_elsewhere:
                summary = ", ".join(
                    f"{target.display_tag} +{count}" for target, count in unread_elsewhere
                )
                status_right = f"Neu: {summary} | {status_right}"
            draw_status_bar(stdscr, status_left, status_right)

            draw_box(stdscr, 1, 0, main_h, sidebar_w, "Kanäle & Kontakte")
            visible_room_rows = max(0, main_h - 2)
            room_offset = ensure_visible(active_target_idx, room_offset, visible_room_rows, len(targets))
            visible_targets = targets[room_offset : room_offset + visible_room_rows]
            for row, target in enumerate(visible_targets):
                idx = room_offset + row
                item_y = 2 + row
                is_active = idx == active_target_idx
                is_highlighted = is_active and focus == FOCUS_ROOMS
                prefix = "▶ " if is_active else "  "
                tag = "#" if target.is_channel else "@"
                label = f"{prefix}{tag}{target.name}"
                unread = chat_store.unread_count(target.id)
                count = len(chat_store.get_history(target.id))
                # Unread messages replace the total count and stand out.
                badge = f"[+{unread}]" if unread else (f"[{count}]" if count else "")
                avail_w = max(0, sidebar_w - 4 - len(badge))
                disp_text = label[:avail_w].ljust(avail_w)
                if is_highlighted:
                    attr = get_color(COLOR_SELECTED) | curses.A_BOLD | curses.A_REVERSE
                elif is_active:
                    attr = get_color(COLOR_HEADER) | curses.A_BOLD
                elif unread:
                    attr = get_color(COLOR_SUCCESS) | curses.A_BOLD
                else:
                    attr = get_color(COLOR_NORMAL)
                safe_addstr(stdscr, item_y, 1, disp_text, attr)
                if badge:
                    badge_attr = (
                        get_color(COLOR_SUCCESS) | curses.A_BOLD | curses.A_REVERSE
                        if unread and not is_highlighted
                        else attr
                    )
                    safe_addstr(stdscr, item_y, 1 + len(disp_text), badge, badge_attr)

            draw_box(stdscr, 1, chat_x, main_h, chat_w, f"Chatverlauf: {active_target.display_tag}")
            chat_inner_h = max(0, main_h - 2)
            chat_inner_w = max(0, chat_w - 4)
            history_entries = format_history_entries(history, chat_inner_w) if history and chat_inner_w > 0 else []
            if not history:
                safe_addstr(stdscr, 3, chat_x + 3, "Noch keine Nachrichten. Schreibe die erste!", get_color(COLOR_DIM))
            elif chat_inner_w > 0:
                total_lines = len(history_entries)
                if selection_scroll_pending:
                    scroll_offset = ensure_history_message_visible(
                        history_entries, selected_message_idx, chat_inner_h, scroll_offset
                    )
                    selection_scroll_pending = False
                max_scroll = max(0, total_lines - chat_inner_h)
                scroll_offset = max(0, min(scroll_offset, max_scroll))
                start_idx = max(0, total_lines - chat_inner_h - scroll_offset)
                visible_entries = history_entries[start_idx : start_idx + chat_inner_h]
                for line_idx, (text_line, line_color, message_index) in enumerate(visible_entries):
                    if focus == FOCUS_HISTORY and message_index == selected_message_idx:
                        attr = get_color(COLOR_SELECTED) | curses.A_REVERSE | curses.A_BOLD
                    else:
                        attr = get_color(line_color)
                    safe_addstr(stdscr, 2 + line_idx, chat_x + 2, text_line, attr)
                if scroll_offset > 0:
                    safe_addstr(
                        stdscr,
                        1,
                        max(chat_x + 1, chat_x + chat_w - 18),
                        f" ↑ {scroll_offset} ältere ",
                        get_color(COLOR_SELECTED) | curses.A_REVERSE,
                    )

            input_y = 1 + main_h
            draw_box(stdscr, input_y, 0, input_h, max_x, f"Nachricht an {active_target.display_tag}")
            prompt_str = f"✍️  {active_target.display_tag} > "
            if input_h >= 3:
                safe_addstr(stdscr, input_y + 1, 2, prompt_str, get_color(COLOR_HEADER) | curses.A_BOLD)
            input_field_x = 2 + len(prompt_str)
            available_input_w = max(0, max_x - input_field_x - 3)
            input_text = "".join(input_buffer)
            if available_input_w > 0 and input_h >= 3:
                if cursor_pos >= available_input_w:
                    start = cursor_pos - available_input_w + 1
                    visible_input = input_text[start : start + available_input_w]
                    render_cursor_x = input_field_x + available_input_w - 1
                else:
                    visible_input = input_text[:available_input_w]
                    render_cursor_x = input_field_x + cursor_pos
                safe_addstr(stdscr, input_y + 1, input_field_x, visible_input, get_color(COLOR_NORMAL) | curses.A_BOLD)
                if focus == FOCUS_INPUT:
                    safe_move(stdscr, input_y + 1, render_cursor_x)

            safe_curs_set(1 if focus == FOCUS_INPUT and input_h >= 3 and available_input_w > 0 else 0)
            stdscr.refresh()
            key = read_key(stdscr)
            if key is None or key == curses.KEY_RESIZE:
                continue

            if key == 27:
                if focus != FOCUS_INPUT:
                    focus = FOCUS_INPUT
                elif worker.busy:
                    exit_when_done = True
                    status_notice = "Verlasse den Chat nach Abschluss der Backend-Aktion …"
                elif prompt_confirm(stdscr, "Chat beenden", "Zurück zum Hauptmenü?"):
                    break
            elif key == ord("\t"):
                focus = (focus + 1) % 3
            elif key in (curses.KEY_UP, ord("k"), ord("K")) and focus == FOCUS_ROOMS:
                if worker.busy and pending_action == "send":
                    status_notice = "Raumwechsel ist während des Sendens gesperrt."
                else:
                    active_target_idx = max(0, active_target_idx - 1)
                    scroll_offset = 0
            elif key in (curses.KEY_DOWN, ord("j"), ord("J")) and focus == FOCUS_ROOMS:
                if worker.busy and pending_action == "send":
                    status_notice = "Raumwechsel ist während des Sendens gesperrt."
                else:
                    active_target_idx = min(len(targets) - 1, active_target_idx + 1)
                    scroll_offset = 0
            elif focus == FOCUS_ROOMS and key in (10, 13, curses.KEY_ENTER, ord(" "), curses.KEY_RIGHT):
                focus = FOCUS_INPUT
            elif focus == FOCUS_ROOMS and isinstance(key, int) and ord("1") <= key <= ord("9"):
                if worker.busy and pending_action == "send":
                    status_notice = "Raumwechsel ist während des Sendens gesperrt."
                else:
                    num_idx = key - ord("1")
                    if num_idx < len(targets):
                        active_target_idx = num_idx
                        scroll_offset = 0
                        focus = FOCUS_INPUT
            elif key in (curses.KEY_UP, curses.KEY_DOWN) and focus == FOCUS_HISTORY:
                if history and selected_message_idx is not None:
                    delta = -1 if key == curses.KEY_UP else 1
                    new_selection = max(0, min(selected_message_idx + delta, len(history) - 1))
                    if new_selection != selected_message_idx:
                        selected_message_idx = new_selection
                        selection_follow_latest = False
                        selection_scroll_pending = True
            elif key in (curses.KEY_PPAGE, curses.KEY_NPAGE) and focus == FOCUS_HISTORY:
                page_step = max(1, chat_inner_h - 1)
                if key == curses.KEY_PPAGE:
                    scroll_offset += page_step
                else:
                    scroll_offset = max(0, scroll_offset - page_step)
            elif key == curses.KEY_HOME and focus == FOCUS_HISTORY:
                scroll_offset = max(0, len(history_entries) - chat_inner_h)
                if history:
                    selected_message_idx = 0
                    selection_follow_latest = False
                    selection_scroll_pending = True
            elif key == curses.KEY_END and focus == FOCUS_HISTORY:
                scroll_offset = 0
                selection_follow_latest = True
                if history:
                    selected_message_idx = len(history) - 1
                    selection_scroll_pending = True
            elif key in (curses.KEY_DC, ord("x"), ord("X")) and focus == FOCUS_ROOMS:
                if worker.busy:
                    status_notice = "Chat erst nach Abschluss der Backend-Aktion löschen."
                elif prompt_confirm(
                    stdscr,
                    "Chat und lokalen Verlauf löschen",
                    (
                        f"{active_target.display_tag} mit komplettem lokalem Verlauf löschen? "
                        "Kontakt/Kanal auf dem Companion bleibt unverändert."
                    ),
                ):
                    deleted_id = active_target.id
                    deleted_tag = active_target.display_tag
                    if chat_store.delete_conversation(deleted_id):
                        active_target_idx = max(
                            0, min(active_target_idx, len(chat_store.targets) - 1)
                        )
                        history_target_id = None
                        history_message_count = 0
                        selected_message_idx = None
                        selection_follow_latest = True
                        selection_scroll_pending = False
                        scroll_offset = 0
                        status_notice = f"{deleted_tag}: Chat und lokaler Verlauf gelöscht."
                    else:
                        status_notice = "Chat konnte nicht gelöscht werden."
            elif key in (curses.KEY_DC, ord("x"), ord("X")) and focus == FOCUS_HISTORY:
                if selected_message_idx is None or not history:
                    status_notice = "Keine lokale Nachricht zum Löschen ausgewählt."
                elif worker.busy:
                    status_notice = "Lokale Nachricht erst nach Abschluss der Backend-Aktion löschen."
                elif prompt_confirm(
                    stdscr,
                    "Nur lokale Nachricht löschen",
                    (
                        f"{history[selected_message_idx].sender}: "
                        f"{history[selected_message_idx].text[:40]} – lokal löschen?"
                    ),
                ):
                    if chat_store.delete_message(active_target.id, selected_message_idx):
                        status_notice = "Lokale Nachricht gelöscht."
                        selected_message_idx = update_message_selection(
                            selected_message_idx,
                            len(history),
                            len(history) - 1,
                            follow_latest=False,
                        )
                        history_message_count = len(chat_store.get_history(active_target.id))
                        selection_follow_latest = False
                        selection_scroll_pending = True
                    else:
                        status_notice = "Lokale Nachricht konnte nicht gelöscht werden."
            elif key in (ord("r"), ord("R")) and focus != FOCUS_INPUT:
                if worker.busy:
                    status_notice = "Bitte warten: Es läuft bereits eine Backend-Aktion."
                elif worker.start(lambda: chat_store.sync_from_backend(backend)):
                    pending_action = "sync"
                    # A manual sync supersedes an automatic one that was about to run.
                    sync_scheduler.schedule(time.monotonic())
                    status_notice = "Synchronisiere Nachrichten …"
            elif key in (ord("n"), ord("N")) and focus != FOCUS_INPUT:
                if worker.busy:
                    status_notice = "Neuer Chat erst nach Abschluss der Backend-Aktion."
                else:
                    user_input = prompt_input(
                        stdscr,
                        "Neuen Chat starten",
                        "Kanal (#0 bis #7) oder Kontaktname (@Name):",
                    )
                    if user_input:
                        user_input = user_input.strip()
                        if user_input.startswith("#"):
                            ch_str = user_input.lstrip("#").strip()
                            try:
                                ch_num = int(ch_str)
                                name = "Public (0)" if ch_num == 0 else f"Kanal {ch_num}"
                            except ValueError:
                                ch_num = None
                                name = ch_str
                            target = chat_store.get_or_create_target(name, True, ch_num)
                        else:
                            target = chat_store.get_or_create_target(user_input.lstrip("@").strip(), False)
                        active_target_idx = chat_store.targets.index(target)
                        focus = FOCUS_INPUT
                        scroll_offset = 0
            elif key in (ord("l"), ord("L")) and focus != FOCUS_INPUT:
                if worker.busy:
                    status_notice = "Lokalen Verlauf erst nach Abschluss der Backend-Aktion leeren."
                elif prompt_confirm(
                    stdscr,
                    "Lokalen Verlauf leeren",
                    f"Lokalen Verlauf für {active_target.display_tag} wirklich leeren?",
                ):
                    chat_store.clear_history(active_target.id)
                    status_notice = "Lokaler Verlauf geleert."
                    selected_message_idx = None
                    selection_follow_latest = True
                    history_message_count = 0
                    scroll_offset = 0
            elif focus == FOCUS_INPUT:
                if key in (10, 13, curses.KEY_ENTER):
                    msg_text = "".join(input_buffer).strip()
                    if msg_text:
                        if worker.busy:
                            status_notice = "Senden wartet auf die laufende Backend-Aktion; Entwurf bleibt erhalten."
                        else:
                            raw_draft = "".join(input_buffer)
                            target = active_target
                            if worker.start(
                                lambda target=target, msg_text=msg_text: chat_store.send_message(backend, target, msg_text)
                            ):
                                pending_action = "send"
                                pending_send = (target, raw_draft)
                                input_buffer.clear()
                                cursor_pos = 0
                                status_notice = f"Sende Nachricht an {target.display_tag} …"
                elif key in (curses.KEY_BACKSPACE, 127, 8):
                    if cursor_pos > 0:
                        input_buffer.pop(cursor_pos - 1)
                        cursor_pos -= 1
                elif key == curses.KEY_DC:
                    if cursor_pos < len(input_buffer):
                        input_buffer.pop(cursor_pos)
                elif key == curses.KEY_LEFT:
                    cursor_pos = max(0, cursor_pos - 1)
                elif key == curses.KEY_RIGHT:
                    cursor_pos = min(cursor_pos + 1, len(input_buffer))
                elif key == curses.KEY_HOME:
                    cursor_pos = 0
                elif key == curses.KEY_END:
                    cursor_pos = len(input_buffer)
                elif key in (curses.KEY_UP, curses.KEY_PPAGE):
                    focus = FOCUS_HISTORY
                    if key == curses.KEY_PPAGE:
                        scroll_offset += max(1, chat_inner_h - 1)
                    elif history and selected_message_idx is not None:
                        selected_message_idx = max(0, selected_message_idx - 1)
                        selection_follow_latest = False
                        selection_scroll_pending = True
                else:
                    char = key_to_text(key)
                    if char is not None:
                        input_buffer.insert(cursor_pos, char)
                        cursor_pos += 1
    finally:
        worker.close()
        safe_curs_set(0)
        stdscr.timeout(-1)
