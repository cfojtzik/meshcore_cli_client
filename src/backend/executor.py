"""Backend executor that delegates to meshcore-cli without modifying it."""

import json
import os
import re
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
    _CLI_ERROR_PATTERNS = tuple(re.compile(pattern, re.IGNORECASE | re.MULTILINE) for pattern in (
        r"^\s*error\b",
        r"^\s*unknown\s+(?:destination|contact)\b",
        r"^\s*invalid\s+channel\b",
        r"^\s*no\s+ack\s+received\b",
        r"^\s*login\s+failed\b",
        r"^\s*bad\s+path\s+format\b",
        r"^\s*timeout\b(?!\s*:\s*\d)",
        r"^\s*problem\s+while\s+executing\b",
        r"^\s*contact\b[^\n]*\bdoes\s+not\s+exist\b",
        r"^\s*traceback\b",
        r"^\s*[\w.]*serialexception\s*:",
        r"^\s*could\s+not\s+open\s+port\b",
        r"^\s*(?:\[[^\]\n]+\]\s*)?no\s+such\s+file\s+or\s+directory\b",
    ))

    def __init__(self, config: Config) -> None:
        self.config = config
        self._meshcli_bin = self._find_meshcli()
        # Working copies for interactive simulation state
        self._sim_contacts = [dict(c) for c in MOCK_CONTACTS]
        self._sim_heard = [dict(h) for h in MOCK_HEARD_NODES]
        self._sim_channels = [dict(c) for c in MOCK_CHANNELS]

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

    @staticmethod
    def _json_has_error(value: Any) -> bool:
        """Check structured CLI responses for application-level failures."""
        if isinstance(value, dict):
            for key, item in value.items():
                if key.lower() == "error" and item not in (None, False, "", 0):
                    return True
                if key.lower() == "ack" and item is False:
                    return True
            return any(MeshCoreBackend._json_has_error(item) for item in value.values())
        if isinstance(value, list):
            return any(MeshCoreBackend._json_has_error(item) for item in value)
        return False

    @classmethod
    def _cli_output_has_error(cls, stdout: str, stderr: str) -> bool:
        """Detect meshcore-cli failures even when the process exits with zero."""
        for output in (stdout, stderr):
            if not output:
                continue
            if any(pattern.search(output) for pattern in cls._CLI_ERROR_PATTERNS):
                return True
            try:
                payload = json.loads(output)
            except (json.JSONDecodeError, TypeError):
                continue
            if cls._json_has_error(payload):
                return True
        return False

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
            output = (res.stdout or "").strip()
            err_output = (res.stderr or "").strip()
            combined = f"{output}\n{err_output}".strip()

            if res.returncode != 0:
                return False, combined or f"Befehl beendet mit Code {res.returncode}"
            if self._cli_output_has_error(output, err_output):
                return False, combined or "meshcli meldete einen Anwendungsfehler."
            return True, output if output else "Befehl erfolgreich ausgeführt (keine Ausgabe)."
        except subprocess.TimeoutExpired:
            return False, f"Zeitüberschreitung ({t_out}s) beim Warten auf Companion an {self.config.port}."
        except FileNotFoundError:
            return False, f"meshcli Binärdatei '{self._meshcli_bin}' nicht gefunden. Bitte 'pip install meshcore-cli' ausführen."
        except Exception as e:
            return False, f"Unerwarteter Fehler: {e}"

    def _find_sim_contact(self, target: str) -> Optional[Dict[str, Any]]:
        normalized = target.strip().casefold()
        if not normalized:
            return None
        for contact in self._sim_contacts:
            if contact["name"].casefold() == normalized or contact.get("key", "").casefold() == normalized:
                return contact
        return None

    def _handle_simulation(self, args: List[str]) -> Tuple[bool, str]:
        """Provide mock responses when running in simulation mode."""
        if not args:
            return False, "Simulation: Kein Befehl angegeben."

        main_cmd = args[0].lower()

        if main_cmd in ("-h", "--help", "help"):
            return True, (
                "Simulierte meshcli-Befehle: infos, ver, contacts, pending_contacts, "
                "msg [-a] <kontakt> <text>, public <text>, chan <kanal> <text>, "
                "set_channel <nr> <name> [key], remove_channel <nr|name>, "
                "get_channels, card, export_contact, "
                "req_status, req_neighbours, req_telemetry, trace, cmd."
            )
        elif main_cmd in ("infos", "i"):
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
            target_str = args[1].strip() if len(args) > 1 else ""
            if not target_str:
                return False, "Unknown contact: Kein gehörter Knoten angegeben."
            found = None
            normalized_target = target_str.casefold()
            for idx, h in enumerate(self._sim_heard):
                if h["name"].casefold() == normalized_target or h["key"].casefold().startswith(normalized_target):
                    found = self._sim_heard.pop(idx)
                    break
            if not found:
                return False, f"Contact '{target_str}' does not exist in pending contacts."
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
        elif main_cmd == "add_contact":
            key_arg = args[1] if len(args) > 1 else "000000000000"
            type_num = args[2] if len(args) > 2 else "1"
            name_arg = args[3] if len(args) > 3 else "Neu"
            type_names = {"1": "Companion", "2": "Repeater", "3": "Room", "4": "Sensor"}
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
            if not msg.strip():
                return False, "Problem while executing public: Keine Nachricht angegeben."
            return True, f"[Sent] Public Broadcast sent: '{msg}'"
        elif main_cmd in ("msg", "m"):
            name_index = 2 if len(args) > 1 and args[1].lower() == "-a" else 1
            if len(args) <= name_index:
                return False, "Unknown destination/contact: Kein Kontakt angegeben."
            name = args[name_index]
            contact = self._find_sim_contact(name)
            if contact is None:
                return False, f"Unknown destination/contact: '{name}'."
            msg = " ".join(args[name_index + 1:])
            if not msg.strip():
                return False, f"Problem while executing msg: Keine Nachricht für '{contact['name']}' angegeben."
            return True, f"[ACK] Direct Message to '{contact['name']}' delivered: '{msg}'"
        elif main_cmd in ("chan", "ch"):
            target = args[1].strip() if len(args) > 1 else ""
            channel = None
            try:
                channel_num = int(target)
            except ValueError:
                channel_num = None
            if channel_num is not None:
                if not 0 <= channel_num <= 7:
                    return False, f"Invalid channel: '{target}' (erlaubt: 0-7)."
                channel = next((c for c in self._sim_channels if c["num"] == channel_num), None)
            elif target:
                channel = next((c for c in self._sim_channels if c["name"].casefold() == target.casefold()), None)
            if channel is None:
                return False, f"Invalid channel: '{target or '?'}' ist nicht konfiguriert."
            msg = " ".join(args[2:])
            if not msg.strip():
                return False, f"Problem while executing chan: Keine Nachricht für Kanal '{target}' angegeben."
            return True, f"[Sent] Channel {target} message sent: '{msg}'"
        elif main_cmd == "set_channel":
            if len(args) < 3:
                return False, "Invalid channel: set_channel <nr> <name> [key]."
            try:
                channel_num = int(args[1])
            except ValueError:
                return False, f"Invalid channel: '{args[1]}' (erlaubt: 0-7)."
            if not 0 <= channel_num <= 7:
                return False, f"Invalid channel: '{channel_num}' (erlaubt: 0-7)."
            name = args[2].strip()
            if not name:
                return False, "Invalid channel: Der Kanalname darf nicht leer sein."
            channel = next((c for c in self._sim_channels if c["num"] == channel_num), None)
            key = args[3] if len(args) > 3 else (channel.get("key", "") if channel else "")
            if channel is None:
                channel = {"num": channel_num, "name": name, "key": key}
                self._sim_channels.append(channel)
            else:
                channel.update({"name": name, "key": key})
            self._sim_channels.sort(key=lambda c: c["num"])
            return True, f"Channel {channel_num} configured: Name: {name} | Key: {key or '<Default MeshCore Key>'}"
        elif main_cmd == "remove_channel":
            target = args[1].strip() if len(args) > 1 else ""
            if not target:
                return False, "Invalid channel: remove_channel <nr|name>."
            try:
                channel_num = int(target)
            except ValueError:
                channel_num = None
            if channel_num is not None:
                if not 1 <= channel_num <= 7:
                    return False, f"Invalid channel: '{target}' (erlaubt: 1-7; Public 0 ist nicht löschbar)."
                channel = next((c for c in self._sim_channels if c["num"] == channel_num), None)
            else:
                channel = next((c for c in self._sim_channels if c["name"] == target), None)
                if channel is not None and not 1 <= channel["num"] <= 7:
                    return False, f"Invalid channel: '{target}' (Public 0 ist nicht löschbar)."
            if channel is None:
                return False, f"Invalid channel: '{target}' ist nicht konfiguriert."
            self._sim_channels.remove(channel)
            return True, f"Channel {channel['num']} ('{channel['name']}') erfolgreich gelöscht."
        elif main_cmd == "get_channels":
            out = "Configured Channels:\n"
            for ch in self._sim_channels:
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
        elif main_cmd == "card":
            return True, (
                "Own Node Card (Simulated):\n"
                "Name: MeshNode-Alpha\n"
                "Public Key: 4c7525aabbcc01020304050607080910\n"
                "URI: meshcore://contact/4c7525aabbcc01020304050607080910?name=MeshNode-Alpha"
            )
        elif main_cmd == "export_contact":
            target = args[1] if len(args) > 1 else ""
            contact = self._find_sim_contact(target)
            if contact is None:
                return False, f"Contact '{target}' does not exist."
            uri_name = contact["name"].replace(" ", "%20")
            return True, (
                f"Contact Card for '{contact['name']}':\n"
                f"Public Key: {contact['key']}\n"
                f"URI: meshcore://contact/{contact['key']}?name={uri_name}"
            )
        elif main_cmd == "req_neighbours":
            rep = args[1] if len(args) > 1 else "BaseStation-1"
            return True, (
                f"Neighbours of Repeater '{rep}' (2 entries):\n"
                " • Mobile-Bravo    SNR: -2.0 dB RSSI: -98 dBm Hops: 1\n"
                " • Gateway-North   SNR: -5.5 dB RSSI: -104 dBm Hops: 1"
            )
        elif main_cmd == "req_telemetry":
            target = args[1] if len(args) > 1 else ""
            contact = self._find_sim_contact(target)
            if contact is None:
                return False, f"Contact '{target}' does not exist."
            return True, (
                f"Telemetry Data for '{contact['name']}':\n"
                "Battery Voltage: 3980 mV (81%)\n"
                "Temperature: 22.8 °C\n"
                "RX Packets: 87 | TX Packets: 21\n"
                f"Last RSSI: {contact.get('rssi', 'n/a')} | SNR: {contact.get('snr', 'n/a')}"
            )
        elif main_cmd == "trace":
            path = " ".join(args[1:]).strip()
            if not path:
                return False, "Problem while executing trace: Kein Pfad oder Ziel angegeben."
            return True, (
                f"Traceroute for '{path}':\n"
                " 1. BaseStation-1  RSSI: -78 dBm  RTT: 184 ms\n"
                " 2. Gateway-North  RSSI: -104 dBm RTT: 392 ms\n"
                "Trace complete: 2 hops."
            )
        elif main_cmd == "cmd":
            if len(args) < 3:
                return False, "Problem while executing cmd: Verwendung: cmd <repeater> <befehl>."
            rep = args[1]
            remote_cmd = " ".join(args[2:])
            return True, (
                f"Remote command '{remote_cmd}' on repeater '{rep}' completed successfully:\n"
                "OK | Battery 4.18V | Uptime 14d 6h | Free memory 148 kB"
            )
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
            return False, f"Unknown simulation command: {' '.join(args)}"
