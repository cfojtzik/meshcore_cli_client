"""Chat history and conversation store for channels and direct messages."""

import json
import re
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..config import CONFIG_DIR
from .executor import MeshCoreBackend

CHAT_STORAGE_FILE = CONFIG_DIR / "chat_history.json"

_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_CURSOR_COLUMN_RE = re.compile(r"\x1b\[[0-?]*[ -/]*G")
_TEXT_MESSAGE_RE = re.compile(
    r"^\[(?P<timestamp>[^\]]+)\]\s*"
    r"(?:\[(?P<channel>[^\]]+)\]\s*)?"
    r"(?P<sender>[^:\r\n]+?):\s*(?P<text>.*)$"
)
_CHANNEL_TAG_NUM_RE = re.compile(r"\(([-+]?\d+)\)\s*$")
# MeshCore channel texts are "<sender name>: <message>" (names max. 32 bytes).
_CHANNEL_SENDER_RE = re.compile(r"^(?P<sender>[^\r\n]{1,32}?): (?P<text>.*)$", re.DOTALL)
_UNKNOWN_SENDERS = {"", "unknown"}


def split_channel_sender(sender: str, text: str) -> Tuple[str, str]:
    """Move the sender name out of a channel text when it is not known yet."""
    if str(sender or "").strip().casefold() not in _UNKNOWN_SENDERS:
        return sender, text
    match = _CHANNEL_SENDER_RE.match(text or "")
    if match is None or not match.group("sender").strip():
        return sender, text
    return match.group("sender").strip(), match.group("text")


@dataclass
class ChatMessage:
    sender: str
    text: str
    timestamp: str
    is_outgoing: bool = False
    status: str = ""  # e.g. "[ACK]", "[Sent]", "[Received]"
    # Stable identity for received backend events; empty for legacy/text records.
    dedup_key: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChatMessage":
        return cls(
            sender=data.get("sender", "Unknown"),
            text=data.get("text", ""),
            timestamp=data.get("timestamp", ""),
            is_outgoing=data.get("is_outgoing", False),
            status=data.get("status", ""),
            dedup_key=data.get("dedup_key", ""),
        )


@dataclass
class ChatTarget:
    id: str  # e.g. "chan_0", "dm_BaseStation-1"
    name: str  # Display name e.g. "Public (0)", "BaseStation-1"
    is_channel: bool  # True for channel, False for direct message
    channel_num: Optional[int] = None  # Channel number 0-7

    @property
    def display_tag(self) -> str:
        prefix = "#" if self.is_channel else "@"
        return f"{prefix}{self.name}"


class ChatStore:
    def __init__(self, storage_path: Optional[Path] = CHAT_STORAGE_FILE) -> None:
        self.storage_path = storage_path
        # A reentrant lock keeps target/history updates and their save atomic.
        self._lock = threading.RLock()
        self._loading = False
        # Map target_id -> List[ChatMessage]
        self.history: Dict[str, List[ChatMessage]] = {}
        # Map target_id -> number of received messages not yet viewed.
        self.unread: Dict[str, int] = {}
        # Transient public-key mapping used to resolve real PRIV payloads.
        self._contact_names_by_key: Dict[str, str] = {}
        # List of available targets
        self.targets: List[ChatTarget] = []
        self._init_default_targets()
        self.load()

    def _init_default_targets(self) -> None:
        """Initialize standard channels and default direct contacts."""
        default_channels = [
            ChatTarget("chan_0", "Public (0)", is_channel=True, channel_num=0),
            ChatTarget("chan_1", "Emergency (1)", is_channel=True, channel_num=1),
            ChatTarget("chan_2", "Local-Team (2)", is_channel=True, channel_num=2),
        ]
        with self._lock:
            self.targets = default_channels

    @staticmethod
    def _channel_number(value: Any) -> Optional[int]:
        """Return a valid channel number, without silently truncating values."""
        if type(value) is int:
            number = value
        elif isinstance(value, str) and re.fullmatch(r"[-+]?\d+", value.strip()):
            number = int(value.strip())
        else:
            return None
        return number if 0 <= number <= 7 else None

    @staticmethod
    def _channel_display_name(name: str, channel_num: int) -> str:
        name = name.strip()
        if re.search(rf"\(\s*{channel_num}\s*\)\s*$", name):
            return name
        return f"{name} ({channel_num})"

    def get_or_create_target(
        self, name: str, is_channel: bool, channel_num: Optional[int] = None
    ) -> ChatTarget:
        """Get an existing chat target or create a new one."""
        clean_name = str(name or "").lstrip("#@").strip()
        target_id = (
            f"chan_{channel_num if channel_num is not None else clean_name}"
            if is_channel
            else f"dm_{clean_name}"
        )

        with self._lock:
            for target in self.targets:
                if target.is_channel != is_channel:
                    continue
                if target.id == target_id or target.name.casefold() == clean_name.casefold():
                    return target

            new_target = ChatTarget(
                id=target_id,
                name=clean_name,
                is_channel=is_channel,
                channel_num=channel_num,
            )
            self.targets.append(new_target)
            if target_id not in self.history:
                self.history[target_id] = []
            # Loading must never rewrite the source file before history is restored.
            if not self._loading:
                self.save()
            return new_target

    def get_history(self, target_id: str) -> List[ChatMessage]:
        """Return message list for a specific chat target."""
        with self._lock:
            return self.history.get(target_id, [])

    def add_message(self, target_id: str, message: ChatMessage) -> None:
        """Add a message to the target's conversation history."""
        with self._lock:
            if target_id not in self.history:
                self.history[target_id] = []

            # Every intentional outgoing send is a distinct event. Received
            # backend events use their stable identity when available; legacy
            # text records retain the old best-effort duplicate detection.
            if not message.is_outgoing:
                for existing in self.history[target_id]:
                    if message.dedup_key:
                        if existing.dedup_key == message.dedup_key:
                            return
                    elif not existing.dedup_key and (
                        existing.timestamp == message.timestamp
                        and existing.sender == message.sender
                        and existing.text == message.text
                        and not existing.is_outgoing
                    ):
                        return

            self.history[target_id].append(message)
            self.save()

    def delete_message(self, target_id: str, index: int) -> bool:
        """Delete one local message, returning whether the index was valid."""
        with self._lock:
            messages = self.history.get(target_id)
            if (
                messages is None
                or type(index) is not int
                or not 0 <= index < len(messages)
            ):
                return False
            messages.pop(index)
            self.save()
            return True

    def clear_history(self, target_id: str) -> None:
        """Clear all local messages for a target without removing the target."""
        with self._lock:
            self.history.setdefault(target_id, []).clear()
            self.unread.pop(target_id, None)
            self.save()

    def delete_conversation(self, target_id: str) -> bool:
        """Remove one local chat-list entry and its complete local history."""
        with self._lock:
            if not any(target.id == target_id for target in self.targets):
                return False
            self.targets = [
                target for target in self.targets if target.id != target_id
            ]
            self.history.pop(target_id, None)
            self.unread.pop(target_id, None)
            self.save()
            return True

    def send_message(
        self, backend: MeshCoreBackend, target: ChatTarget, text: str
    ) -> Tuple[bool, str]:
        """Send a message via meshcore-cli and record it in history."""
        text = text.strip()
        if not text:
            return False, "Leere Nachricht kann nicht gesendet werden."

        target_name = str(target.name or "").strip() if target is not None else ""
        if not target_name:
            return False, "Leeres Ziel: Nachricht wurde nicht gesendet."

        args: Optional[List[str]] = None
        ok = False
        res = ""

        if target.is_channel:
            channel_num = target.channel_num
            if channel_num is None:
                # A named channel is not implicitly the public channel.
                args = ["chan", target_name, text]
            elif type(channel_num) is int and 0 <= channel_num <= 7:
                if channel_num == 0:
                    args = ["public", text]
                else:
                    args = ["chan", str(channel_num), text]
            else:
                res = "Ungültige Kanalnummer (erlaubt: 0 bis 7)."
        else:
            # -a makes meshcli wait for the direct-message acknowledgement.
            args = ["msg", "-a", target_name, text]

        if args is not None:
            ok, res = backend.run_cli(args)

        if not ok:
            status = "[Fehler]"
        elif target.is_channel:
            status = "[Sent]"
        else:
            status = "[ACK]"

        msg = ChatMessage(
            sender="Ich",
            text=text,
            timestamp=datetime.now().strftime("%H:%M:%S"),
            is_outgoing=True,
            status=status,
        )
        self.add_message(target.id, msg)
        return ok, res

    def delete_channel(
        self, backend: MeshCoreBackend, target: ChatTarget
    ) -> Tuple[bool, str]:
        """Remove a non-public channel from the device and its local chat data."""
        if target is None or not target.is_channel:
            return False, "Nur Kanäle können gelöscht werden."

        channel_num = target.channel_num
        if type(channel_num) is int and channel_num == 0:
            return False, "Public (0) kann nicht gelöscht werden."

        if type(channel_num) is int:
            if not 1 <= channel_num <= 7:
                return False, "Ungültige Kanalnummer (erlaubt: 1 bis 7)."
            args = ["remove_channel", str(channel_num)]
        elif channel_num is None:
            target_name = str(target.name or "").strip()
            if not target_name:
                return False, "Leerer Kanalname kann nicht gelöscht werden."
            args = ["remove_channel", target_name]
        else:
            return False, "Ungültige Kanalnummer (erlaubt: 1 bis 7)."

        ok, res = backend.run_cli(args)
        if not ok:
            return False, res

        with self._lock:
            self.targets = [
                existing for existing in self.targets if existing.id != target.id
            ]
            self.history.pop(target.id, None)
            self.unread.pop(target.id, None)
            self.save()
        return True, res

    @staticmethod
    def _timestamp(value: Any) -> str:
        if value is None:
            value = time.time()
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            try:
                return datetime.fromtimestamp(value).strftime("%H:%M:%S")
            except (OverflowError, OSError, ValueError):
                pass
        return str(value)

    def _add_received_message(
        self,
        target: ChatTarget,
        sender: str,
        text: str,
        timestamp: Any,
        dedup_key: str = "",
    ) -> int:
        message = ChatMessage(
            sender=sender,
            text=text,
            timestamp=self._timestamp(timestamp),
            is_outgoing=False,
            status="[RX]",
            dedup_key=dedup_key,
        )
        with self._lock:
            before_len = len(self.get_history(target.id))
            # Count first so add_message persists history and counter together.
            self.unread[target.id] = self.unread.get(target.id, 0) + 1
            self.add_message(target.id, message)
            added = len(self.get_history(target.id)) > before_len
            if not added:  # Duplicate: nothing new to read, nothing was saved.
                self._decrement_unread(target.id)
            return int(added)

    def _decrement_unread(self, target_id: str) -> None:
        remaining = self.unread.get(target_id, 0) - 1
        if remaining > 0:
            self.unread[target_id] = remaining
        else:
            self.unread.pop(target_id, None)

    def unread_count(self, target_id: str) -> int:
        """Received messages in a chat which have not been viewed yet."""
        with self._lock:
            return self.unread.get(target_id, 0)

    def unread_targets(self) -> List[Tuple[ChatTarget, int]]:
        """Chats with unread messages, in chat-list order."""
        with self._lock:
            return [
                (target, self.unread[target.id])
                for target in self.targets
                if self.unread.get(target.id, 0) > 0
            ]

    def mark_read(self, target_id: str) -> bool:
        """Mark a chat as read; returns whether anything was unread."""
        with self._lock:
            if not self.unread.pop(target_id, 0):
                return False
            self.save()
            return True

    def _remember_contact(self, name: str, key: Any) -> None:
        key_text = str(key or "").strip().casefold()
        if name.strip() and key_text:
            self._contact_names_by_key[key_text] = name.strip()

    def _contact_name_for_prefix(self, prefix: str) -> str:
        normalized = prefix.strip().casefold()
        if not normalized:
            return ""
        for key, name in self._contact_names_by_key.items():
            if key.startswith(normalized) or normalized.startswith(key):
                return name
        return ""

    def _sync_json_messages(self, data: List[Any]) -> int:
        new_count = 0
        for item in data:
            if not isinstance(item, dict):
                continue

            message_type = str(item.get("type", "")).upper()
            text_value = item.get("text")
            if text_value is None and message_type == "DATA":
                data_type = item.get("data_type", "?")
                payload = item.get("payload", "")
                text_value = f"[DATA {data_type}] {payload}"
            elif text_value is None:
                text_value = item.get("msg", "")
            text = str(text_value)
            timestamp = item.get("sender_timestamp")
            if timestamp is None:
                timestamp = item.get("time", item.get("timestamp"))

            sender_value = item.get("sender") or item.get("from")
            sender = str(sender_value).strip() if sender_value is not None else ""
            pubkey_prefix = str(item.get("pubkey_prefix") or "").strip()

            if message_type == "CHAN" or (
                "channel_idx" in item and message_type != "PRIV"
            ):
                channel_num = self._channel_number(item.get("channel_idx"))
                if channel_num is None:
                    continue
                target = self.get_or_create_target(
                    name="Public (0)" if channel_num == 0 else f"Kanal {channel_num}",
                    is_channel=True,
                    channel_num=channel_num,
                )
                sender = sender or "Unknown"
            elif message_type == "PRIV" or pubkey_prefix:
                # Real PRIV events carry only a key prefix. Resolve known contacts
                # populated immediately before sync; retain the prefix for unknowns.
                known_name = self._contact_name_for_prefix(pubkey_prefix)
                if known_name and (not sender or sender.casefold() == "unknown"):
                    sender = known_name
                elif pubkey_prefix and (not sender or sender.casefold() == "unknown"):
                    sender = pubkey_prefix
                dm_name = sender or known_name or pubkey_prefix
                if not dm_name:
                    continue
                target = self.get_or_create_target(dm_name, is_channel=False)
            elif item.get("channel") is not None:
                raw_channel = item.get("channel")
                channel_num = self._channel_number(raw_channel)
                if channel_num is not None:
                    target = self.get_or_create_target(
                        name="Public (0)" if channel_num == 0 else f"Kanal {channel_num}",
                        is_channel=True,
                        channel_num=channel_num,
                    )
                else:
                    channel_name = str(raw_channel).strip()
                    if not channel_name:
                        continue
                    target = self.get_or_create_target(
                        channel_name, is_channel=True, channel_num=None
                    )
                sender = sender or "Unknown"
            else:
                sender = sender or "Unknown"
                target = self.get_or_create_target(sender, is_channel=False)

            dedup_key = json.dumps(
                {
                    "type": message_type,
                    "channel_idx": item.get("channel_idx", item.get("channel")),
                    "pubkey_prefix": pubkey_prefix,
                    "sender": sender,
                    "timestamp": timestamp,
                    "text": text,
                    "data_type": item.get("data_type"),
                    "payload": item.get("payload"),
                },
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            )
            # Split only after building the key, so identities of messages
            # stored by older versions stay identical.
            if target.is_channel and message_type != "DATA":
                sender, text = split_channel_sender(sender, text)
            new_count += self._add_received_message(
                target, sender, text, timestamp, dedup_key=dedup_key
            )

        return new_count

    def _sync_text_messages(self, response: str) -> int:
        new_count = 0
        for raw_line in response.splitlines():
            line = _ANSI_RE.sub("", raw_line).strip()
            line = re.sub(r"^•\s*", "", line)
            match = _TEXT_MESSAGE_RE.match(line)
            if not match:
                continue

            sender = match.group("sender").strip()
            if not sender:
                continue
            channel_tag = match.group("channel")
            if channel_tag is not None:
                channel_tag = channel_tag.strip()
                number_match = _CHANNEL_TAG_NUM_RE.search(channel_tag)
                channel_num = (
                    self._channel_number(number_match.group(1)) if number_match else None
                )
                if number_match and channel_num is None:
                    continue
                target = self.get_or_create_target(
                    channel_tag, is_channel=True, channel_num=channel_num
                )
            else:
                # Lines without an explicit channel tag are direct messages.
                target = self.get_or_create_target(sender, is_channel=False)

            new_count += self._add_received_message(
                target,
                sender,
                match.group("text").strip(),
                match.group("timestamp").strip(),
            )

        return new_count

    @staticmethod
    def _complete_json_objects(response: str) -> List[Dict[str, Any]]:
        """Recover complete top-level objects from a damaged JSON array.

        meshcli can emit a trailing comma after a message when a later receive
        fails. Those already consumed messages must not be discarded.
        """
        stripped = response.lstrip()
        if not stripped.startswith("["):
            return []
        decoder = json.JSONDecoder()
        objects: List[Dict[str, Any]] = []
        index = 1
        while index < len(stripped):
            while index < len(stripped) and (stripped[index].isspace() or stripped[index] == ","):
                index += 1
            if index >= len(stripped) or stripped[index] == "]":
                break
            try:
                value, end = decoder.raw_decode(stripped, index)
            except json.JSONDecodeError:
                break
            if isinstance(value, dict):
                objects.append(value)
            index = end
        return objects

    def sync_from_backend(self, backend: MeshCoreBackend) -> int:
        """Read unread messages once, preserving every recoverable response item."""
        ok, res = backend.run_cli(["sync_msgs"], json_mode=True)
        if not res:
            if not ok:
                raise RuntimeError("sync_msgs wurde vom Backend abgelehnt.")
            return 0

        new_count = 0
        warning = ""
        stripped = res.strip()
        if stripped.startswith(("[", "{")):
            try:
                data = json.loads(stripped)
            except (json.JSONDecodeError, TypeError, ValueError):
                recovered = self._complete_json_objects(stripped)
                if recovered:
                    new_count = self._sync_json_messages(recovered)
                    warning = f"Sync-Antwort war beschädigt; {len(recovered)} Nachricht(en) gesichert."
                else:
                    # Timestamped text also starts with '[', so try that parser
                    # against the same response without a second destructive read.
                    new_count = self._sync_text_messages(res)
                    has_text_message = any(
                        _TEXT_MESSAGE_RE.match(
                            re.sub(r"^•\s*", "", _ANSI_RE.sub("", raw_line).strip())
                        )
                        for raw_line in res.splitlines()
                    )
                    if not has_text_message:
                        warning = "Sync-Antwort konnte nicht ausgewertet werden."
            else:
                if isinstance(data, list):
                    new_count = self._sync_json_messages(data)
                elif isinstance(data, dict):
                    new_count = self._sync_json_messages([data])
        else:
            # Simulation and older text-only backends return text despite JSON mode.
            new_count = self._sync_text_messages(res)

        if not ok:
            detail = f" ({warning})" if warning else ""
            raise RuntimeError(f"{res}{detail}")
        if warning:
            raise RuntimeError(warning)
        return new_count

    def _add_backend_channel(self, raw_num: Any, raw_name: Any) -> None:
        channel_num = self._channel_number(raw_num)
        name = str(raw_name or "").strip()
        if channel_num is None or not name:
            return
        display_name = self._channel_display_name(name, channel_num)
        target = self.get_or_create_target(
            name=display_name,
            is_channel=True,
            channel_num=channel_num,
        )
        # The device is authoritative for names of default/persisted channels.
        changed = target.channel_num != channel_num or target.name != display_name
        target.channel_num = channel_num
        target.name = display_name
        if changed:
            self.save()

    def _populate_channels(self, response: str) -> None:
        try:
            data = json.loads(response)
        except (json.JSONDecodeError, TypeError, ValueError):
            data = None

        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    self._add_backend_channel(
                        item.get("channel_idx", item.get("channel")),
                        item.get("channel_name", item.get("name")),
                    )
            return

        for raw_line in response.splitlines():
            line = _ANSI_RE.sub("", raw_line).strip()
            mock_match = re.search(
                r"\[CH\s+(\d+)\]\s*Name:\s*([^|]+)", line, re.IGNORECASE
            )
            if mock_match:
                self._add_backend_channel(mock_match.group(1), mock_match.group(2))
                continue

            # meshcore-cli 1.6.9: "0: Channel name [hex-secret]"
            real_match = re.match(r"^(\d+)\s*:\s*(.*?)\s*\[[^\]]*\]\s*$", line)
            if real_match:
                self._add_backend_channel(real_match.group(1), real_match.group(2))

    def _populate_contacts(self, response: str) -> None:
        try:
            data = json.loads(response)
        except (json.JSONDecodeError, TypeError, ValueError):
            data = None

        if isinstance(data, dict):
            if "adv_name" in data or "name" in data:
                contacts = [data]
            else:
                contacts = []
                for outer_key, value in data.items():
                    if isinstance(value, dict):
                        record = dict(value)
                        record.setdefault("public_key", outer_key)
                        contacts.append(record)
        elif isinstance(data, list):
            contacts = data
        else:
            contacts = None

        if contacts is not None:
            for item in contacts:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("adv_name") or item.get("name") or "").strip()
                if name:
                    self.get_or_create_target(name, is_channel=False)
                    self._remember_contact(
                        name,
                        item.get("public_key") or item.get("key") or item.get("pubkey"),
                    )
            return

        for raw_line in response.splitlines():
            clean_line = _ANSI_RE.sub("", raw_line).strip()
            clean_line = re.sub(r"^[•📡]\s*", "", clean_line)
            lower_line = clean_line.casefold()
            if (
                not clean_line
                or clean_line.startswith(">")
                or lower_line.startswith("contacts list")
                or lower_line.startswith("fetching contacts")
            ):
                continue

            # Real output places the cursor at column 34 after a 30-char name
            # field. Splitting before that code also preserves spaces in names.
            cursor_match = _CURSOR_COLUMN_RE.search(raw_line)
            contact_key = ""
            if cursor_match:
                name = _ANSI_RE.sub("", raw_line[: cursor_match.start()]).strip()
                key_match = re.search(
                    r"\b[0-9a-fA-F]{8,64}\b", raw_line[cursor_match.end() :]
                )
                contact_key = key_match.group(0) if key_match else ""
            elif "[" in clean_line and "]" in clean_line:
                # Simulation format: "Name [Type] RSSI: ..."
                name = clean_line.split("[", 1)[0].strip()
            elif len(clean_line) > 30:
                # Fallback for output with ANSI already removed by a wrapper.
                name = clean_line[:30].strip()
            else:
                continue

            name = re.sub(r"^[•📡]\s*", "", name).strip()
            if name:
                self.get_or_create_target(name, is_channel=False)
                self._remember_contact(name, contact_key)

    def populate_targets_from_backend(self, backend: MeshCoreBackend) -> None:
        """Fetch discovered channels and contacts to build room list."""
        ok_ch, res_ch = backend.run_cli(["get_channels"])
        if ok_ch and res_ch:
            self._populate_channels(res_ch)

        ok_ct, res_ct = backend.run_cli(["contacts"])
        if ok_ct and res_ct:
            self._populate_contacts(res_ct)

    def load(self) -> None:
        """Load stored messages and custom targets from disk."""
        if not self.storage_path or not self.storage_path.exists():
            return
        with self._lock:
            self._loading = True
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    # Restore every target before any history, without saving in between.
                    raw_targets = data.get("targets", [])
                    if isinstance(raw_targets, list):
                        for t_data in raw_targets:
                            if not isinstance(t_data, dict):
                                continue
                            try:
                                self.get_or_create_target(
                                    name=t_data["name"],
                                    is_channel=t_data["is_channel"],
                                    channel_num=t_data.get("channel_num"),
                                )
                            except (KeyError, TypeError, ValueError):
                                continue

                    raw_history = data.get("history", {})
                    if isinstance(raw_history, dict):
                        for t_id, msgs in raw_history.items():
                            if not isinstance(msgs, list):
                                continue
                            self.history[t_id] = [
                                ChatMessage.from_dict(m)
                                for m in msgs
                                if isinstance(m, dict)
                            ]

                    # Older versions stored channel messages as sender
                    # "Unknown" with the name inside the text.
                    channel_ids = {t.id for t in self.targets if t.is_channel}
                    for t_id in channel_ids:
                        for message in self.history.get(t_id, []):
                            if not message.is_outgoing:
                                message.sender, message.text = split_channel_sender(
                                    message.sender, message.text
                                )

                    raw_unread = data.get("unread", {})
                    if isinstance(raw_unread, dict):
                        self.unread = {
                            str(t_id): count
                            for t_id, count in raw_unread.items()
                            if type(count) is int and count > 0
                        }
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                pass
            finally:
                self._loading = False

    def save(self) -> None:
        """Save chat history and targets to disk."""
        if not self.storage_path:
            return
        with self._lock:
            if self._loading:
                return
            try:
                self.storage_path.parent.mkdir(parents=True, exist_ok=True)
                serializable_history = {
                    t_id: [m.to_dict() for m in msgs]
                    for t_id, msgs in self.history.items()
                }
                serializable_targets = [
                    {
                        "id": t.id,
                        "name": t.name,
                        "is_channel": t.is_channel,
                        "channel_num": t.channel_num,
                    }
                    for t in self.targets
                ]
                with open(self.storage_path, "w", encoding="utf-8") as f:
                    json.dump(
                        {
                            "targets": serializable_targets,
                            "history": serializable_history,
                            "unread": dict(self.unread),
                        },
                        f,
                        indent=2,
                    )
            except (OSError, TypeError, ValueError):
                pass
