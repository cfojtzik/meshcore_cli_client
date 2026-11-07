"""One shared interactive meshcli process with durable event retention.

The companion is a single serial resource. This module keeps one meshcli
session open, serializes commands, and retains contact/message events which
arrive between commands. No third-party terminal wrapper is required.
"""

import codecs
from collections import deque
from dataclasses import dataclass, field
import fcntl
import json
import os
from pathlib import Path
import pty
import re
import select
import shlex
import struct
import subprocess
import termios
import threading
import time
import uuid
from typing import Any, Deque, Dict, Iterable, List, Optional, Set, Tuple


_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b[@-_]")
_MESSAGE_TYPES = {"PRIV", "CHAN", "DATA"}
_COMMAND_ALIASES = {
    "sm": "sync_msgs",
    "r": "recv",
    "wm": "wait_msg",
    "wmt": "trywait_msg",
}
_MESSAGE_COMMANDS = {
    "sync_msgs",
    "recv",
    "wait_msg",
    "trywait_msg",
    "wmt8",
    "]",
}


# Virtual terminal size of the meshcli session: wide enough that no prompt plus
# command (names, scopes, long message texts) is ever wrapped.
_PTY_COLUMNS = 4000
_PTY_ROWS = 50

_DEFAULT_SCOPE_VALUES = {"", "0", "none", "clear"}


def normalize_scope(value: Any) -> str:
    """Return the flood scope as meshcli stores it; "" means device default."""
    scope = str(value or "").strip()
    return "" if scope.casefold() in _DEFAULT_SCOPE_VALUES else scope


def scope_line(scope: str) -> str:
    """Interactive (non-$$) scope line which also updates meshcli's loop scope.

    The interactive loop re-applies its own scope variable before every input
    line, so a raw '$$scope X' alone is reverted by the very next command.
    """
    return f"scope {normalize_scope(scope) or '0'}"


class PersistentCLIError(RuntimeError):
    """The shared meshcli process cannot execute further commands."""


class PersistentCLITimeout(PersistentCLIError):
    """A command did not reach its completion marker in time."""


class EventBuffer:
    """Durable message/pending state shared by successive CLI processes.

    Delivered messages are removed at the beginning of the following sync,
    not before the current response is returned. A crash can therefore cause a
    duplicate, which ChatStore deduplicates, but never silent message loss.
    """

    def __init__(self, storage_path: Optional[Path] = None) -> None:
        self.storage_path = storage_path
        self._lock = threading.RLock()
        self.messages: List[Dict[str, Any]] = []
        self.message_ids: List[str] = []
        self.pending_contacts: Dict[str, Dict[str, Any]] = {}
        self.heard_adverts: Dict[str, Dict[str, Any]] = {}
        self._delivered_event_ids: Set[str] = set()
        self._load()

    @staticmethod
    def _message_key(message: Dict[str, Any]) -> str:
        return json.dumps(message, sort_keys=True, ensure_ascii=False, default=str)

    @staticmethod
    def contact_key(contact: Dict[str, Any]) -> str:
        return str(
            contact.get("public_key")
            or contact.get("pubkey")
            or contact.get("key")
            or ""
        ).strip()

    def _load(self) -> None:
        if not self.storage_path or not self.storage_path.exists():
            return
        try:
            with self.storage_path.open("r", encoding="utf-8") as file:
                data = json.load(file)
            if not isinstance(data, dict):
                return
            messages = data.get("messages", [])
            pending = data.get("pending_contacts", {})
            adverts = data.get("heard_adverts", {})
            if isinstance(messages, list):
                self.messages[:] = [dict(item) for item in messages if isinstance(item, dict)]
                stored_ids = data.get("message_ids", [])
                if (
                    isinstance(stored_ids, list)
                    and len(stored_ids) == len(self.messages)
                    and all(isinstance(item, str) and item for item in stored_ids)
                ):
                    self.message_ids[:] = list(stored_ids)
                else:
                    self.message_ids[:] = [uuid.uuid4().hex for _ in self.messages]
            if isinstance(pending, dict):
                for key, contact in pending.items():
                    if isinstance(contact, dict):
                        self.pending_contacts[self.contact_key(contact) or str(key)] = dict(contact)
            if isinstance(adverts, dict):
                for key, advert in adverts.items():
                    if isinstance(advert, dict):
                        self.heard_adverts[str(key)] = dict(advert)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            # A broken spool must not block access to the companion.
            return

    def _save_locked(self) -> None:
        if not self.storage_path:
            return
        temporary = self.storage_path.with_name(self.storage_path.name + ".tmp")
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            with temporary.open("w", encoding="utf-8") as file:
                json.dump(
                    {
                        "messages": self.messages,
                        "message_ids": self.message_ids,
                        "pending_contacts": self.pending_contacts,
                        "heard_adverts": self.heard_adverts,
                    },
                    file,
                    ensure_ascii=False,
                    indent=2,
                )
            os.replace(temporary, self.storage_path)
        except (OSError, TypeError, ValueError):
            # In-memory retention still protects normal session restarts.
            return

    def _add_messages_locked(self, messages: Iterable[Dict[str, Any]]) -> None:
        changed = False
        for message in messages:
            # Each occurrence gets its own identity. Two genuinely identical
            # frames must remain two events; ChatStore performs content dedup.
            self.messages.append(dict(message))
            self.message_ids.append(uuid.uuid4().hex)
            changed = True
        if changed:
            self._save_locked()

    def add_messages(self, messages: Iterable[Dict[str, Any]]) -> None:
        with self._lock:
            self._add_messages_locked(messages)

    def deliver_sync(self, response_messages: Iterable[Dict[str, Any]] = ()) -> List[Dict[str, Any]]:
        """Return retained occurrences and rotate the previous delivery.

        The reader has already spooled every response occurrence. The optional
        legacy argument is deliberately not added again, which would duplicate
        the same transport event while identical real events must stay distinct.
        """
        with self._lock:
            if self._delivered_event_ids:
                retained = [
                    (event_id, message)
                    for event_id, message in zip(self.message_ids, self.messages)
                    if event_id not in self._delivered_event_ids
                ]
                self.message_ids[:] = [event_id for event_id, _ in retained]
                self.messages[:] = [message for _, message in retained]
            self._delivered_event_ids.clear()
            delivered = [dict(message) for message in self.messages]
            self._delivered_event_ids = set(self.message_ids)
            self._save_locked()
            return delivered

    def discard_messages(self, messages: Iterable[Dict[str, Any]]) -> None:
        """Acknowledge response occurrences returned by recv/wait_msg."""
        response_keys = [self._message_key(message) for message in messages]
        if not response_keys:
            return
        with self._lock:
            changed = False
            for key in response_keys:
                index = next(
                    (
                        index
                        for index, message in enumerate(self.messages)
                        if self._message_key(message) == key
                    ),
                    None,
                )
                if index is not None:
                    self.messages.pop(index)
                    removed_id = self.message_ids.pop(index)
                    self._delivered_event_ids.discard(removed_id)
                    changed = True
            if changed:
                self._save_locked()

    def merge_pending(self, contacts: Iterable[Dict[str, Any]]) -> None:
        with self._lock:
            changed = False
            for contact in contacts:
                key = self.contact_key(contact)
                if key and self.pending_contacts.get(key) != contact:
                    self.pending_contacts[key] = dict(contact)
                    changed = True
            if changed:
                self._save_locked()

    def pending_snapshot(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return {key: dict(contact) for key, contact in self.pending_contacts.items()}

    def record_advert(self, public_key: str) -> None:
        key = str(public_key or "").strip()
        if not key:
            return
        with self._lock:
            self.heard_adverts[key] = {
                "public_key": key,
                "last_heard": time.time(),
            }
            self._save_locked()

    def advert_snapshot(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(advert) for advert in self.heard_adverts.values()]

    def clear_adverts(self) -> None:
        with self._lock:
            self.heard_adverts.clear()
            self._save_locked()

    def remove_pending(self, target: str) -> None:
        normalized = target.strip().casefold()
        if not normalized:
            return
        with self._lock:
            for key, contact in list(self.pending_contacts.items()):
                name = str(contact.get("adv_name") or contact.get("name") or "").strip().casefold()
                if key.casefold().startswith(normalized) or name == normalized:
                    self.pending_contacts.pop(key, None)
            self._save_locked()

    def clear_pending(self) -> None:
        with self._lock:
            self.pending_contacts.clear()
            self._save_locked()


@dataclass
class _Command:
    args: List[str]
    json_mode: bool
    marker: str
    lines: List[str] = field(default_factory=list)
    done: bool = False
    error: str = ""


class PersistentMeshCLI:
    """Serialize commands and retain events from one interactive meshcli."""

    def __init__(
        self,
        command: List[str],
        env: Optional[Dict[str, str]] = None,
        events: Optional[EventBuffer] = None,
        scope: str = "",
    ) -> None:
        self._command = list(command)
        self._env = env
        # Flood scope re-applied at start; meshcli begins with the default.
        self._scope = normalize_scope(scope)
        self._events = events or EventBuffer()
        # Stable aliases retained for diagnostics and backwards-compatible tests.
        self._pending_contacts = self._events.pending_contacts
        self._message_buffer = self._events.messages
        self._process: Optional[subprocess.Popen] = None
        self._master_fd: Optional[int] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._text_buffer = ""
        self._condition = threading.Condition()
        self._execute_lock = threading.Lock()
        self._close_lock = threading.Lock()
        self._active: Optional[_Command] = None
        self._ready = False
        self._ready_marker = ""
        self._start_error = ""
        self._startup_lines: List[str] = []
        self._sent_lines: Deque[str] = deque(maxlen=64)
        self._closing = False
        self._closed = False

    @staticmethod
    def _clean_line(line: str) -> str:
        return _ANSI_RE.sub("", line).replace("\x00", "").strip()

    @staticmethod
    def _json_values(text: str) -> List[Any]:
        """Recover complete JSON values from a line or a whole response."""
        decoder = json.JSONDecoder()
        values: List[Any] = []
        index = 0
        while index < len(text):
            if text[index] not in "[{":
                index += 1
                continue
            try:
                value, end = decoder.raw_decode(text, index)
            except json.JSONDecodeError:
                index += 1
                continue
            values.append(value)
            index = end
        return values

    @staticmethod
    def _is_message(value: Any) -> bool:
        return isinstance(value, dict) and value.get("type") in _MESSAGE_TYPES

    @classmethod
    def _messages_from_output(cls, output: str) -> List[Dict[str, Any]]:
        messages: List[Dict[str, Any]] = []
        for value in cls._json_values(output):
            if cls._is_message(value):
                messages.append(value)
            elif isinstance(value, list):
                messages.extend(item for item in value if cls._is_message(item))
        return messages

    @staticmethod
    def _command_name(args: List[str]) -> str:
        if not args:
            return ""
        name = args[0].lstrip(".").casefold()
        return _COMMAND_ALIASES.get(name, name)

    def _record_contact_event(self, contact: Dict[str, Any]) -> None:
        if EventBuffer.contact_key(contact):
            self._events.merge_pending([contact])

    def _handle_json_line(self, line: str, command: Optional[_Command]) -> bool:
        """Handle asynchronous JSON events; return whether to drop the line."""
        values = self._json_values(line)
        if not values:
            return False
        candidates: List[Dict[str, Any]] = []
        for value in values:
            if isinstance(value, dict):
                candidates.append(value)
            elif isinstance(value, list):
                candidates.extend(item for item in value if isinstance(item, dict))

        drop_line = False
        command_is_message_producer = (
            command is not None and self._command_name(command.args) in _MESSAGE_COMMANDS
        )
        for value in candidates:
            if value.get("event") == "advert":
                self._events.record_advert(str(value.get("public_key") or ""))
                drop_line = True
            elif value.get("event") == "new_contact" and isinstance(value.get("contact"), dict):
                self._record_contact_event(value["contact"])
                drop_line = True
            elif self._is_message(value):
                # Spool immediately, including partial commands which later fail.
                self._events.add_messages([value])
                if not command_is_message_producer:
                    drop_line = True
        return drop_line

    def _finish_process_locked(self, reason: str) -> None:
        if not self._ready:
            self._start_error = reason
        if self._active is not None and not self._active.done:
            self._active.error = reason
            self._active.done = True
        self._condition.notify_all()

    def _is_transport_line_locked(self, line: str) -> bool:
        # Rendered input ends with the exact command. A JSON payload containing
        # '$$' or similar text does not match unless it is genuinely that input.
        return any(line.endswith(sent) for sent in self._sent_lines)

    def _handle_line_locked(self, raw_line: str) -> None:
        line = self._clean_line(raw_line)
        if not line:
            return

        if self._ready_marker and self._ready_marker in line and "$$echo" not in line:
            self._ready = True
            self._condition.notify_all()
            return

        command = self._active
        if (
            command is not None
            and not command.done
            and command.marker in line
            and "$$echo" not in line
        ):
            command.done = True
            self._condition.notify_all()
            return

        receiving = command if command is not None and not command.done else None
        if self._handle_json_line(line, receiving):
            return
        if self._is_transport_line_locked(line):
            return
        if receiving is not None:
            receiving.lines.append(line)
        elif not self._ready:
            self._startup_lines.append(line)

    def _answer_terminal_queries(self, text: str) -> str:
        """Answer prompt-toolkit CPR queries because no terminal emulator exists."""
        if "\x1b[6n" not in text:
            return text
        fd = self._master_fd
        if fd is not None:
            try:
                os.write(fd, b"\x1b[1;1R")
            except OSError:
                pass
        return text.replace("\x1b[6n", "")

    def _reader(self) -> None:
        reason = "meshcli-Sitzung wurde unerwartet beendet."
        try:
            while not self._closed:
                fd = self._master_fd
                process = self._process
                if fd is None or process is None:
                    break
                readable, _, _ = select.select([fd], [], [], 0.1)
                if not readable:
                    if process.poll() is not None:
                        break
                    continue
                try:
                    chunk = os.read(fd, 8192)
                except OSError:
                    break
                if not chunk:
                    break
                self._text_buffer += self._decoder.decode(chunk)
                self._text_buffer = self._answer_terminal_queries(self._text_buffer)
                self._text_buffer = self._text_buffer.replace("\r\n", "\n").replace("\r", "\n")
                lines = self._text_buffer.split("\n")
                self._text_buffer = lines.pop()
                with self._condition:
                    for line in lines:
                        self._handle_line_locked(line)
        finally:
            tail = self._text_buffer + self._decoder.decode(b"", final=True)
            if tail:
                with self._condition:
                    self._handle_line_locked(tail)
            with self._condition:
                self._finish_process_locked(reason)

    def _write_line(self, line: str) -> None:
        fd = self._master_fd
        process = self._process
        if fd is None or process is None or process.poll() is not None:
            raise PersistentCLIError("meshcli-Sitzung ist nicht verbunden.")
        with self._condition:
            self._sent_lines.append(line)
        data = (line + "\n").encode("utf-8")
        try:
            view = memoryview(data)
            while view:
                written = os.write(fd, view)
                view = view[written:]
        except OSError as exc:
            raise PersistentCLIError(f"meshcli-Eingabe fehlgeschlagen: {exc}") from exc

    def start(self, timeout: float = 20) -> None:
        """Start meshcli and wait until its interactive loop is ready."""
        if self._process is not None:
            return
        master_fd, slave_fd = pty.openpty()
        try:
            # prompt_toolkit wraps input echoes at the terminal width. With a
            # long prompt (node name + flood scope) or command, fragments of
            # the wrapped echo would otherwise leak into command output.
            fcntl.ioctl(
                slave_fd,
                termios.TIOCSWINSZ,
                struct.pack("HHHH", _PTY_ROWS, _PTY_COLUMNS, 0, 0),
            )
            self._process = subprocess.Popen(
                self._command,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                close_fds=True,
                start_new_session=True,
                env=self._env,
            )
        except Exception:
            os.close(master_fd)
            os.close(slave_fd)
            raise
        self._master_fd = master_fd
        os.close(slave_fd)
        self._reader_thread = threading.Thread(
            target=self._reader, daemon=True, name="meshcore-meshcli-events"
        )
        self._reader_thread.start()

        self._ready_marker = f"__MESHCORE_READY_{uuid.uuid4().hex}__"
        try:
            self._write_line("$$set print_new_contacts on")
            self._write_line("$$set print_adverts on")
            self._write_line("$$set json_msgs on")
            if self._scope:
                self._write_line(scope_line(self._scope))
            self._write_line(f"$$echo {self._ready_marker}")
            deadline = time.monotonic() + timeout
            with self._condition:
                while not self._ready and not self._start_error:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise PersistentCLITimeout(
                            "Zeitüberschreitung beim Start der gemeinsamen meshcli-Sitzung."
                        )
                    self._condition.wait(remaining)
                if self._start_error:
                    detail = "\n".join(self._startup_lines[-8:])
                    raise PersistentCLIError(
                        f"{self._start_error}{chr(10) + detail if detail else ''}"
                    )
        except Exception:
            self.close()
            raise

    def execute(self, args: List[str], json_mode: bool, timeout: float) -> str:
        """Execute one command and return output up to its completion marker."""
        if not args:
            raise PersistentCLIError("Kein meshcli-Befehl angegeben.")
        with self._execute_lock:
            if (
                self._closing
                or self._closed
                or self._process is None
                or self._process.poll() is not None
            ):
                raise PersistentCLIError("meshcli-Sitzung ist nicht verbunden.")

            command_args = list(args)
            if json_mode and not command_args[0].startswith("."):
                command_args[0] = "." + command_args[0]
            command = _Command(
                args=command_args,
                json_mode=json_mode,
                marker=f"__MESHCORE_DONE_{uuid.uuid4().hex}__",
            )
            is_scope = self._command_name(command_args) == "scope" and len(command_args) > 1
            with self._condition:
                self._active = command
            try:
                # The raw command reports errors such as an unsupported scope.
                self._write_line("$$" + shlex.join(command_args))
                if is_scope:
                    # Keep the interactive loop from reverting the new scope.
                    self._write_line(scope_line(command_args[1]))
                self._write_line(f"$$echo {command.marker}")
                deadline = time.monotonic() + timeout
                with self._condition:
                    while not command.done:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise PersistentCLITimeout(
                                f"Zeitüberschreitung ({timeout:g}s) beim Warten auf Companion."
                            )
                        self._condition.wait(remaining)
                    if command.error:
                        raise PersistentCLIError(command.error)
            except Exception:
                self.close()
                raise
            finally:
                with self._condition:
                    if self._active is command:
                        self._active = None
            return "\n".join(command.lines).strip()

    def process_success(self, args: List[str], json_mode: bool, output: str) -> str:
        """Merge retained events after a command was validated as successful."""
        name = self._command_name(args)
        if name == "sync_msgs" and json_mode:
            messages = self._events.deliver_sync(self._messages_from_output(output))
            return json.dumps(messages)

        if name in _MESSAGE_COMMANDS and name != "sync_msgs":
            # recv/wait_msg return consumed messages directly to their caller.
            self._events.discard_messages(self._messages_from_output(output))
            return output

        if name == "pending_contacts":
            json_values = self._json_values(output)
            for value in json_values:
                records: Any = value
                if isinstance(records, dict) and isinstance(
                    records.get("pending_contacts"), (dict, list)
                ):
                    records = records["pending_contacts"]
                if isinstance(records, dict):
                    self._events.merge_pending(
                        contact for contact in records.values() if isinstance(contact, dict)
                    )
                elif isinstance(records, list):
                    self._events.merge_pending(
                        contact for contact in records if isinstance(contact, dict)
                    )
            # Older/text-only output is additive and must never be erased. JSON
            # lines such as '"lastmod": 1794055014' must not be read as text.
            for line in ([] if json_values else output.splitlines()):
                match = re.fullmatch(
                    r"\s*(?P<name>.+?):\s*(?P<key>[0-9a-fA-F]{8,64})\s*", line
                )
                if match:
                    self._events.merge_pending(
                        [{"adv_name": match.group("name"), "public_key": match.group("key")}]
                    )
            pending = self._events.pending_snapshot()
            if json_mode:
                return json.dumps(pending)
            return "\n".join(
                f"{contact.get('adv_name', contact.get('name', key))}: {key}"
                for key, contact in pending.items()
            )

        if name == "flush_pending":
            self._events.clear_pending()
        elif name == "add_pending" and len(args) > 1:
            self._events.remove_pending(args[1])
        return output

    def close(self) -> None:
        """Reap meshcli, drain already-written PTY events, then close the fd."""
        with self._close_lock:
            with self._condition:
                if self._closed:
                    return
                self._closing = True
                self._finish_process_locked("meshcli-Sitzung wurde geschlossen.")

            process = self._process
            if process is not None:
                try:
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=1)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=1)
                    else:
                        process.wait(timeout=0)
                except (OSError, subprocess.TimeoutExpired):
                    pass

            # Do not stop the reader merely because closing was requested:
            # bytes flushed by meshcli before termination still need spooling.
            reader = self._reader_thread
            if reader is not None and reader.is_alive():
                reader.join(timeout=2)

            fd = self._master_fd
            if reader is not None and reader.is_alive():
                # Fallback for a broken platform reader; the normal path above
                # always reaches EOF before the descriptor is closed.
                with self._condition:
                    self._closed = True
                    self._condition.notify_all()
            self._master_fd = None
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
            if reader is not None and reader.is_alive():
                reader.join(timeout=0.5)
            with self._condition:
                self._closed = True
                self._condition.notify_all()
