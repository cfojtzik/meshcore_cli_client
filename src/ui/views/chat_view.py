"""Interactive Chat Window with conversation history for channels and direct messages."""

import curses
from typing import List, Optional

from ...backend.chat_store import ChatMessage, ChatStore, ChatTarget
from ...backend.executor import MeshCoreBackend
from ...config import Config
from ..colors import (
    COLOR_DIM,
    COLOR_ERROR,
    COLOR_HEADER,
    COLOR_NORMAL,
    COLOR_SELECTED,
    COLOR_STATUS,
    COLOR_SUCCESS,
    COLOR_WARNING,
    get_color,
)
from ..widgets import (
    draw_box,
    draw_header,
    draw_status_bar,
    prompt_confirm,
    prompt_input,
    safe_addstr,
    show_message,
)

FOCUS_INPUT = 0
FOCUS_ROOMS = 1
FOCUS_HISTORY = 2


def run_chat_view(stdscr: curses.window, backend: MeshCoreBackend, config: Config) -> None:
    """Full-featured interactive chat window with history for channels & DMs."""
    chat_store = ChatStore()
    chat_store.populate_targets_from_backend(backend)

    # Initial sync
    chat_store.sync_from_backend(backend)

    active_target_idx = 0
    focus = FOCUS_INPUT

    input_buffer: List[str] = []
    cursor_pos = 0
    scroll_offset = 0  # Offset from bottom of history
    status_notice = ""

    while True:
        max_y, max_x = stdscr.getmaxyx()
        stdscr.clear()

        # Ensure valid target index
        if not chat_store.targets:
            chat_store._init_default_targets()
        active_target_idx = max(0, min(active_target_idx, len(chat_store.targets) - 1))
        active_target = chat_store.targets[active_target_idx]

        # Geometry calculations
        header_h = 1
        status_h = 1
        input_h = 3
        main_h = max(6, max_y - header_h - status_h - input_h)

        # Width of left sidebar (rooms/contacts)
        sidebar_w = min(26, max(18, max_x // 3))
        chat_x = sidebar_w
        chat_w = max_x - sidebar_w

        # Draw Top Header
        mode_text = "SIMULATION" if config.simulation_mode else f"USB: {config.port}"
        target_title = f"Raum: {active_target.display_tag}"
        draw_header(stdscr, "MeshCore Chatfenster", f"{target_title} | {mode_text}")

        # Draw Status Bar
        focus_labels = {
            FOCUS_INPUT: "Eingabe (Tippen zum Schreiben)",
            FOCUS_ROOMS: "Raumliste (↑/↓ wählen)",
            FOCUS_HISTORY: "Verlauf (↑/↓ scrollen)",
        }
        status_left = f"[Tab] Fokus ({focus_labels[focus]}) | [Enter] Senden | [R] Sync | [N] Neu | [Esc] Menü"
        status_right = status_notice if status_notice else f"Nachrichten: {len(chat_store.get_history(active_target.id))}"
        draw_status_bar(stdscr, status_left, status_right)

        # -------------------------------------------------------------
        # 1. Left Pane: Räume & Kontakte
        # -------------------------------------------------------------
        sidebar_border_attr = (
            get_color(COLOR_SELECTED) if focus == FOCUS_ROOMS else get_color(COLOR_DIM)
        )
        draw_box(stdscr, 1, 0, main_h, sidebar_w, "Kanäle & Kontakte")

        visible_room_rows = main_h - 2
        for idx, target in enumerate(chat_store.targets[:visible_room_rows]):
            item_y = 2 + idx
            is_active = idx == active_target_idx
            is_highlighted = is_active and focus == FOCUS_ROOMS

            prefix = "▶ " if is_active else "  "
            tag = "#" if target.is_channel else "@"
            label = f"{prefix}{tag}{target.name}"

            # Unread / count badge
            count = len(chat_store.get_history(target.id))
            badge = f"[{count}]" if count > 0 else ""

            avail_w = sidebar_w - 4 - len(badge)
            disp_text = label[:avail_w].ljust(avail_w) + badge

            if is_highlighted:
                attr = get_color(COLOR_SELECTED) | curses.A_BOLD
            elif is_active:
                attr = get_color(COLOR_HEADER) | curses.A_BOLD
            else:
                attr = get_color(COLOR_NORMAL)

            safe_addstr(stdscr, item_y, 1, disp_text[: sidebar_w - 2], attr)

        # -------------------------------------------------------------
        # 2. Right Pane: Chatverlauf
        # -------------------------------------------------------------
        history_title = f"Chatverlauf: {active_target.display_tag}"
        draw_box(stdscr, 1, chat_x, main_h, chat_w, history_title)

        history = chat_store.get_history(active_target.id)
        chat_inner_h = main_h - 2
        chat_inner_w = chat_w - 4

        if not history:
            safe_addstr(
                stdscr,
                3,
                chat_x + 3,
                "Noch keine Nachrichten in diesem Chat. Schreibe die erste Nachricht!",
                get_color(COLOR_DIM),
            )
        else:
            # Calculate display lines with wrapping
            formatted_lines = []
            for msg in history:
                time_tag = f"[{msg.timestamp}]"
                status_tag = f" {msg.status}" if msg.status else ""
                
                if msg.is_outgoing:
                    header = f"{time_tag} <Ich>{status_tag}: "
                    color = COLOR_SUCCESS
                else:
                    header = f"{time_tag} <{msg.sender}>{status_tag}: "
                    color = COLOR_WARNING if msg.sender.startswith("Sensor") else COLOR_HEADER

                full_msg = header + msg.text
                formatted_lines.append((full_msg, color))

            # Viewport calculation for scrolling
            total_lines = len(formatted_lines)
            max_scroll = max(0, total_lines - chat_inner_h)
            scroll_offset = max(0, min(scroll_offset, max_scroll))

            start_idx = max(0, total_lines - chat_inner_h - scroll_offset)
            end_idx = min(total_lines, start_idx + chat_inner_h)

            for line_idx, (text_line, line_color) in enumerate(formatted_lines[start_idx:end_idx]):
                draw_y = 2 + line_idx
                safe_addstr(
                    stdscr,
                    draw_y,
                    chat_x + 2,
                    text_line[:chat_inner_w],
                    get_color(line_color),
                )

            # Scroll indicator
            if scroll_offset > 0:
                safe_addstr(
                    stdscr,
                    1,
                    chat_x + chat_w - 18,
                    f" ↑ {scroll_offset} ältere ",
                    get_color(COLOR_SELECTED),
                )

        # -------------------------------------------------------------
        # 3. Bottom Pane: Eingabezeile
        # -------------------------------------------------------------
        input_y = 1 + main_h
        input_border_attr = (
            get_color(COLOR_SELECTED) if focus == FOCUS_INPUT else get_color(COLOR_DIM)
        )
        input_title = f"Nachricht an {active_target.display_tag}"
        draw_box(stdscr, input_y, 0, input_h, max_x, input_title)

        prompt_str = f"✍️  {active_target.display_tag} > "
        safe_addstr(
            stdscr,
            input_y + 1,
            2,
            prompt_str,
            get_color(COLOR_HEADER) | curses.A_BOLD,
        )

        input_field_x = 2 + len(prompt_str)
        available_input_w = max_x - input_field_x - 3
        input_text = "".join(input_buffer)

        # Scrolling input field if text is longer than width
        if cursor_pos >= available_input_w:
            visible_input = input_text[cursor_pos - available_input_w + 1 : cursor_pos + 1]
            render_cursor_x = input_field_x + available_input_w - 1
        else:
            visible_input = input_text[:available_input_w]
            render_cursor_x = input_field_x + cursor_pos

        safe_addstr(
            stdscr,
            input_y + 1,
            input_field_x,
            visible_input,
            get_color(COLOR_NORMAL) | curses.A_BOLD,
        )

        # Place hardware cursor if in input focus
        if focus == FOCUS_INPUT:
            curses.curs_set(1)
            stdscr.move(input_y + 1, render_cursor_x)
        else:
            curses.curs_set(0)

        stdscr.refresh()
        status_notice = ""  # Reset transient notice on redraw
        key = stdscr.getch()

        # -------------------------------------------------------------
        # Key Handling
        # -------------------------------------------------------------
        if key in (27,):  # ESC
            if focus != FOCUS_INPUT:
                focus = FOCUS_INPUT
            else:
                if prompt_confirm(stdscr, "Chat beenden", "Zurück zum Hauptmenü?"):
                    curses.curs_set(0)
                    break
        elif key == ord("\t"):  # TAB switches focus
            focus = (focus + 1) % 3
        elif key in (curses.KEY_UP, ord("k"), ord("K")) and focus == FOCUS_ROOMS:
            if active_target_idx > 0:
                active_target_idx -= 1
                scroll_offset = 0
        elif key in (curses.KEY_DOWN, ord("j"), ord("J")) and focus == FOCUS_ROOMS:
            if active_target_idx < len(chat_store.targets) - 1:
                active_target_idx += 1
                scroll_offset = 0
        elif key in (curses.KEY_UP, curses.KEY_PPAGE) and focus == FOCUS_HISTORY:
            scroll_offset += 1
        elif key in (curses.KEY_DOWN, curses.KEY_NPAGE) and focus == FOCUS_HISTORY:
            if scroll_offset > 0:
                scroll_offset -= 1
        elif (key in (ord("r"), ord("R"))) and focus != FOCUS_INPUT:
            # Sync messages
            status_notice = "Synchronisiere Nachrichten..."
            safe_addstr(stdscr, max_y - 1, 2, status_notice, get_color(COLOR_WARNING))
            stdscr.refresh()
            new_msgs = chat_store.sync_from_backend(backend)
            status_notice = f"Sync abgeschlossen: {new_msgs} neue Nachricht(en)."
            scroll_offset = 0
        elif (key in (ord("n"), ord("N"))) and focus != FOCUS_INPUT:
            # New chat target
            user_input = prompt_input(
                stdscr,
                "Neuen Chat starten",
                "Kanal (#0 bis #7) oder Kontaktname (@Name):",
            )
            if user_input:
                user_input = user_input.strip()
                if user_input.startswith("#"):
                    # Channel
                    ch_str = user_input.lstrip("#").strip()
                    try:
                        ch_num = int(ch_str)
                        name = f"Public (0)" if ch_num == 0 else f"Kanal {ch_num}"
                    except ValueError:
                        ch_num = None
                        name = ch_str
                    target = chat_store.get_or_create_target(name=name, is_channel=True, channel_num=ch_num)
                else:
                    # Contact
                    c_name = user_input.lstrip("@").strip()
                    target = chat_store.get_or_create_target(name=c_name, is_channel=False)

                active_target_idx = chat_store.targets.index(target)
                focus = FOCUS_INPUT
                scroll_offset = 0
        elif (key in (ord("l"), ord("L"))) and focus != FOCUS_INPUT:
            # Clear history for current room
            if prompt_confirm(stdscr, "Verlauf leeren", f"Verlauf für {active_target.display_tag} wirklich leeren?"):
                chat_store.history[active_target.id] = []
                chat_store.save()
                scroll_offset = 0
        elif focus == FOCUS_INPUT:
            # Input bar active
            if key in (10, 13, curses.KEY_ENTER):
                msg_text = "".join(input_buffer).strip()
                if msg_text:
                    status_notice = f"Sende Nachricht an {active_target.display_tag}..."
                    safe_addstr(stdscr, max_y - 1, 2, status_notice, get_color(COLOR_WARNING))
                    stdscr.refresh()

                    ok, res = chat_store.send_message(backend, active_target, msg_text)
                    input_buffer.clear()
                    cursor_pos = 0
                    scroll_offset = 0

                    if ok:
                        status_notice = f"✓ Nachricht gesendet an {active_target.display_tag}"
                    else:
                        status_notice = f"✗ Senden fehlgeschlagen: {res}"
                        show_message(stdscr, "Sendefehler", res, is_error=True)
            elif key in (curses.KEY_BACKSPACE, 127, 8):
                if cursor_pos > 0:
                    input_buffer.pop(cursor_pos - 1)
                    cursor_pos -= 1
            elif key == curses.KEY_DC:  # Delete key
                if cursor_pos < len(input_buffer):
                    input_buffer.pop(cursor_pos)
            elif key == curses.KEY_LEFT:
                if cursor_pos > 0:
                    cursor_pos -= 1
            elif key == curses.KEY_RIGHT:
                if cursor_pos < len(input_buffer):
                    cursor_pos += 1
            elif key == curses.KEY_HOME:
                cursor_pos = 0
            elif key == curses.KEY_END:
                cursor_pos = len(input_buffer)
            elif key in (curses.KEY_UP, curses.KEY_PPAGE):
                # When pressing up in input, allow scrolling history
                focus = FOCUS_HISTORY
                scroll_offset += 1
            elif 32 <= key <= 126 or key >= 160:  # Printable characters
                input_buffer.insert(cursor_pos, chr(key))
                cursor_pos += 1
