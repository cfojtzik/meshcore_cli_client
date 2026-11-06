"""Chat history and conversation store for channels and direct messages."""

import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..config import CONFIG_DIR
from .executor import MeshCoreBackend

CHAT_STORAGE_FILE = CONFIG_DIR / "chat_history.json"


@dataclass
class ChatMessage:
    sender: str
    text: str
    timestamp: str
    is_outgoing: bool = False
    status: str = ""  # e.g. "[ACK]", "[Sent]", "[Received]"

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
        # Map target_id -> List[ChatMessage]
        self.history: Dict[str, List[ChatMessage]] = {}
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
        self.targets = default_channels

    def get_or_create_target(
        self, name: str, is_channel: bool, channel_num: Optional[int] = None
    ) -> ChatTarget:
        """Get an existing chat target or create a new one."""
        clean_name = name.lstrip("#@").strip()
        target_id = f"chan_{channel_num if channel_num is not None else clean_name}" if is_channel else f"dm_{clean_name}"

        for t in self.targets:
            if t.id == target_id or t.name.lower() == clean_name.lower():
                return t

        new_target = ChatTarget(
            id=target_id,
            name=clean_name,
            is_channel=is_channel,
            channel_num=channel_num,
        )
        self.targets.append(new_target)
        if target_id not in self.history:
            self.history[target_id] = []
        self.save()
        return new_target

    def get_history(self, target_id: str) -> List[ChatMessage]:
        """Return message list for a specific chat target."""
        return self.history.get(target_id, [])

    def add_message(self, target_id: str, message: ChatMessage) -> None:
        """Add a message to the target's conversation history."""
        if target_id not in self.history:
            self.history[target_id] = []

        # Prevent exact duplicates
        for existing in self.history[target_id]:
            if (
                existing.timestamp == message.timestamp
                and existing.sender == message.sender
                and existing.text == message.text
            ):
                return

        self.history[target_id].append(message)
        self.save()

    def send_message(
        self, backend: MeshCoreBackend, target: ChatTarget, text: str
    ) -> Tuple[bool, str]:
        """Send a message via meshcore-cli and record it in history."""
        text = text.strip()
        if not text:
            return False, "Leere Nachricht kann nicht gesendet werden."

        now_str = datetime.now().strftime("%H:%M:%S")

        if target.is_channel:
            if target.channel_num == 0 or target.channel_num is None:
                # Public broadcast
                ok, res = backend.run_cli(["public", text])
            else:
                ok, res = backend.run_cli(["chan", str(target.channel_num), text])
        else:
            # Direct message to contact
            ok, res = backend.run_cli(["msg", target.name, text, "wait_ack"])

        status = "[ACK]" if ok else "[Fehler]"
        msg = ChatMessage(
            sender="Ich",
            text=text,
            timestamp=now_str,
            is_outgoing=True,
            status=status,
        )
        self.add_message(target.id, msg)
        return ok, res

    def sync_from_backend(self, backend: MeshCoreBackend) -> int:
        """
        Sync unread messages from node via sync_msgs and route them to targets.
        Returns count of newly added messages.
        """
        ok, res = backend.run_cli(["sync_msgs"], json_mode=True)
        new_count = 0

        # Try parsing JSON first
        if ok and res.strip().startswith("[") and res.strip().endswith("]"):
            try:
                data = json.loads(res.strip())
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict):
                            sender = item.get("sender") or item.get("from") or "Unknown"
                            text = item.get("text") or item.get("msg") or ""
                            ts_val = item.get("sender_timestamp") or item.get("time") or time.time()
                            if isinstance(ts_val, (int, float)):
                                ts_str = datetime.fromtimestamp(ts_val).strftime("%H:%M:%S")
                            else:
                                ts_str = str(ts_val)

                            chan = item.get("channel")
                            is_chan = chan is not None
                            target = self.get_or_create_target(
                                name=f"Public (0)" if chan == 0 else (f"Kanal {chan}" if is_chan else sender),
                                is_channel=is_chan,
                                channel_num=chan if is_chan else None,
                            )
                            msg = ChatMessage(
                                sender=sender,
                                text=text,
                                timestamp=ts_str,
                                is_outgoing=False,
                                status="[RX]",
                            )
                            before_len = len(self.get_history(target.id))
                            self.add_message(target.id, msg)
                            if len(self.get_history(target.id)) > before_len:
                                new_count += 1
                    return new_count
            except Exception:
                pass

        # Fallback to parsing text output (e.g. from simulation or raw text mode)
        ok_txt, text_res = backend.run_cli(["sync_msgs"])
        if ok_txt and text_res:
            for line in text_res.splitlines():
                line = line.strip()
                if not line or "Synchronized Messages" in line:
                    continue
                # Example: [12:01] [Public (0)] BaseStation-1: Beacon broadcast OK.
                # Example: [12:05] BaseStation-1: Hello
                try:
                    ts_str = datetime.now().strftime("%H:%M:%S")
                    msg_body = line
                    target_name = "Public (0)"
                    is_chan = True
                    chan_num = 0

                    if line.startswith("[") and "]" in line:
                        parts = line.split("]", 2)
                        if len(parts) >= 2:
                            ts_str = parts[0].strip("[ ")
                            rest = parts[1].strip()
                            if rest.startswith("[") and "]" in rest:
                                # Channel tag present
                                chan_tag = rest.strip("[] ")
                                target_name = chan_tag
                                is_chan = True
                                msg_body = parts[2].strip() if len(parts) > 2 else ""
                            else:
                                msg_body = rest

                    if ":" in msg_body:
                        sender, content = msg_body.split(":", 1)
                        sender = sender.strip().lstrip("• ")
                        content = content.strip()
                    else:
                        sender = "Node"
                        content = msg_body

                    target = self.get_or_create_target(
                        name=target_name,
                        is_channel=is_chan,
                        channel_num=chan_num,
                    )
                    msg = ChatMessage(
                        sender=sender,
                        text=content,
                        timestamp=ts_str,
                        is_outgoing=False,
                        status="[RX]",
                    )
                    before_len = len(self.get_history(target.id))
                    self.add_message(target.id, msg)
                    if len(self.get_history(target.id)) > before_len:
                        new_count += 1
                except Exception:
                    continue

        return new_count

    def populate_targets_from_backend(self, backend: MeshCoreBackend) -> None:
        """Fetch discovered channels and contacts to build room list."""
        # Channels
        ok_ch, res_ch = backend.run_cli(["get_channels"])
        if ok_ch and res_ch:
            for line in res_ch.splitlines():
                if "CH " in line and "Name:" in line:
                    try:
                        # Extract channel num and name
                        ch_part = line.split("Name:")[0]
                        num_str = ch_part.split("CH")[1].strip(" []|:")
                        num = int(num_str)
                        name_part = line.split("Name:")[1].split("|")[0].strip()
                        self.get_or_create_target(
                            name=f"{name_part} ({num})",
                            is_channel=True,
                            channel_num=num,
                        )
                    except Exception:
                        pass

        # Contacts
        ok_ct, res_ct = backend.run_cli(["contacts"])
        if ok_ct and res_ct:
            for line in res_ct.splitlines():
                line = line.strip().lstrip("• ")
                if "[" in line and "]" in line and not line.startswith("Contacts List"):
                    name = line.split("[")[0].strip()
                    if name:
                        self.get_or_create_target(
                            name=name,
                            is_channel=False,
                        )

    def load(self) -> None:
        """Load stored messages and custom targets from disk."""
        if not self.storage_path or not self.storage_path.exists():
            return
        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    # Load targets
                    raw_targets = data.get("targets", [])
                    for t_data in raw_targets:
                        self.get_or_create_target(
                            name=t_data["name"],
                            is_channel=t_data["is_channel"],
                            channel_num=t_data.get("channel_num"),
                        )

                    # Load history
                    raw_history = data.get("history", {})
                    for t_id, msgs in raw_history.items():
                        self.history[t_id] = [ChatMessage.from_dict(m) for m in msgs]
        except Exception:
            pass

    def save(self) -> None:
        """Save chat history and targets to disk."""
        if not self.storage_path:
            return
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            serializable_history = {
                t_id: [m.to_dict() for m in msgs] for t_id, msgs in self.history.items()
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
                    {"targets": serializable_targets, "history": serializable_history},
                    f,
                    indent=2,
                )
        except Exception:
            pass
