"""Interactive dual-list view for heard nodes and saved contacts."""

import curses
import time
from typing import Any, Callable, Optional, Sequence

from ...backend.contact_store import ContactStore
from ...backend.executor import MeshCoreBackend
from ...config import Config
from ..async_task import BackgroundTask, run_with_progress
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
    display_scrollable_text,
    draw_box,
    draw_header,
    draw_status_bar,
    ensure_visible,
    prompt_confirm,
    prompt_input,
    read_key,
    safe_addstr,
    show_message,
)
from .chat_view import run_chat_view

TAB_HEARD = 0
TAB_SAVED = 1

AUTO_REFRESH = "refresh"
AUTO_DISCOVERY = "discovery"


def discovery_interval(refresh_interval: int) -> int:
    """Return the radio-friendly interval for a full discovery scan."""
    return max(30, refresh_interval * 6)


def next_auto_action(
    now: float,
    last_refresh: float,
    last_discovery: float,
    refresh_interval: int,
) -> Optional[str]:
    """Return the due background action, giving full discovery priority."""
    if now >= last_discovery + discovery_interval(refresh_interval):
        return AUTO_DISCOVERY
    if now >= last_refresh + refresh_interval:
        return AUTO_REFRESH
    return None


def stable_selection_index(
    nodes: Sequence[Any], selected_node: Optional[Any], fallback: int
) -> int:
    """Keep the same node selected after refresh and clamp stale indices."""
    if not nodes:
        return 0
    fallback = max(0, min(fallback, len(nodes) - 1))
    if selected_node is None:
        return fallback

    selected_key = str(getattr(selected_node, "key", "") or "").strip().casefold()
    if selected_key:
        for index, node in enumerate(nodes):
            if str(getattr(node, "key", "") or "").strip().casefold() == selected_key:
                return index

    selected_name = str(getattr(selected_node, "name", "") or "").strip().casefold()
    if selected_name:
        for index, node in enumerate(nodes):
            if str(getattr(node, "name", "") or "").strip().casefold() == selected_name:
                return index
    return fallback


def run_contacts_view(stdscr: curses.window, backend: MeshCoreBackend, config: Config) -> None:
    """Interactive heard-node and saved-contact manager."""
    store = ContactStore()
    task = BackgroundTask()

    def run_io(title: str, func: Callable[[], Any]) -> Optional[Any]:
        try:
            result = run_with_progress(stdscr, task, title, func)
        finally:
            # Progress dialogs restore blocking input; this view stays pollable.
            stdscr.timeout(100)
        if not result.success:
            show_message(stdscr, title, str(result.value), is_error=True)
            return None
        return result.value

    def refresh_nodes(discover: bool = False) -> Any:
        # The persistent CLI also keeps device-side contacts current when
        # adverts are auto-added instead of entering the manual pending queue.
        store.fetch_saved_contacts(backend)
        return store.fetch_heard_nodes(backend, discover=discover)

    def initial_load() -> Any:
        return refresh_nodes(discover=True)

    stdscr.timeout(100)
    run_io("Kontakte laden", initial_load)
    last_refresh = last_discovery = time.monotonic()
    active_tab = TAB_HEARD
    selected_heard_idx = 0
    selected_saved_idx = 0
    heard_offset = 0
    saved_offset = 0
    status_notice = ""
    pending_auto: Optional[str] = None
    auto_selected_idx = 0
    auto_selected_node: Optional[Any] = None
    exit_when_done = False

    try:
        while True:
            completed = task.poll()
            if completed is not None and pending_auto is not None:
                action = pending_auto
                pending_auto = None
                if exit_when_done:
                    break

                # Pause a full interval after completion, also after timeouts.
                finished_at = time.monotonic()
                last_refresh = finished_at
                if action == AUTO_DISCOVERY:
                    last_discovery = finished_at

                if selected_heard_idx == auto_selected_idx:
                    selected_heard_idx = stable_selection_index(
                        store.cached_heard, auto_selected_node, selected_heard_idx
                    )
                else:
                    selected_heard_idx = max(
                        0, min(selected_heard_idx, len(store.cached_heard) - 1)
                    )
                auto_selected_node = None
                label = "Auto-Discovery" if action == AUTO_DISCOVERY else "Auto-Refresh"
                if completed.success:
                    status_notice = f"{label}: {len(store.cached_heard)} gehörte Knoten."
                else:
                    # Automatic failures stay in the status line and never open
                    # a recurring modal dialog over navigation or text input.
                    status_notice = f"{label} fehlgeschlagen: {completed.value}"

            refresh_interval = getattr(config, "refresh_interval", 5)
            now = time.monotonic()
            if not exit_when_done and not task.busy:
                action = next_auto_action(
                    now, last_refresh, last_discovery, refresh_interval
                )
                if action is not None:
                    heard_snapshot = list(store.cached_heard)
                    auto_selected_idx = selected_heard_idx
                    auto_selected_node = (
                        heard_snapshot[selected_heard_idx]
                        if 0 <= selected_heard_idx < len(heard_snapshot)
                        else None
                    )
                    if task.start(
                        lambda discover=action == AUTO_DISCOVERY: refresh_nodes(
                            discover=discover
                        )
                    ):
                        pending_auto = action

            max_y, max_x = stdscr.getmaxyx()
            stdscr.clear()
            heard_nodes = list(store.cached_heard)
            saved_nodes = list(store.cached_contacts)
            heard_count = len(heard_nodes)
            saved_count = len(saved_nodes)
            mode_text = "SIMULATION" if config.simulation_mode else f"Port: {config.port}"
            tab_title = "Gehörte Nodes" if active_tab == TAB_HEARD else "Gespeicherte Kontakte"
            draw_header(stdscr, f"Knoten-Verwaltung [{tab_title}]", mode_text)

            if active_tab == TAB_HEARD:
                status_left = "[Tab/←/→] Tab | [S/Enter] Speichern | [L/Entf] Löschen | [R] Scan | [F] Leeren | [Esc] Menü"
                status_right = f"Gehört: {heard_count}"
            else:
                status_left = "[Tab/←/→] Tab | [C/Enter] Chat | [D] Info | [P] Pfad | [L/Entf] Löschen | [Esc] Menü"
                status_right = f"Kontakte: {saved_count}"
            auto_status = f"Auto: {refresh_interval}s"
            if task.busy and pending_auto is not None:
                auto_status += " (läuft)"
            if exit_when_done:
                auto_status += " – beenden nach Abschluss"
            status_details = f"{status_notice} | " if status_notice else ""
            draw_status_bar(
                stdscr,
                status_left,
                f"{status_details}{auto_status} | {status_right}",
            )

            tab1_label = f"  1. 📡 Gehörte Nodes ({heard_count})  "
            tab2_label = f"  2. 👥 Gespeicherte Kontakte ({saved_count})  "
            tab1_attr = get_color(COLOR_SELECTED) | curses.A_REVERSE if active_tab == TAB_HEARD else get_color(COLOR_DIM)
            tab2_attr = get_color(COLOR_SELECTED) | curses.A_REVERSE if active_tab == TAB_SAVED else get_color(COLOR_DIM)
            safe_addstr(stdscr, 1, 2, tab1_label, tab1_attr | curses.A_BOLD)
            safe_addstr(stdscr, 1, 4 + len(tab1_label), tab2_label, tab2_attr | curses.A_BOLD)

            list_y = 3
            preview_h = min(4, max(0, max_y - list_y - 2))
            list_h = max(0, max_y - list_y - preview_h - 2)
            box_title = (
                "📡 Über Funk gehörte Knoten"
                if active_tab == TAB_HEARD
                else "👥 Gespeicherte Kontakte im Node"
            )
            draw_box(stdscr, list_y, 0, list_h, max_x, box_title)
            header_y = list_y + 1
            if active_tab == TAB_HEARD:
                col_str = f"  {'KNOTEN-NAME':<20} {'TYP':<12} {'SNR':<10} {'RSSI':<10} {'ZULETZT GEHÖRT':<16} KEY"
            else:
                col_str = f"  {'KONTAKT-NAME':<20} {'TYP':<12} {'PFAD':<12} {'SNR':<10} {'RSSI':<10} HOPS"
            safe_addstr(stdscr, header_y, 2, col_str, get_color(COLOR_HEADER) | curses.A_BOLD)
            safe_addstr(stdscr, header_y + 1, 2, "─" * max(0, max_x - 4), get_color(COLOR_DIM))

            row_start_y = header_y + 2
            visible_rows = max(0, list_h - 4)
            # Work on snapshots while a worker may replace or trim store lists.
            current_list = heard_nodes if active_tab == TAB_HEARD else saved_nodes
            if not current_list:
                selected_heard_idx = 0 if active_tab == TAB_HEARD else selected_heard_idx
                selected_saved_idx = 0 if active_tab == TAB_SAVED else selected_saved_idx
            current_idx = selected_heard_idx if active_tab == TAB_HEARD else selected_saved_idx
            if current_list:
                current_idx = max(0, min(current_idx, len(current_list) - 1))
                if active_tab == TAB_HEARD:
                    selected_heard_idx = current_idx
                else:
                    selected_saved_idx = current_idx

            if not current_list:
                empty_msg = (
                    "Keine ungespeicherten Nodes gehört. [R] startet die Discovery."
                    if active_tab == TAB_HEARD
                    else "Noch keine Kontakte gespeichert."
                )
                safe_addstr(stdscr, row_start_y + 1, 4, empty_msg, get_color(COLOR_WARNING))
            else:
                if active_tab == TAB_HEARD:
                    heard_offset = ensure_visible(current_idx, heard_offset, visible_rows, len(current_list))
                    scroll_start = heard_offset
                else:
                    saved_offset = ensure_visible(current_idx, saved_offset, visible_rows, len(current_list))
                    scroll_start = saved_offset
                visible_nodes = current_list[scroll_start : scroll_start + visible_rows]
                for i, node in enumerate(visible_nodes):
                    actual_idx = scroll_start + i
                    item_y = row_start_y + i
                    is_selected = actual_idx == current_idx
                    prefix = "▶ " if is_selected else "  "
                    if active_tab == TAB_HEARD:
                        key_preview = f"{node.key[:10]}..." if node.key else "n/a"
                        row_text = f"{prefix}{node.name:<20} {node.type_name:<12} {node.snr:<10} {node.rssi:<10} {node.last_seen:<16} {key_preview}"
                    else:
                        row_text = f"{prefix}{node.name:<20} {node.type_name:<12} {node.path:<12} {node.snr:<10} {node.rssi:<10} {node.hops}"
                    attr = (
                        get_color(COLOR_SELECTED) | curses.A_BOLD | curses.A_REVERSE
                        if is_selected
                        else get_color(COLOR_NORMAL)
                    )
                    safe_addstr(stdscr, item_y, 2, row_text.ljust(max(0, max_x - 4)) if is_selected else row_text, attr)

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
                        f"Signal: SNR {sel_node.snr}, RSSI {sel_node.rssi} | Gehört: {sel_node.last_seen}",
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
                    safe_addstr(stdscr, prev_y + 2, 2, "[C/Enter] Chat [D] Info [P] Pfad [L/Entf] Löschen", get_color(COLOR_NORMAL))
            else:
                safe_addstr(stdscr, prev_y + 1, 2, "(Kein Knoten ausgewählt)", get_color(COLOR_DIM))

            stdscr.refresh()
            key = read_key(stdscr)
            if key is None or key == curses.KEY_RESIZE:
                continue
            if exit_when_done:
                continue
            if key in (27, ord("q"), ord("Q")):
                if task.busy:
                    # Do not detach an auto-refresh which can still mutate the
                    # store after this view has been left.
                    exit_when_done = True
                    status_notice = "Beende nach Abschluss der Backend-Aktion …"
                    continue
                break
            if key in (ord("\t"), curses.KEY_RIGHT, curses.KEY_LEFT):
                active_tab = TAB_SAVED if active_tab == TAB_HEARD else TAB_HEARD
            elif key == ord("1"):
                active_tab = TAB_HEARD
            elif key == ord("2"):
                active_tab = TAB_SAVED
            elif key in (curses.KEY_UP, ord("k"), ord("K")):
                if active_tab == TAB_HEARD:
                    selected_heard_idx = max(0, selected_heard_idx - 1)
                else:
                    selected_saved_idx = max(0, selected_saved_idx - 1)
            elif key in (curses.KEY_DOWN, ord("j"), ord("J")):
                if active_tab == TAB_HEARD:
                    selected_heard_idx = min(max(0, len(current_list) - 1), selected_heard_idx + 1)
                else:
                    selected_saved_idx = min(max(0, len(current_list) - 1), selected_saved_idx + 1)
            elif active_tab == TAB_HEARD and key in (ord("s"), ord("S"), 10, 13, curses.KEY_ENTER):
                if current_list and selected_heard_idx < len(current_list):
                    node = current_list[selected_heard_idx]
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
                            "Typ: [1] Client [2] Repeater [3] Room [4] Sensor:",
                            default=str(node.type_id or 1),
                        )
                        try:
                            chosen_type = int(type_input or 1)
                        except ValueError:
                            chosen_type = 1
                        result = run_io(
                            "Kontakt speichern",
                            lambda node=node, custom_name=custom_name, chosen_type=chosen_type: store.save_heard_node_to_contacts(
                                backend, node, custom_name=custom_name, custom_type=chosen_type
                            ),
                        )
                        if result is not None:
                            ok, msg = result
                            show_message(stdscr, "Kontakt speichern", msg, is_error=not ok)
                            if ok:
                                active_tab = TAB_SAVED
                                selected_saved_idx = max(0, len(store.cached_contacts) - 1)
                else:
                    show_message(stdscr, "Kein Knoten", "Kein gehörter Knoten zum Speichern vorhanden.", is_error=True)
            elif active_tab == TAB_HEARD and key in (ord("r"), ord("R")):
                selected_node = (
                    current_list[selected_heard_idx]
                    if 0 <= selected_heard_idx < len(current_list)
                    else None
                )
                result = run_io("Gehörte Nodes scannen", lambda: refresh_nodes(discover=True))
                if result is not None:
                    last_refresh = last_discovery = time.monotonic()
                    selected_heard_idx = stable_selection_index(
                        store.cached_heard, selected_node, selected_heard_idx
                    )
                    status_notice = f"Aktualisiert: {len(store.cached_heard)} gehörte Knoten."
            elif active_tab == TAB_HEARD and key in (ord("f"), ord("F")):
                if prompt_confirm(stdscr, "Gehörte Nodes leeren", "Möchtest du die Liste der gehörten Nodes leeren?"):
                    result = run_io("Gehörte Nodes leeren", lambda: store.flush_heard_nodes(backend))
                    if result is not None:
                        ok, msg = result
                        show_message(stdscr, "Gehörte Nodes leeren", msg, is_error=not ok)
                        status_notice = msg
                        if ok:
                            selected_heard_idx = 0
                            heard_offset = 0
            elif active_tab == TAB_HEARD and key in (
                ord("l"), ord("L"), ord("x"), ord("X"), curses.KEY_DC, 127, 8, curses.KEY_BACKSPACE
            ):
                if current_list and selected_heard_idx < len(current_list):
                    node = current_list[selected_heard_idx]
                    if prompt_confirm(stdscr, "Gehörten Knoten entfernen", f"Knoten '{node.name}' aus Liste entfernen?"):
                        result = store.dismiss_heard_node(node)
                        if isinstance(result, tuple):
                            ok, msg = result
                        else:
                            ok, msg = True, f"Knoten '{node.name}' aus der Gehört-Liste entfernt."
                        show_message(stdscr, "Knoten entfernen", msg, is_error=not ok)
                        if ok:
                            selected_heard_idx = min(selected_heard_idx, max(0, len(store.cached_heard) - 1))
            elif active_tab == TAB_HEARD and key in (ord("d"), ord("D")):
                if current_list and selected_heard_idx < len(current_list):
                    node = current_list[selected_heard_idx]
                    info_text = (
                        f"Name:            {node.name}\n"
                        f"Public Key:      {node.key or 'n/a'}\n"
                        f"Knoten-Typ:      {node.type_name} (ID: {node.type_id})\n"
                        f"SNR (Signal):    {node.snr}\n"
                        f"RSSI:            {node.rssi}\n"
                        f"Zuletzt gehört:  {node.last_seen}\n\n"
                        "Status: Über Funk empfangen (noch nicht gespeichert)."
                    )
                    display_scrollable_text(stdscr, f"Details: {node.name}", info_text)
            elif active_tab == TAB_SAVED and key in (ord("c"), ord("C"), 10, 13, curses.KEY_ENTER):
                if current_list and selected_saved_idx < len(current_list):
                    target_node = current_list[selected_saved_idx]
                    run_chat_view(stdscr, backend, config, initial_target=target_node.name)
                else:
                    run_chat_view(stdscr, backend, config)
                run_io("Kontakte aktualisieren", lambda: store.fetch_saved_contacts(backend))
            elif active_tab == TAB_SAVED and key in (ord("r"), ord("R")):
                result = run_io("Kontakte laden", lambda: store.fetch_saved_contacts(backend))
                if result is not None:
                    status_notice = f"Kontakte aktualisiert: {len(store.cached_contacts)}."
            elif active_tab == TAB_SAVED and key in (ord("d"), ord("D")):
                if current_list and selected_saved_idx < len(current_list):
                    node = current_list[selected_saved_idx]
                    result = run_io("Kontaktdetails", lambda node=node: backend.run_cli(["contact_info", node.name]))
                    if result is not None:
                        ok, res = result
                        display_scrollable_text(stdscr, f"Kontaktdetails: {node.name}" + ("" if ok else " – Fehler"), res)
            elif active_tab == TAB_SAVED and key in (ord("p"), ord("P")):
                if current_list and selected_saved_idx < len(current_list):
                    node = current_list[selected_saved_idx]
                    result = run_io("Pfad ermitteln", lambda node=node: backend.run_cli(["disc_path", node.name], timeout=15))
                    if result is not None:
                        ok, res = result
                        show_message(stdscr, f"Pfad: {node.name}", res, is_error=not ok)
            elif active_tab == TAB_SAVED and key in (ord("t"), ord("T")):
                if current_list and selected_saved_idx < len(current_list):
                    node = current_list[selected_saved_idx]
                    result = run_io("Telemetrie anfordern", lambda node=node: backend.run_cli(["req_telemetry", node.name], timeout=15))
                    if result is not None:
                        ok, res = result
                        display_scrollable_text(stdscr, f"Telemetrie: {node.name}" + ("" if ok else " – Fehler"), res)
            elif active_tab == TAB_SAVED and key in (ord("e"), ord("E")):
                if current_list and selected_saved_idx < len(current_list):
                    node = current_list[selected_saved_idx]
                    result = run_io("Kontakt exportieren", lambda node=node: backend.run_cli(["export_contact", node.name]))
                    if result is not None:
                        ok, res = result
                        show_message(stdscr, f"Export: {node.name}", res, is_error=not ok)
            elif active_tab == TAB_SAVED and key in (
                ord("l"), ord("L"), ord("x"), ord("X"), curses.KEY_DC, 127, 8, curses.KEY_BACKSPACE
            ):
                if current_list and selected_saved_idx < len(current_list):
                    node = current_list[selected_saved_idx]
                    if prompt_confirm(stdscr, "Kontakt löschen", f"Kontakt '{node.name}' wirklich entfernen?"):
                        result = run_io(
                            "Kontakt löschen",
                            lambda node=node: store.delete_saved_contact(backend, node.name, key=node.key),
                        )
                        if result is not None:
                            ok, res = result
                            show_message(stdscr, "Kontakt löschen", res, is_error=not ok)
                            if ok:
                                selected_saved_idx = min(selected_saved_idx, max(0, len(store.cached_contacts) - 1))
            elif active_tab == TAB_SAVED and key in (ord("+"), ord("a"), ord("A")):
                key_in = prompt_input(stdscr, "Kontakt manuell anlegen", "Public Key (Hex):")
                if key_in:
                    name_in = prompt_input(stdscr, "Kontaktname", "Name des Kontakts:")
                    if name_in:
                        type_in = prompt_input(
                            stdscr,
                            "Typ",
                            "Typ: [1] Client [2] Repeater [3] Room [4] Sensor:",
                            default="1",
                        )

                        def add_contact() -> tuple:
                            result = backend.run_cli(["add_contact", key_in, type_in or "1", name_in])
                            if result[0]:
                                store.fetch_saved_contacts(backend)
                            return result

                        result = run_io("Kontakt anlegen", add_contact)
                        if result is not None:
                            ok, res = result
                            show_message(stdscr, "Kontakt anlegen", res, is_error=not ok)
    finally:
        task.close()
        stdscr.timeout(-1)
