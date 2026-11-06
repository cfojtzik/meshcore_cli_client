"""Manager and store for heard nodes (discovered/pending) and saved contacts."""

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..config import CONFIG_DIR
from .executor import MeshCoreBackend

HEARD_NODES_FILE = CONFIG_DIR / "heard_nodes.json"


@dataclass
class NodeItem:
    name: str
    key: str = ""
    type_name: str = "Companion"
    type_id: int = 1  # 1=Companion, 2=Repeater, 4=Sensor, 8=Room
    snr: str = "n/a"
    rssi: str = "n/a"
    hops: int = 1
    path: str = "Direct"
    last_seen: str = "gerade eben"
    is_saved: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NodeItem":
        return cls(
            name=data.get("name", "Unknown"),
            key=data.get("key", ""),
            type_name=data.get("type_name", "Companion"),
            type_id=data.get("type_id", 1),
            snr=data.get("snr", "n/a"),
            rssi=data.get("rssi", "n/a"),
            hops=data.get("hops", 1),
            path=data.get("path", "Direct"),
            last_seen=data.get("last_seen", "n/a"),
            is_saved=data.get("is_saved", False),
        )


class ContactStore:
    def __init__(self, storage_path: Optional[Path] = HEARD_NODES_FILE) -> None:
        self.storage_path = storage_path
        self.cached_heard: List[NodeItem] = []
        self.cached_contacts: List[NodeItem] = []
        self.load_heard_cache()

    def load_heard_cache(self) -> None:
        """Load persistent heard nodes from disk."""
        if not self.storage_path or not self.storage_path.exists():
            return
        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    self.cached_heard = [NodeItem.from_dict(d) for d in data]
        except Exception:
            pass

    def save_heard_cache(self) -> None:
        """Save persistent heard nodes to disk."""
        if not self.storage_path:
            return
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump([n.to_dict() for n in self.cached_heard], f, indent=2)
        except Exception:
            pass

    def fetch_saved_contacts(self, backend: MeshCoreBackend) -> List[NodeItem]:
        """Fetch and parse all saved contacts from node."""
        ok, res = backend.run_cli(["contacts"])
        contacts: List[NodeItem] = []

        if ok and res:
            for line in res.splitlines():
                line = line.strip().lstrip("• ")
                if not line or line.startswith("Contacts List"):
                    continue

                # Format example: BaseStation-1      [Repeater] RSSI: -78 dBm SNR: +6.5 dB Hops: 1 Path: Direct
                try:
                    name = line.split("[")[0].strip()
                    type_part = line.split("[")[1].split("]")[0].strip() if "[" in line else "Companion"
                    snr = "n/a"
                    rssi = "n/a"
                    hops = 1
                    path = "Direct"

                    if "SNR:" in line:
                        snr = line.split("SNR:")[1].split()[0].strip()
                    if "RSSI:" in line:
                        rssi = line.split("RSSI:")[1].split()[0].strip()
                    if "Hops:" in line:
                        try:
                            hops = int(line.split("Hops:")[1].split()[0].strip())
                        except ValueError:
                            pass
                    if "Path:" in line:
                        path = line.split("Path:")[1].split()[0].strip()

                    contacts.append(
                        NodeItem(
                            name=name,
                            key="",
                            type_name=type_part,
                            snr=snr,
                            rssi=rssi,
                            hops=hops,
                            path=path,
                            is_saved=True,
                        )
                    )
                except Exception:
                    continue

        self.cached_contacts = contacts
        return contacts

    def fetch_heard_nodes(self, backend: MeshCoreBackend) -> List[NodeItem]:
        """
        Fetch heard/pending nodes from the node (over the air) and merge
        with local discovery history.
        """
        ok, res = backend.run_cli(["pending_contacts"])
        newly_heard: List[NodeItem] = []

        if ok and res:
            for line in res.splitlines():
                line = line.strip().lstrip("📡• ")
                if not line or "Pending list is empty" in line or line.startswith("Heard / Pending Nodes"):
                    continue

                # Parse formats:
                # 1. adv_name: public_key
                # 2. Delta-Repeater-9 [Key: e5f6a1b2c3d4...] Type: Repeater SNR: +4.0 dB RSSI: -82 dBm
                try:
                    name = ""
                    key = ""
                    type_str = "Companion"
                    snr = "n/a"
                    rssi = "n/a"

                    if "[Key:" in line:
                        name = line.split("[Key:")[0].strip()
                        key_part = line.split("[Key:")[1].split("]")[0].strip()
                        key = key_part
                        if "Type:" in line:
                            type_str = line.split("Type:")[1].split()[0].strip()
                        if "SNR:" in line:
                            snr = line.split("SNR:")[1].split()[0].strip()
                        if "RSSI:" in line:
                            rssi = line.split("RSSI:")[1].split()[0].strip()
                    elif ":" in line:
                        parts = line.split(":", 1)
                        name = parts[0].strip()
                        key = parts[1].strip()

                    if name:
                        newly_heard.append(
                            NodeItem(
                                name=name,
                                key=key,
                                type_name=type_str,
                                snr=snr,
                                rssi=rssi,
                                last_seen="gerade eben",
                                is_saved=False,
                            )
                        )
                except Exception:
                    continue

        # Merge newly heard into cached_heard (avoid duplicates by name/key)
        saved_names = {c.name.lower() for c in self.cached_contacts}
        for item in newly_heard:
            # Don't add if already in saved contacts
            if item.name.lower() in saved_names:
                continue

            existing_idx = None
            for idx, ch in enumerate(self.cached_heard):
                if ch.name.lower() == item.name.lower() or (item.key and ch.key == item.key):
                    existing_idx = idx
                    break

            if existing_idx is not None:
                self.cached_heard[existing_idx] = item
            else:
                self.cached_heard.append(item)

        # Filter out any that are now saved in contacts
        self.cached_heard = [
            h for h in self.cached_heard if h.name.lower() not in saved_names
        ]
        self.save_heard_cache()
        return self.cached_heard

    def save_heard_node_to_contacts(
        self,
        backend: MeshCoreBackend,
        node: NodeItem,
        custom_name: Optional[str] = None,
        custom_type: Optional[int] = None,
    ) -> Tuple[bool, str]:
        """
        Save a heard/discovered node into the node's official contact list.
        Executes add_pending or add_contact.
        """
        target_name = (custom_name or node.name).strip()
        type_id = custom_type if custom_type is not None else node.type_id

        # 1. If key is known, use add_contact <key> <type> <name>
        if node.key and len(node.key) >= 8:
            ok, res = backend.run_cli(["add_contact", node.key, str(type_id), target_name])
        else:
            # 2. Otherwise use add_pending <name>
            ok, res = backend.run_cli(["add_pending", node.name])

        if ok:
            # Remove from heard nodes
            self.cached_heard = [
                h for h in self.cached_heard if h.name.lower() != node.name.lower() and h.key != node.key
            ]
            self.save_heard_cache()
            # Refresh contacts
            self.fetch_saved_contacts(backend)
            return True, f"Knoten '{target_name}' erfolgreich in die Kontaktliste übernommen!"
        return False, f"Fehler beim Speichern: {res}"

    def delete_saved_contact(self, backend: MeshCoreBackend, name: str) -> Tuple[bool, str]:
        """Delete contact from node."""
        ok, res = backend.run_cli(["remove_contact", name])
        if ok:
            self.fetch_saved_contacts(backend)
            return True, f"Kontakt '{name}' erfolgreich entfernt."
        return False, f"Fehler beim Entfernen: {res}"

    def flush_heard_nodes(self, backend: MeshCoreBackend) -> Tuple[bool, str]:
        """Clear heard/pending nodes."""
        ok, res = backend.run_cli(["flush_pending"])
        self.cached_heard.clear()
        self.save_heard_cache()
        return True, "Liste der gehörten Knoten geleert."
