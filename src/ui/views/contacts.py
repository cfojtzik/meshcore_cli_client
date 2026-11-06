"""Interactive Dual-List View for Heard Nodes and Saved Contacts."""

import curses
from typing import List, Optional

from ...backend.contact_store import ContactStore, NodeItem
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
    display_scrollable_text,
    draw_box,
    draw_header,
    draw_status_bar,
    prompt_confirm,
    prompt_input,
    safe_addstr,
    show_message,
)
from .chat_view import run_chat_view

TAB_HEARD = 0
TAB_SAVED = 1


def run_contacts_view(stdscr: curses.window, backend: MeshCoreBackend, config: Config) -> None:
    """Interactive dual-list manager: Heard Nodes & Saved Contacts."""
    store = ContactStore()

    # Initial load
    store.fetch_saved_contacts(backend)
    store.fetch_heard_nodes(backend)

    active_tab = TAB_HEARD
    selected_heard_idx = 0
    selected_saved_idx = 0
    status_notice = ""

    while True:
        max_y, max_x = stdscr.getmaxyx()
        stdscr.clear()

        heard_count = len(store.cached_heard)
        saved_count = len(store.cached_contacts)

        # Header
        mode_text = "SIMULATION" if config.simulation_mode else f"Port: {config.port}"
        tab_title = "Gehörte Nodes" if active_tab == TAB_HEARD else "Gespeicherte Kontakte"
        draw_header(stdscr, f"Knoten-Verwaltung [{tab_title}]", mode_text)

        # Status Bar
        if active_tab == TAB_HEARD:
            status_left = "[Tab/←/→] Tab wechseln | [S/Enter] In Kontakte speichern | [R] Scan/Sync | [F] Leeren | [Esc] Menü"
            status_right = f"Gehört: {heard_count} Knoten"
        else:
            status_left = "[Tab/←/→] Tab wechseln | [C] Chat | [D] Info | [P] Pfad | [T] Telemetrie | [X] Löschen | [Esc] Menü"
            status_right = f"Kontakte: {saved_count} gespeichert"

        if status_notice:
            status_right = status_notice
        draw_status_bar(stdscr, status_left, status_right)

        # -------------------------------------------------------------
        # 1. Tab Selector Bar
        # -------------------------------------------------------------
        tab1_label = f"  1. 📡 Gehörte Nodes ({heard_count})  "
        tab2_label = f"  2. 👥 Gespeicherte Kontakte ({saved_count})  "

        tab1_attr = (
            get_color(COLOR_SELECTED) | curses.A_BOLD if active_tab == TAB_HEARD else get_color(COLOR_DIM)
        )
        tab2_attr = (
            get_color(COLOR_SELECTED) | curses.A_BOLD if active_tab == TAB_SAVED else get_color(COLOR_DIM)
        )

        safe_addstr(stdscr, 1, 2, tab1_label, tab1_attr)
        safe_addstr(stdscr, 1, 4 + len(tab1_label), tab2_label, tab2_attr)

        # -------------------------------------------------------------
        # 2. Main List Box
        # -------------------------------------------------------------
        list_y = 3
        preview_h = 4
        list_h = max(6, max_y - list_y - preview_h - 2)

        if active_tab == TAB_HEARD:
            box_title = "📡 Über Funk gehörte Knoten (Noch nicht in Kontakten gespeichert)"
        else:
            box_title = "👥 Gespeicherte Kontakte im Node (Adressbuch)"

        draw_box(stdscr, list_y, 0, list_h, max_x, box_title)

        # Table Header
        header_y = list_y + 1
        if active_tab == TAB_HEARD:
            col_str = f"  {'KNOTEN-NAME':<20} {'TYP':<12} {'SNR':<10} {'RSSI':<10} {'ZUSETZT GEHÖRT':<16} KEY"
        else:
            col_str = f"  {'KONTAKT-NAME':<20} {'TYP':<12} {'PFAD':<12} {'SNR':<10} {'RSSI':<10} HOPS"

        safe_addstr(stdscr, header_y, 2, col_str[: max_x - 4], get_color(COLOR_HEADER) | curses.A_BOLD)
        safe_addstr(stdscr, header_y + 1, 2, "─" * (max_x - 4), get_color(COLOR_DIM))

        # Render rows
        row_start_y = header_y + 2
        visible_rows = list_h - 4

        current_list = store.cached_heard if active_tab == TAB_HEARD else store.cached_contacts
        current_idx = selected_heard_idx if active_tab == TAB_HEARD else selected_saved_idx

        # Ensure bounds
        if current_list:
            current_idx = max(0, min(current_idx, len(current_list) - 1))
            if active_tab == TAB_HEARD:
                selected_heard_idx = current_idx
            else:
                selected_saved_idx = current_idx

        if not current_list:
            empty_msg = (
                "Keine ungespeicherten Nodes gehört. Drücke [R] zum Scannen / Aktualisieren."
                if active_tab == TAB_HEARD
                else "Noch keine Kontakte gespeichert. Gehe zu 'Gehörte Nodes' und drücke [S] zum Speichern."
            )
            safe_addstr(stdscr, row_start_y + 1, 4, empty_msg, get_color(COLOR_WARNING))
        else:
            # Scroll window
            scroll_start = max(0, current_idx - (visible_rows // 2))
            scroll_end = min(len(current_list), scroll_start + visible_rows)

            for i, node in enumerate(current_list[scroll_start:scroll_end]):
                actual_idx = scroll_start + i
                item_y = row_start_y + i
                is_selected = actual_idx == current_idx

                prefix = "▶ " if is_selected else "  "

                if active_tab == TAB_HEARD:
                    key_preview = f"{node.key[:10]}..." if node.key else "n/a"
                    row_text = f"{prefix}{node.name:<20} {node.type_name:<12} {node.snr:<10} {node.rssi:<10} {node.last_seen:<16} {key_preview}"
                else:
                    row_text = f"{prefix}{node.name:<20} {node.type_name:<12} {node.path:<12} {node.snr:<10} {node.rssi:<10} {node.hops}"

                if is_selected:
                    safe_addstr(stdscr, item_y, 2, row_text.ljust(max_x - 4), get_color(COLOR_SELECTED) | curses.A_BOLD)
                else:
                    safe_addstr(stdscr, item_y, 2, row_text[: max_x - 4], get_color(COLOR_NORMAL))

        # -------------------------------------------------------------
        # 3. Preview / Details Box (Bottom)
        # -------------------------------------------------------------
        prev_y = list_y + list_h
        draw_box(stdscr, prev_y, 0, preview_h, max_x, "Ausgewählter Knoten")

        if current_list and current_idx < len(current_list):
            sel_node = current_list[current_idx]
            if active_tab == TAB_HEARD:
                safe_addstr(
                    stdscr,
                    prev_y + 1,
                    2,
                    f"Name: {sel_node.name} | Typ: {sel_node.type_name} | Key: {sel_node.key or 'n/a'}",
                    get_color(COLOR_HEADER) | curses.A_BOLD,
                )
                safe_addstr(
                    stdscr,
                    prev_y + 2,
                    2,
                    f"Signal: SNR {sel_node.snr}, RSSI {sel_node.rssi} | Status: 📡 Gehört ({sel_node.last_seen}) ➔ [S] zum Speichern",
                    get_color(COLOR_SUCCESS),
                )
            else:
                safe_addstr(
                    stdscr,
                    prev_y + 1,
                    2,
                    f"Name: {sel_node.name} | Typ: {sel_node.type_name} | Pfad: {sel_node.path} ({sel_node.hops} Hops)",
                    get_color(COLOR_HEADER) | curses.A_BOLD,
                )
                safe_addstr(
                    stdscr,
                    prev_y + 2,
                    2,
                    f"Signal: SNR {sel_node.snr}, RSSI {sel_node.rssi} | Aktionen: [C] Chat [D] Info [P] Pfad [X] Löschen",
                    get_color(COLOR_NORMAL),
                )
        else:
            safe_addstr(stdscr, prev_y + 1, 2, "(Kein Knoten ausgewählt)", get_color(COLOR_DIM))

        stdscr.refresh()
        status_notice = ""
        key = stdscr.getch()

        # Navigation
        if key in (27, ord("q"), ord("Q")):
            break
        elif key in (ord("\t"), curses.KEY_RIGHT, curses.KEY_LEFT):
            active_tab = TAB_SAVED if active_tab == TAB_HEARD else TAB_HEARD
        elif key == ord("1"):
            active_tab = TAB_HEARD
        elif key == ord("2"):
            active_tab = TAB_SAVED
        elif key in (curses.KEY_UP, ord("k"), ord("K")):
            if active_tab == TAB_HEARD:
                if selected_heard_idx > 0:
                    selected_heard_idx -= 1
            else:
                if selected_saved_idx > 0:
                    selected_saved_idx -= 1
        elif key in (curses.KEY_DOWN, ord("j"), ord("J")):
            if active_tab == TAB_HEARD:
                if selected_heard_idx < len(store.cached_heard) - 1:
                    selected_heard_idx += 1
            else:
                if selected_saved_idx < len(store.cached_contacts) - 1:
                    selected_saved_idx += 1

        # -------------------------------------------------------------
        # Actions on Heard Nodes (Tab 1)
        # -------------------------------------------------------------
        elif active_tab == TAB_HEARD and key in (ord("s"), ord("S"), 10, 13, curses.KEY_ENTER):
            if store.cached_heard and selected_heard_idx < len(store.cached_heard):
                node = store.cached_heard[selected_heard_idx]

                # Confirm / Edit dialog
                custom_name = prompt_input(
                    stdscr,
                    "In Kontaktliste speichern",
                    f"Name für '{node.name}' übernehmen oder anpassen:",
                    default=node.name,
                )
                if custom_name:
                    type_input = prompt_input(
                        stdscr,
                        "Knoten-Typ wählen",
                        "Typ: [1] Companion / Client  [2] Repeater  [4] Sensor:",
                        default=str(node.type_id or 1),
                    )
                    try:
                        chosen_type = int(type_input or 1)
                    except ValueError:
                        chosen_type = 1

                    safe_addstr(stdscr, max_y - 1, 2, f"Speichere '{custom_name}'...", get_color(COLOR_WARNING))
                    stdscr.refresh()

                    ok, msg = store.save_heard_node_to_contacts(
                        backend,
                        node,
                        custom_name=custom_name,
                        custom_type=chosen_type,
                    )
                    show_message(stdscr, "Kontakt speichern", msg, is_error=not ok)
                    if ok:
                        # Switch to Saved Contacts so user sees the newly saved contact immediately!
                        active_tab = TAB_SAVED
                        selected_saved_idx = len(store.cached_contacts) - 1
            else:
                show_message(stdscr, "Kein Knoten", "Kein gehörter Knoten zum Speichern vorhanden.", is_error=True)

        elif active_tab == TAB_HEARD and key in (ord("r"), ord("R")):
            safe_addstr(stdscr, max_y - 1, 2, "Scanne nach gehörten Nodes...", get_color(COLOR_WARNING))
            stdscr.refresh()
            store.fetch_heard_nodes(backend)
            status_notice = f"Aktualisiert: {len(store.cached_heard)} gehörte Knoten."

        elif active_tab == TAB_HEARD and key in (ord("f"), ord("F")):
            if prompt_confirm(stdscr, "Gehörte Nodes leeren", "Möchtest du die Liste der gehörten Nodes leeren?"):
                store.flush_heard_nodes(backend)
                selected_heard_idx = 0
                status_notice = "Liste der gehörten Nodes geleert."

        elif active_tab == TAB_HEARD and key in (ord("d"), ord("D")):
            if store.cached_heard and selected_heard_idx < len(store.cached_heard):
                node = store.cached_heard[selected_heard_idx]
                info_text = (
                    f"Name:            {node.name}\n"
                    f"Public Key:      {node.key or 'n/a'}\n"
                    f"Knoten-Typ:      {node.type_name} (ID: {node.type_id})\n"
                    f"SNR (Signal):    {node.snr}\n"
                    f"RSSI:            {node.rssi}\n"
                    f"Zuletzt gehört:  {node.last_seen}\n"
                    f"Status:          Über Funk empfangen (noch nicht in Kontakten gespeichert)\n\n"
                    f"Tipp: Drücke [S], um diesen Knoten in deine Kontaktliste zu übernehmen."
                )
                display_scrollable_text(stdscr, f"Details: {node.name}", info_text)

        # -------------------------------------------------------------
        # Actions on Saved Contacts (Tab 2)
        # -------------------------------------------------------------
        elif active_tab == TAB_SAVED and key in (ord("c"), ord("C"), 10, 13, curses.KEY_ENTER):
            # Open Chat Window directly for the selected contact!
            if store.cached_contacts and selected_saved_idx < len(store.cached_contacts):
                target_node = store.cached_contacts[selected_saved_idx]
                run_chat_view(stdscr, backend, config, initial_target=target_node.name)
            else:
                run_chat_view(stdscr, backend, config)
            # Reload contacts after chat in case changes were made
            store.fetch_saved_contacts(backend)

        elif active_tab == TAB_SAVED and key in (ord("r"), ord("R")):
            safe_addstr(stdscr, max_y - 1, 2, "Lade gespeicherte Kontakte...", get_color(COLOR_WARNING))
            stdscr.refresh()
            store.fetch_saved_contacts(backend)
            status_notice = f"Kontakte aktualisiert: {len(store.cached_contacts)}."

        elif active_tab == TAB_SAVED and key in (ord("d"), ord("D")):
            if store.cached_contacts and selected_saved_idx < len(store.cached_contacts):
                node = store.cached_contacts[selected_saved_idx]
                ok, res = backend.run_cli(["contact_info", node.name])
                display_scrollable_text(stdscr, f"Kontaktdetails: {node.name}", res)

        elif active_tab == TAB_SAVED and key in (ord("p"), ord("P")):
            if store.cached_contacts and selected_saved_idx < len(store.cached_contacts):
                node = store.cached_contacts[selected_saved_idx]
                safe_addstr(stdscr, max_y - 1, 2, f"Ermittle Pfad zu '{node.name}'...", get_color(COLOR_WARNING))
                stdscr.refresh()
                ok, res = backend.run_cli(["disc_path", node.name], timeout=15)
                show_message(stdscr, f"Pfad: {node.name}", res, is_error=not ok)

        elif active_tab == TAB_SAVED and key in (ord("t"), ord("T")):
            if store.cached_contacts and selected_saved_idx < len(store.cached_contacts):
                node = store.cached_contacts[selected_saved_idx]
                safe_addstr(stdscr, max_y - 1, 2, f"Fordere Telemetrie von '{node.name}' an...", get_color(COLOR_WARNING))
                stdscr.refresh()
                ok, res = backend.run_cli(["req_telemetry", node.name], timeout=15)
                display_scrollable_text(stdscr, f"Telemetrie: {node.name}", res)

        elif active_tab == TAB_SAVED and key in (ord("e"), ord("E")):
            if store.cached_contacts and selected_saved_idx < len(store.cached_contacts):
                node = store.cached_contacts[selected_saved_idx]
                ok, res = backend.run_cli(["export_contact", node.name])
                show_message(stdscr, f"Export: {node.name}", res, is_error=not ok)

        elif active_tab == TAB_SAVED and key in (ord("x"), ord("X"), curses.KEY_DC):
            if store.cached_contacts and selected_saved_idx < len(store.cached_contacts):
                node = store.cached_contacts[selected_saved_idx]
                if prompt_confirm(stdscr, "Kontakt löschen", f"Kontakt '{node.name}' wirklich entfernen?"):
                    ok, res = store.delete_saved_contact(backend, node.name)
                    show_message(stdscr, "Kontakt löschen", res, is_error=not ok)
                    if selected_saved_idx >= len(store.cached_contacts):
                        selected_saved_idx = max(0, len(store.cached_contacts) - 1)

        elif active_tab == TAB_SAVED and key in (ord("+"), ord("a"), ord("A")):
            # Manually add contact
            key_in = prompt_input(stdscr, "Kontakt manuell anlegen", "Public Key (Hex):")
            if key_in:
                name_in = prompt_input(stdscr, "Kontaktname", "Name des Kontakts:")
                if name_in:
                    type_in = prompt_input(stdscr, "Typ", "Typ: [1] Client [2] Repeater [4] Sensor:", default="1")
                    ok, res = backend.run_cli(["add_contact", key_in, type_in or "1", name_in])
                    show_message(stdscr, "Kontakt anlegen", res, is_error=not ok)
                    store.fetch_saved_contacts(backend)
