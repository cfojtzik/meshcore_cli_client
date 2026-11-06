"""Contacts Management View."""

import curses

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
    display_scrollable_text,
    draw_box,
    draw_header,
    draw_status_bar,
    prompt_confirm,
    prompt_input,
    safe_addstr,
    show_message,
)


def run_contacts_view(stdscr: curses.window, backend: MeshCoreBackend, config: Config) -> None:
    """Contacts management view."""
    cached_contacts = "Lade Kontakte..."
    loading = True

    while True:
        max_y, max_x = stdscr.getmaxyx()
        stdscr.clear()

        draw_header(stdscr, "Kontaktverwaltung (Contacts)", f"Port: {config.port}")
        draw_status_bar(
            stdscr,
            "[1] Refresh [2] Details [3] Pfad-Scan [4] Reset Pfad [5] Telemetrie [6] Export [7] Import [Esc] Zurück",
            "Contacts",
        )

        view_h = max_y - 3
        draw_box(stdscr, 1, 0, view_h, max_x, "Gefundene Mesh-Knoten")

        if loading:
            safe_addstr(stdscr, 3, 4, "Lade Kontaktliste über USB... bitte warten...", get_color(COLOR_WARNING))
            stdscr.refresh()
            ok, res = backend.run_cli(["contacts"])
            cached_contacts = res if ok else f"Fehler beim Laden der Kontakte:\n{res}"
            loading = False

        # Display contacts list in box
        lines = cached_contacts.splitlines()
        visible_lines = lines[: view_h - 4]
        for idx, line in enumerate(visible_lines):
            safe_addstr(stdscr, 3 + idx, 3, line[: max_x - 6], get_color(COLOR_NORMAL))

        stdscr.refresh()
        key = stdscr.getch()

        if key in (27, ord("q"), ord("Q")):
            break
        elif key in (ord("1"), ord("r"), ord("R")):
            loading = True
        elif key in (ord("2"), ord("d"), ord("D")):
            name = prompt_input(stdscr, "Kontaktdetails", "Name des Kontakts:")
            if name:
                ok, res = backend.run_cli(["contact_info", name])
                show_message(stdscr, f"Details zu {name}", res, is_error=not ok)
        elif key in (ord("3"), ord("p"), ord("P")):
            name = prompt_input(stdscr, "Pfad ermitteln (Path Discovery)", "Name des Zielknotens:")
            if name:
                safe_addstr(stdscr, max_y - 2, 2, f"Ermittle Pfad zu {name}...", get_color(COLOR_WARNING))
                stdscr.refresh()
                ok, res = backend.run_cli(["disc_path", name], timeout=15)
                show_message(stdscr, f"Pfad zu {name}", res, is_error=not ok)
        elif key == ord("4"):
            name = prompt_input(stdscr, "Pfad zurücksetzen", "Name des Zielknotens:")
            if name:
                ok, res = backend.run_cli(["reset_path", name])
                show_message(stdscr, "Pfad zurückgesetzt", res, is_error=not ok)
        elif key in (ord("5"), ord("t"), ord("T")):
            name = prompt_input(stdscr, "Knoten-Telemetrie anfordern", "Name des Knotens:")
            if name:
                safe_addstr(stdscr, max_y - 2, 2, f"Fordere Telemetrie von {name} an...", get_color(COLOR_WARNING))
                stdscr.refresh()
                ok, res = backend.run_cli(["req_telemetry", name], timeout=15)
                display_scrollable_text(stdscr, f"Telemetrie: {name}", res)
        elif key in (ord("6"), ord("e"), ord("E")):
            name = prompt_input(stdscr, "Kontakt exportieren", "Name des Kontakts:")
            if name:
                ok, res = backend.run_cli(["export_contact", name])
                show_message(stdscr, f"Export: {name}", res, is_error=not ok)
        elif key in (ord("7"), ord("i"), ord("I")):
            uri = prompt_input(stdscr, "Kontakt importieren", "Kontakt-URI eingeben:")
            if uri:
                ok, res = backend.run_cli(["import_contact", uri])
                show_message(stdscr, "Kontakt importieren", res, is_error=not ok)
                loading = True
        elif key == ord("8"):
            name = prompt_input(stdscr, "Kontakt entfernen", "Name des zu löschenden Kontakts:")
            if name and prompt_confirm(stdscr, "Kontakt löschen", f"Kontakt '{name}' wirklich entfernen?"):
                ok, res = backend.run_cli(["remove_contact", name])
                show_message(stdscr, "Kontakt entfernen", res, is_error=not ok)
                loading = True
