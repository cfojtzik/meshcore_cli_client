"""Store heard adverts/discovered/pending nodes and saved contacts."""

import json
import re
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..config import CONFIG_DIR
from .executor import MeshCoreBackend

HEARD_NODES_FILE = CONFIG_DIR / "heard_nodes.json"

TYPE_NAMES = {1: "Companion", 2: "Repeater", 3: "Room", 4: "Sensor"}
TYPE_ALIASES = {
    "1": 1,
    "cli": 1,
    "client": 1,
    "comp": 1,
    "companion": 1,
    "2": 2,
    "rep": 2,
    "repeater": 2,
    "3": 3,
    "room": 3,
    "room server": 3,
    "4": 4,
    "sens": 4,
    "sensor": 4,
}
ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b[@-_]")
CURSOR_RE = re.compile(r"\x1b\[(\d+)G")
CONTACT_SUMMARY_RE = re.compile(
    r"^>\s*\d+\s+from\s+\d+\s+contacts\b", re.IGNORECASE
)


def _strip_ansi(value: str) -> str:
    return ANSI_RE.sub("", value)


def _first_value(data: Dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in data and data[name] is not None:
            return data[name]
    return None


def _as_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _node_type(data: Dict[str, Any]) -> Tuple[int, str]:
    """Return canonical MeshCore contact type IDs and display names."""
    unknown_id: Optional[int] = None
    unknown_name = ""
    for field in ("type_id", "type", "node_type", "type_name"):
        value = data.get(field)
        if value is None or value == "":
            continue
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            type_id = int(value)
            if type_id in TYPE_NAMES:
                return type_id, TYPE_NAMES[type_id]
            if type_id == 0:
                return 0, "Unknown"
            unknown_id = type_id
            continue

        text = str(value).strip()
        type_id = TYPE_ALIASES.get(text.casefold())
        if type_id is not None:
            return type_id, TYPE_NAMES[type_id]
        numeric_id = _as_int(text)
        if numeric_id is not None:
            if numeric_id in TYPE_NAMES:
                return numeric_id, TYPE_NAMES[numeric_id]
            if numeric_id == 0:
                return 0, "Unknown"
            unknown_id = numeric_id
        elif text:
            unknown_name = text

    if unknown_id is not None:
        return unknown_id, unknown_name or f"Type {unknown_id}"
    if unknown_name:
        return 1, unknown_name
    return 1, TYPE_NAMES[1]


def _signal_text(value: Any) -> str:
    if value is None:
        return "n/a"
    text = str(value).strip()
    if not text:
        return "n/a"
    match = re.fullmatch(
        r"([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*(?:dBm|dB)?",
        text,
        re.IGNORECASE,
    )
    return match.group(1) if match else text


def _format_timestamp(value: Any) -> str:
    """Keep textual timestamps and render Unix timestamps without losing them."""
    if value is None or value == "":
        return "n/a"
    if isinstance(value, bool):
        return str(value)

    timestamp: Optional[float] = None
    if isinstance(value, (int, float)):
        timestamp = float(value)
    elif re.fullmatch(r"[+-]?\d+(?:\.\d+)?", str(value).strip()):
        try:
            timestamp = float(str(value).strip())
        except ValueError:
            pass

    if timestamp is None:
        return str(value).strip() or "n/a"
    if timestamp <= 0:
        return "n/a"
    try:
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
    except (OverflowError, OSError, ValueError):
        return str(value).strip()


def _epoch(value: Any) -> float:
    """Return a positive Unix timestamp for sorting, otherwise 0."""
    if value is None or isinstance(value, bool):
        return 0.0
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return 0.0
    return timestamp if timestamp > 0 else 0.0


def _format_out_path(path: Any, path_len: int, hash_mode: Any) -> str:
    text = str(path or "").strip()
    if not text:
        return "n/a"
    hash_len = (_as_int(hash_mode, 0) or 0) + 1
    width = max(1, hash_len) * 2
    hops = [text[index * width : (index + 1) * width] for index in range(path_len)]
    return ",".join(hop for hop in hops if hop) or "n/a"


def _path_and_hops(data: Dict[str, Any]) -> Tuple[str, int]:
    explicit_path = _first_value(data, "path")
    path = str(explicit_path).strip() if explicit_path is not None else ""
    hops = _as_int(data.get("hops"))
    path_len = _as_int(_first_value(data, "out_path_len", "path_len"))
    out_path = data.get("out_path", "")

    if path_len in (-1, 255):
        return path or "Flood", 0 if hops is None else hops
    if path_len == 0:
        return path or "0 hop", 0 if hops is None else hops
    if path_len is not None and path_len > 0:
        formatted = _format_out_path(out_path, path_len, data.get("out_path_hash_mode"))
        return path or formatted, path_len if hops is None else hops

    if not path:
        path = str(out_path).strip() if out_path else "Direct"
    if hops is None:
        lowered = path.casefold()
        if lowered == "flood" or lowered.startswith("0 hop"):
            hops = 0
        elif "," in path:
            hops = len(path.split(","))
        else:
            hops = 1
    return path, hops


def _text_signal(line: str, label: str) -> str:
    match = re.search(
        rf"\b{label}:\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)|n/a)(?:\s*(?:dBm|dB))?",
        line,
        re.IGNORECASE,
    )
    return _signal_text(match.group(1)) if match else "n/a"


def _text_path(line: str) -> Optional[str]:
    match = re.search(
        r"\bPath:\s*(.*?)(?=\s+(?:SNR|RSSI|Hops):|\s*$)",
        line,
        re.IGNORECASE,
    )
    return match.group(1).strip() if match else None


def _text_hops(line: str) -> Optional[int]:
    match = re.search(r"\bHops:\s*(-?\d+)", line, re.IGNORECASE)
    return int(match.group(1)) if match else None


def _path_text_hops(path: str) -> int:
    lowered = path.casefold()
    if lowered == "flood" or lowered.startswith("0 hop"):
        return 0
    if "," in path:
        return len(path.split(","))
    return 1


def _node_from_record(record: Dict[str, Any], is_saved: bool) -> Optional["NodeItem"]:
    key_value = _first_value(record, "public_key", "key", "pubkey", "publicKey")
    key = str(key_value).strip() if key_value is not None else ""
    name_value = _first_value(record, "adv_name", "name", "node_name")
    name = str(name_value).strip() if name_value is not None else ""
    if not name and key:
        name = key[:12]
    if not name:
        return None

    type_id, type_name = _node_type(record)
    path, hops = _path_and_hops(record)
    timestamp = _first_value(
        record, "last_advert", "last_seen", "last_heard", "timestamp", "lastmod"
    )
    return NodeItem(
        name=name,
        key=key,
        type_name=type_name,
        type_id=type_id,
        snr=_signal_text(_first_value(record, "snr", "SNR", "SNR_in")),
        rssi=_signal_text(_first_value(record, "rssi", "RSSI")),
        hops=hops,
        path=path,
        last_seen=_format_timestamp(timestamp),
        is_saved=is_saved,
        heard_at=_epoch(timestamp),
    )


def _decode_json_output(output: Any) -> Any:
    if isinstance(output, (dict, list)):
        return output
    if not isinstance(output, str):
        return None
    text = _strip_ansi(output).strip()
    if not text:
        return None
    try:
        value = json.loads(text)
        return value if isinstance(value, (dict, list)) else None
    except json.JSONDecodeError:
        pass

    # Some CLI versions print connection/status lines before the JSON payload.
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char not in "[{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, (dict, list)):
            return value
    return None


def _contact_records(value: Any) -> Optional[List[Dict[str, Any]]]:
    """Normalize both meshcore-cli's keyed dict and its filtered list output."""
    if isinstance(value, list):
        return [dict(item) for item in value if isinstance(item, dict)]
    if not isinstance(value, dict):
        return None

    contact_fields = {
        "adv_name",
        "name",
        "public_key",
        "pubkey",
        "type",
        "type_id",
        "node_type",
    }
    if contact_fields.intersection(value):
        return [dict(value)]

    for envelope in ("contacts", "pending_contacts", "pending", "nodes", "result"):
        if envelope in value and isinstance(value[envelope], (dict, list)):
            return _contact_records(value[envelope])

    records: List[Dict[str, Any]] = []
    for outer_key, item in value.items():
        if not isinstance(item, dict):
            continue
        record = dict(item)
        if not _first_value(record, "public_key", "key", "pubkey", "publicKey"):
            record["public_key"] = str(outer_key)
        records.append(record)
    return records


def _records_from_output(output: Any) -> Optional[List[Dict[str, Any]]]:
    value = _decode_json_output(output)
    if value is None:
        return None
    return _contact_records(value)


def _ignored_text_line(line: str) -> bool:
    lowered = line.casefold()
    return (
        not line
        or bool(CONTACT_SUMMARY_RE.match(line))
        or lowered.startswith("contacts list")
        or lowered.startswith("heard / pending nodes")
        or "pending list is empty" in lowered
        or "keine neuen gehörten nodes" in lowered
    )


def _parse_fixed_contact(line: str) -> Optional["NodeItem"]:
    """Parse meshcore-cli 1.6.9's ANSI cursor/fixed-column contact rows."""
    cursor = CURSOR_RE.search(line)
    name = ""
    fields = ""
    tail = ""
    type_token = ""
    key = ""

    type_pattern = r"NONE|CLI|REP|ROOM|SENS|Companion|Repeater|Sensor|t:\d+"
    key_pattern = r"[0-9a-fA-F]{4,64}"
    if cursor:
        name = _strip_ansi(line[: cursor.start()]).strip().lstrip("• ").strip()
        fields = _strip_ansi(line[cursor.end() :]).strip()
        match = re.match(
            rf"^(?P<type>{type_pattern})\s+(?P<key>{key_pattern})(?:\s+(?P<tail>.*))?$",
            fields,
            re.IGNORECASE,
        )
        if match:
            type_token = match.group("type")
            key = match.group("key")
            tail = match.group("tail") or ""
    else:
        clean = _strip_ansi(line).strip()
        match = re.match(
            rf"^(?P<name>.*?)\s{{2,}}(?P<type>{type_pattern})\s+"
            rf"(?P<key>{key_pattern})(?:\s+(?P<tail>.*))?$",
            clean,
            re.IGNORECASE,
        )
        if match:
            name = match.group("name").strip().lstrip("• ").strip()
            type_token = match.group("type")
            key = match.group("key")
            tail = match.group("tail") or ""

    if not name or not type_token or not key:
        return None

    age = ""
    path = ""
    tail_parts = tail.split(None, 1)
    if len(tail_parts) == 2:
        age, path = tail_parts[0], tail_parts[1].strip()
    elif tail_parts:
        if re.fullmatch(r"\+?\d+(?:s|m|h|d|y)|0|n/a", tail_parts[0], re.IGNORECASE):
            age = tail_parts[0]
        else:
            path = tail_parts[0]

    type_id, type_name = _node_type({"type": type_token})
    path = path or "Direct"
    return NodeItem(
        name=name,
        key=key,
        type_name=type_name,
        type_id=type_id,
        hops=_path_text_hops(path),
        path=path,
        last_seen=age or "n/a",
        is_saved=True,
    )


def _parse_saved_text_line(raw_line: str) -> Optional["NodeItem"]:
    line = _strip_ansi(raw_line).strip()
    line = re.sub(r"^[•]\s*", "", line)
    if _ignored_text_line(line):
        return None

    fixed = _parse_fixed_contact(raw_line)
    if fixed:
        return fixed

    bracket = re.search(r"\[([^\]]+)\]", line)
    if not bracket:
        return None
    name = line[: bracket.start()].strip()
    if not name:
        return None

    data: Dict[str, Any] = {
        "name": name,
        "type_name": bracket.group(1).strip(),
        "snr": _text_signal(line, "SNR"),
        "rssi": _text_signal(line, "RSSI"),
    }
    path = _text_path(line)
    hops = _text_hops(line)
    if path is not None:
        data["path"] = path
    if hops is not None:
        data["hops"] = hops
    return _node_from_record(data, is_saved=True)


def _parse_heard_text_line(raw_line: str) -> Optional["NodeItem"]:
    line = _strip_ansi(raw_line).strip()
    line = re.sub(r"^(?:📡|•)\s*", "", line)
    if _ignored_text_line(line):
        return None

    key_match = re.search(r"\[Key:\s*([^\]]*)\]", line, re.IGNORECASE)
    if key_match:
        name = line[: key_match.start()].strip()
        key = re.sub(r"\.{3}$", "", key_match.group(1).strip())
        type_match = re.search(r"\bType:\s*([A-Za-z]+)", line, re.IGNORECASE)
        heard_match = re.search(r"\(([^()]*)\)\s*$", line)
        data: Dict[str, Any] = {
            "name": name,
            "key": key,
            "type_name": type_match.group(1) if type_match else "Companion",
            "snr": _text_signal(line, "SNR"),
            "rssi": _text_signal(line, "RSSI"),
            "last_heard": heard_match.group(1).strip() if heard_match else "n/a",
        }
        path = _text_path(line)
        hops = _text_hops(line)
        if path is not None:
            data["path"] = path
        if hops is not None:
            data["hops"] = hops
        return _node_from_record(data, is_saved=False)

    # Native non-JSON pending_contacts output is "adv_name: public_key".
    match = re.match(r"^(?P<name>.+?):\s*(?P<key>[0-9a-fA-F]{8,64})\s*$", line)
    if not match:
        return None
    return _node_from_record(
        {"adv_name": match.group("name"), "public_key": match.group("key")},
        is_saved=False,
    )


def _clean_key(key: Any) -> str:
    return re.sub(r"\.{3}$", "", str(key or "").strip()).casefold()


def _keys_match(first: Any, second: Any) -> bool:
    left, right = _clean_key(first), _clean_key(second)
    if not left or not right:
        return False
    if left == right:
        return True
    return min(len(left), len(right)) >= 8 and (
        left.startswith(right) or right.startswith(left)
    )


def _same_node(first: "NodeItem", second: "NodeItem") -> bool:
    if first.key and second.key and _keys_match(first.key, second.key):
        return True
    return first.name.strip().casefold() == second.name.strip().casefold()


@dataclass
class NodeItem:
    name: str
    key: str = ""
    type_name: str = "Companion"
    type_id: int = 1  # 1=Companion/CLI, 2=Repeater, 3=Room, 4=Sensor
    snr: str = "n/a"
    rssi: str = "n/a"
    hops: int = 1
    path: str = "Direct"
    last_seen: str = "gerade eben"
    is_saved: bool = False
    heard_at: float = 0.0  # Unix time of the last advert, 0 when unknown

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NodeItem":
        type_id, type_name = _node_type(data)
        return cls(
            name=str(data.get("name", "Unknown")),
            key=str(data.get("key", "")),
            type_name=type_name,
            type_id=type_id,
            snr=str(data.get("snr", "n/a")),
            rssi=str(data.get("rssi", "n/a")),
            hops=_as_int(data.get("hops"), 1) or 0,
            path=str(data.get("path", "Direct")),
            last_seen=str(data.get("last_seen", "n/a")),
            is_saved=bool(data.get("is_saved", False)),
            heard_at=_epoch(data.get("heard_at")),
        )


class ContactStore:
    def __init__(self, storage_path: Optional[Path] = HEARD_NODES_FILE) -> None:
        self.storage_path = storage_path
        self.cached_heard: List[NodeItem] = []
        self.cached_contacts: List[NodeItem] = []
        self.dismissed_heard: set[str] = set()
        self.load_heard_cache()

    def load_heard_cache(self) -> None:
        """Load current dict storage and legacy list-only heard node files."""
        if not self.storage_path or not self.storage_path.exists():
            return
        try:
            with open(self.storage_path, "r", encoding="utf-8") as file:
                data = json.load(file)
            if isinstance(data, list):
                nodes = data
                dismissed: List[str] = []
            elif isinstance(data, dict):
                nodes = data.get("nodes", [])
                dismissed = data.get("dismissed", [])
            else:
                return
            if not isinstance(nodes, list):
                nodes = []
            if not isinstance(dismissed, list):
                dismissed = []
            self.dismissed_heard = {
                str(item) for item in dismissed if isinstance(item, str) and item
            }
            self.cached_heard = [
                NodeItem.from_dict(item) for item in nodes if isinstance(item, dict)
            ]
            self.cached_heard = [
                node for node in self.cached_heard if not self._is_dismissed(node)
            ]
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            # A broken cache must not prevent access to the live contact list.
            return

    def save_heard_cache(self) -> None:
        """Save heard nodes and their persistent dismissal tombstones."""
        if not self.storage_path:
            return
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "nodes": [node.to_dict() for node in self.cached_heard],
                "dismissed": sorted(self.dismissed_heard),
            }
            with open(self.storage_path, "w", encoding="utf-8") as file:
                json.dump(payload, file, indent=2)
        except OSError:
            # Persistence errors are non-fatal for the in-memory UI.
            return

    @staticmethod
    def _dismissal_id(node: NodeItem) -> str:
        if node.key:
            return f"key:{_clean_key(node.key)}"
        return f"name:{node.name.strip().casefold()}"

    def _is_dismissed(self, node: NodeItem) -> bool:
        name_id = f"name:{node.name.strip().casefold()}"
        for dismissal in self.dismissed_heard:
            if dismissal == name_id:
                return True
            if dismissal.startswith("key:") and node.key:
                if _keys_match(dismissal[4:], node.key):
                    return True
        return False

    def dismiss_heard_node(self, node: NodeItem) -> None:
        """Dismiss one heard node locally and keep it dismissed after refreshes."""
        self.dismissed_heard.add(self._dismissal_id(node))
        self.cached_heard = [item for item in self.cached_heard if not self._is_dismissed(item)]
        self.save_heard_cache()

    def fetch_saved_contacts(self, backend: MeshCoreBackend) -> List[NodeItem]:
        """Fetch contacts, preferring meshcore-cli JSON with text fallbacks."""
        ok, res = backend.run_cli(["contacts"], json_mode=True)
        contacts: List[NodeItem] = []

        if ok and res:
            records = _records_from_output(res)
            if records is not None:
                for record in records:
                    node = _node_from_record(record, is_saved=True)
                    if node:
                        contacts.append(node)
            else:
                for raw_line in str(res).splitlines():
                    node = _parse_saved_text_line(raw_line)
                    if node:
                        contacts.append(node)

        self.cached_contacts = contacts
        return contacts

    def fetch_heard_nodes(
        self, backend: MeshCoreBackend, discover: bool = False
    ) -> List[NodeItem]:
        """Fetch discovery results and pending nodes, then merge local history."""
        newly_heard: List[NodeItem] = []

        def append_from_output(res: Any) -> None:
            records = _records_from_output(res)
            if records is not None:
                for record in records:
                    node = _node_from_record(record, is_saved=False)
                    if node:
                        newly_heard.append(node)
            else:
                for raw_line in str(res).splitlines():
                    node = _parse_heard_text_line(raw_line)
                    if node:
                        newly_heard.append(node)

        if discover:
            # Discovery responses are separate from the pending-contact queue.
            # JSON preserves keys, types and signal values of both sources.
            discover_ok, discover_res = backend.run_cli(
                ["node_discover"], json_mode=True, timeout=15
            )
            if discover_ok and discover_res:
                append_from_output(discover_res)

        ok, res = backend.run_cli(["pending_contacts"], json_mode=True)
        if ok and res:
            append_from_output(res)

        # ADVERTISEMENT and NEW_CONTACT are different meshcli events. Adverts
        # also include nodes which the companion auto-added to its saved list.
        try:
            advert_records = getattr(backend, "get_heard_adverts", lambda: [])()
        except Exception:
            advert_records = []
        if not isinstance(advert_records, list):
            advert_records = []
        for advert in advert_records:
            if not isinstance(advert, dict):
                continue
            key = str(
                advert.get("public_key") or advert.get("pubkey") or advert.get("key") or ""
            ).strip()
            if not key:
                continue
            timestamp = _first_value(advert, "last_heard", "last_advert", "timestamp")
            saved_match = next(
                (
                    contact
                    for contact in self.cached_contacts
                    if contact.key and _keys_match(contact.key, key)
                ),
                None,
            )
            if saved_match is not None:
                item = replace(
                    saved_match,
                    last_seen=_format_timestamp(timestamp),
                    is_saved=True,
                    heard_at=_epoch(timestamp),
                )
            else:
                existing = next(
                    (node for node in newly_heard if node.key and _keys_match(node.key, key)),
                    None,
                )
                if existing is not None:
                    if timestamp is not None:
                        existing.last_seen = _format_timestamp(timestamp)
                        existing.heard_at = max(existing.heard_at, _epoch(timestamp))
                    continue
                item = _node_from_record(
                    {"public_key": key, "last_advert": timestamp}, is_saved=False
                )
            if item is not None:
                newly_heard.append(item)

        # The companion records the last advert of every saved contact, also
        # while this client was not running. Live adverts are rare (often hours
        # apart), so these timestamps are the primary source of heard nodes.
        for contact in self.cached_contacts:
            if contact.heard_at <= 0:
                continue
            if any(
                node.is_saved and _same_node(node, contact) for node in newly_heard
            ):
                continue
            newly_heard.append(replace(contact, is_saved=True))

        saved_names = {contact.name.strip().casefold() for contact in self.cached_contacts}
        saved_keys = [contact.key for contact in self.cached_contacts if contact.key]

        def is_saved(node: NodeItem) -> bool:
            return node.name.strip().casefold() in saved_names or any(
                _keys_match(node.key, key) for key in saved_keys
            )

        for item in newly_heard:
            if (not item.is_saved and is_saved(item)) or self._is_dismissed(item):
                continue

            existing_idx = next(
                (
                    index
                    for index, cached in enumerate(self.cached_heard)
                    if _same_node(cached, item)
                ),
                None,
            )
            if existing_idx is not None:
                existing = self.cached_heard[existing_idx]
                if existing.key and (
                    not item.key
                    or (
                        _clean_key(existing.key).startswith(_clean_key(item.key))
                        and len(existing.key) > len(item.key)
                    )
                ):
                    item.key = existing.key
                if item.last_seen == "n/a" and existing.last_seen != "n/a":
                    item.last_seen = existing.last_seen
                if existing.heard_at > item.heard_at:
                    item.heard_at = existing.heard_at
                    item.last_seen = existing.last_seen
                # An advert placeholder (key prefix only) must not replace an
                # already known name and type of the same node.
                placeholder = bool(item.key) and item.name == item.key[:12]
                if placeholder and existing.name != item.name:
                    item.name = existing.name
                    item.type_id = existing.type_id
                    item.type_name = existing.type_name
                self.cached_heard[existing_idx] = item
            else:
                self.cached_heard.append(item)

        retained: List[NodeItem] = []
        for node in self.cached_heard:
            if self._is_dismissed(node):
                continue
            if node.is_saved:
                # Re-evaluate a stored flag: a deleted contact is heard again
                # as an unsaved node. Without a loaded contact list, keep it.
                if self.cached_contacts and not is_saved(node):
                    node.is_saved = False
                retained.append(node)
            elif not is_saved(node):
                retained.append(node)
        # Most recently heard first; nodes without a timestamp keep their order.
        retained.sort(key=lambda node: node.heard_at, reverse=True)
        self.cached_heard = retained
        self.save_heard_cache()
        return self.cached_heard

    def save_heard_node_to_contacts(
        self,
        backend: MeshCoreBackend,
        node: NodeItem,
        custom_name: Optional[str] = None,
        custom_type: Optional[int] = None,
    ) -> Tuple[bool, str]:
        """Save a heard/discovered node with its actual MeshCore type ID."""
        if node.is_saved:
            self.fetch_saved_contacts(backend)
            return True, f"Knoten '{node.name}' ist bereits in der Kontaktliste gespeichert."

        target_name = (custom_name or node.name).strip()
        type_id = custom_type if custom_type is not None else node.type_id

        if node.key and len(node.key) >= 8:
            ok, res = backend.run_cli(["add_contact", node.key, str(type_id), target_name])
        else:
            ok, res = backend.run_cli(["add_pending", node.name])

        if ok:
            self.cached_heard = [
                heard for heard in self.cached_heard if not _same_node(heard, node)
            ]
            self.save_heard_cache()
            self.fetch_saved_contacts(backend)
            return True, f"Knoten '{target_name}' erfolgreich in die Kontaktliste übernommen!"
        return False, f"Fehler beim Speichern: {res}"

    def delete_saved_contact(
        self, backend: MeshCoreBackend, name: str, key: Optional[str] = None
    ) -> Tuple[bool, str]:
        """Delete by name and retry every failed name attempt by key prefix."""
        ok, res = backend.run_cli(["remove_contact", name])

        if not ok and key and len(key.strip()) >= 4:
            ok, res = backend.run_cli(["remove_contact", key.strip()[:12]])

        if ok:
            self.fetch_saved_contacts(backend)
            return True, f"Kontakt '{name}' erfolgreich entfernt."
        return False, f"Fehler beim Entfernen: {res}"

    def flush_heard_nodes(self, backend: MeshCoreBackend) -> Tuple[bool, str]:
        """Clear local heard state only after the backend confirms the flush."""
        ok, res = backend.run_cli(["flush_pending"])
        if not ok:
            return False, f"Fehler beim Leeren der gehörten Knoten: {res}"
        getattr(backend, "clear_heard_adverts", lambda: None)()
        self.cached_heard.clear()
        self.dismissed_heard.clear()
        self.save_heard_cache()
        return True, "Liste der gehörten Knoten geleert."
