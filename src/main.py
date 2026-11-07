#!/usr/bin/env python3
"""Main entry point for MeshCore Terminal Client."""

import argparse
import sys

from src.ui.app import MeshCoreTUIApp


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Menügesteuerter MeshCore Terminal-Client (Curses TUI)",
    )
    parser.add_argument(
        "-s",
        "--serial",
        dest="port",
        help="Serieller USB-Port (z. B. /dev/ttyUSB0 oder /dev/ttyACM0)",
    )
    parser.add_argument(
        "-b",
        "--baudrate",
        type=int,
        default=None,
        help="Baudrate für die serielle Schnittstelle (Standard: gespeicherte Konfiguration)",
    )
    parser.add_argument(
        "--simulate",
        action="store_true",
        help="Startet den Client im Simulationsmodus (zum Testen ohne physische USB-Hardware)",
    )

    args = parser.parse_args()

    app = MeshCoreTUIApp(auto_select_port=args.port is None)

    if args.port:
        app.config.port = args.port
    if args.baudrate is not None:
        app.config.baudrate = args.baudrate
    if args.simulate:
        app.config.simulation_mode = True

    try:
        app.run()
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
