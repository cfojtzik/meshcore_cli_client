"""Backend executor that delegates to meshcore-cli without modifying it."""

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import serial.tools.list_ports

from ..config import Config
from .mock_data import (
    MOCK_CHANNELS,
    MOCK_CONTACTS,
    MOCK_HEARD_NODES,
    MOCK_INFO,
    MOCK_MSGS,
    MOCK_TELEMETRY,
    MOCK_VER,
)


class MeshCoreBackend:
    def __init__(self, config: Config) -> None:
        self.config = config
        self._meshcli_bin = self._find_meshcli()
        # Working copy for interactive simulation state
        self._sim_contacts = [dict(c) for c in MOCK_CONTACTS]
        self._sim_heard = [dict(h) for h in MOCK_HEARD_NODES]

    def _find_meshcli(self) -> str:
        """Find the meshcli executable in venv or system PATH."""
        # 1. Check in same python environment (e.g. venv/bin)
        venv_bin = Path(sys.prefix) / "bin" / "meshcli"
        if venv_bin.is_file() and os.access(venv_bin, os.X_OK):
            return str(venv_bin)

        # 2. Check local project .venv
        project_venv = Path(__file__).resolve().parent.parent.parent / ".venv" / "bin" / "meshcli"
        if project_venv.is_file() and os.access(project_venv, os.X_OK):
            return str(project_venv)

        # 3. Check PATH
        which_path = shutil.which("meshcli") or shutil.which("meshcore-cli")
        if which_path:
            return which_path

        # Fallback to meshcli in PATH
        return "meshcli"

    @staticmethod
    def list_serial_ports() -> List[Dict[str, str]]:
        """List available serial/USB ports."""
        ports = []
        try:
            for p in serial.tools.list_ports.comports():
                is_usb = any(x in p.device.lower() for x in ["usb", "acm"])
                ports.append({
                    "device": p.device,
                    "description": p.description or "Serial Device",
                    "hwid": p.hwid or "",
                    "is_usb": is_usb,
                })
        except Exception as e:
            ports.append({"device": "/dev/ttyUSB0", "description": f"Scan error: {e}", "hwid": "", "is_usb": True})

        # Sort USB/ACM ports to the top
        ports.sort(key=lambda x: (not x["is_usb"], x["device"]))
        return ports

    def test_connection(self) -> Tuple[bool, str]:
        """Test if the node responds on the configured port."""
        if self.config.simulation_mode:
            return True, "Simulation Mode: Connected to virtual MeshCore Companion."

        success, out = self.run_cli(["infos"], timeout=5)
        if success:
            return True, "Verbindung erfolgreich! Companion antwortet."
        return False, f"Fehler bei Verbindung mit {self.config.port}:\n{out}"

    def run_cli(self, args: List[str], json_mode: bool = False, timeout: Optional[int] = None) -> Tuple[bool, str]:
        """
        Execute meshcli with connection options and commands.
        Does not alter meshcore-cli in any way.
        """
        if self.config.simulation_mode:
            return self._handle_simulation(args)

        t_out = timeout or self.config.timeout
        cmd = [self._meshcli_bin, "-s", self.config.port, "-b", str(self.config.baudrate)]
        if json_mode:
            cmd.append("-j")
        cmd.extend(args)

        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=t_out,
            )
            output = res.stdout.strip()
            err_output = res.stderr.strip()

            if res.returncode == 0:
                return True, output if output else "Befehl erfolgreich ausgeführt (keine Ausgabe)."
            else:
                combined = f"{output}\n{err_output}".strip()
                return False, combined or f"Befehl beendet mit Code {res.returncode}"
        except subprocess.TimeoutExpired:
            return False, f"Zeitüberschreitung ({t_out}s) beim Warten auf Companion an {self.config.port}."
        except FileNotFoundError:
            return False, f"meshcli Binärdatei '{self._meshcli_bin}' nicht gefunden. Bitte 'pip install meshcore-cli' ausführen."
        except Exception as e:
            return False, f"Unerwarteter Fehler: {e}"

    def _handle_simulation(self, args: List[str]) -> Tuple[bool, str]:
        """Provide mock responses when running in simulation mode."""
        if not args:
            return True, "Simulation: Kein Befehl angegeben."

        main_cmd = args[0].lower()

        if main_cmd in ("infos", "i"):
            return True, MOCK_INFO
        elif main_cmd in ("ver", "v"):
            return True, MOCK_VER
        elif main_cmd in ("self_telemetry", "t"):
            return True, MOCK_TELEMETRY
        elif main_cmd == "clock" and len(args) > 1 and args[1] == "sync":
            return True, "Clock synchronized with host system successfully."
        elif main_cmd == "clock":
            return True, "Current device clock: 2026-11-06 22:00:00 UTC"
        elif main_cmd == "reboot":
            return True, "Reboot command sent. Node is restarting..."
        elif main_cmd in ("contacts", "list", "lc"):
            out = f"Contacts List ({len(self._sim_contacts)} contacts in device):\n"
            for c in self._sim_contacts:
                out += f" • {c['name']:<16} [{c['type']}] RSSI: {c.get('rssi', 'n/a')} SNR: {c.get('snr', 'n/a')} Hops: {c.get('hops', 1)} Path: {c.get('path', 'Direct')}\n"
            return True, out.strip()
        elif main_cmd in ("pending_contacts", "node_discover", "nd"):
            if not self._sim_heard:
                return True, "Keine neuen gehörten Nodes in der Warteschlange (Pending list is empty)."
            out = f"Heard / Pending Nodes ({len(self._sim_heard)} Knoten gehört):\n"
            for h in self._sim_heard:
                out += f" 📡 {h['name']:<16} [Key: {h['key'][:12]}...] Type: {h.get('type', 'Companion')} SNR: {h.get('snr', 'n/a')} RSSI: {h.get('rssi', 'n/a')} ({h.get('last_heard', 'gerade eben')})\n"
            return True, out.strip()
        elif main_cmd == "add_pending":
            target_str = args[1] if len(args) > 1 else ""
            found = None
            for idx, h in enumerate(self._sim_heard):
                if h["name"].lower() == target_str.lower() or h["key"].startswith(target_str):
                    found = self._sim_heard.pop(idx)
                    break
            if found:
                self._sim_contacts.append({
                    "name": found["name"],
                    "key": found["key"],
                    "type": found.get("type", "Companion"),
                    "snr": found.get("snr", "+0.0 dB"),
                    "rssi": found.get("rssi", "-90 dBm"),
                    "hops": found.get("hops", 1),
                    "path": found.get("path", "Direct"),
                    "last_seen": "gerade eben",
                })
                return True, f"Knoten '{found['name']}' erfolgreich in die Kontaktliste übernommen!"
            # If not in heard, still allow adding as new
            self._sim_contacts.append({
                "name": target_str or "NeuerKontakt",
                "key": "ffffffffffff",
                "type": "Companion",
                "snr": "n/a",
                "rssi": "n/a",
                "hops": 1,
                "path": "Direct",
                "last_seen": "gerade eben",
            })
            return True, f"Kontakt '{target_str}' in Kontaktliste gespeichert."
        elif main_cmd == "add_contact":
            key_arg = args[1] if len(args) > 1 else "000000000000"
            type_num = args[2] if len(args) > 2 else "1"
            name_arg = args[3] if len(args) > 3 else "Neu"
            type_names = {"1": "Companion", "2": "Repeater", "4": "Sensor", "8": "Room"}
            t_name = type_names.get(str(type_num), "Companion")

            # Remove from heard if present
            self._sim_heard = [h for h in self._sim_heard if h["name"] != name_arg and h["key"] != key_arg]
            self._sim_contacts.append({
                "name": name_arg,
                "key": key_arg,
                "type": t_name,
                "snr": "+5.0 dB",
                "rssi": "-80 dBm",
                "hops": 1,
                "path": "Direct",
                "last_seen": "gerade eben",
            })
            return True, f"Kontakt '{name_arg}' [{t_name}] erfolgreich gespeichert!"
        elif main_cmd in ("remove_contact", "del_contact"):
            name_arg = args[1].strip() if len(args) > 1 else ""
            before_len = len(self._sim_contacts)
            self._sim_contacts = [
                c for c in self._sim_contacts
                if c["name"].lower().strip() != name_arg.lower()
                and c.get("key", "").lower().strip() != name_arg.lower()
            ]
            if len(self._sim_contacts) < before_len:
                return True, f"Kontakt '{name_arg}' erfolgreich gelöscht."
            return False, f"Kontakt '{name_arg}' nicht gefunden."
        elif main_cmd == "flush_pending":
            self._sim_heard.clear()
            return True, "Liste der gehörten Knoten geleert."
        elif main_cmd in ("contact_info", "ci"):
            name = args[1] if len(args) > 1 else "Unknown"
            return True, f"Contact Information for '{name}':\nKey: a1b2c3d4e5f6\nRole: Repeater\nFlags: tel_l, star\nTimeout: 120s"
        elif main_cmd in ("disc_path", "dp"):
            name = args[1] if len(args) > 1 else "Unknown"
            return True, f"Path discovery for '{name}': Direct -> Repeater1 -> {name} (2 hops, SNR +4.2dB)"
        elif main_cmd in ("reset_path", "rp"):
            name = args[1] if len(args) > 1 else "Unknown"
            return True, f"Path to '{name}' reset to Flood."
        elif main_cmd in ("public", "dch"):
            msg = " ".join(args[1:])
            return True, f"[ACK] Public Broadcast sent: '{msg}'"
        elif main_cmd in ("msg", "m"):
            name = args[1] if len(args) > 1 else "?"
            msg = " ".join(args[2:])
            return True, f"[ACK] Direct Message to '{name}' delivered: '{msg}'"
        elif main_cmd in ("chan", "ch"):
            ch = args[1] if len(args) > 1 else "0"
            msg = " ".join(args[2:])
            return True, f"[ACK] Channel {ch} message sent: '{msg}'"
        elif main_cmd == "get_channels":
            out = "Configured Channels:\n"
            for ch in MOCK_CHANNELS:
                out += f" [CH {ch['num']}] Name: {ch['name']} | Key: {ch['key']}\n"
            return True, out.strip()
        elif main_cmd in ("sync_msgs", "sm"):
            out = "Synchronized Messages (3 received):\n"
            for m in MOCK_MSGS:
                out += f" [{m['time']}] [{m['chan']}] {m['from']}: {m['text']}\n"
            return True, out.strip()
        elif main_cmd in ("login", "l"):
            rep = args[1] if len(args) > 1 else "Repeater"
            return True, f"Successfully logged into repeater '{rep}'."
        elif main_cmd == "logout":
            rep = args[1] if len(args) > 1 else "Repeater"
            return True, f"Logged out of repeater '{rep}'."
        elif main_cmd in ("req_status", "rs"):
            rep = args[1] if len(args) > 1 else "Repeater"
            return True, f"Status of Repeater '{rep}': Battery 4.18V, Solar 5.2V (charging), Temp 18.2C, Uptime 14d 6h."
        elif main_cmd in ("advert", "a", "floodadv"):
            return True, "Advertisement packet transmitted successfully."
        elif main_cmd == "scope":
            scope = args[1] if len(args) > 1 else "0"
            return True, f"Flood scope set to '{scope}'."
        elif main_cmd == "get":
            param = args[1] if len(args) > 1 else "all"
            return True, f"Parameter '{param}': default_value_ok"
        elif main_cmd == "set":
            param = args[1] if len(args) > 1 else "?"
            val = args[2] if len(args) > 2 else "?"
            return True, f"Parameter '{param}' updated to '{val}'."
        else:
            return True, f"Simulated output for command: {' '.join(args)}"
