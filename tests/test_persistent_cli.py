"""Integration tests for the shared meshcli subprocess without radio hardware."""

import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from src.backend.chat_store import ChatStore
from src.backend.contact_store import ContactStore
from src.backend.executor import MeshCoreBackend
from src.backend.persistent_cli import (
    EventBuffer,
    PersistentCLIError,
    PersistentCLITimeout,
    PersistentMeshCLI,
)
from src.config import Config


FAKE_MESHCLI = r'''
import json
import os
from pathlib import Path
import sys
import threading
import time

pending = {}
sync_count = 0

# Pre-interactive sync, interactive second sync and immediate auto-fetch.
print(json.dumps([{"type": "PRIV", "pubkey_prefix": "abc", "text": "from startup"}]), flush=True)
print(json.dumps([{"type": "CHAN", "channel_idx": 0, "text": "second startup sync"}]), flush=True)
print(json.dumps({"type": "PRIV", "pubkey_prefix": "def", "text": "initial auto fetch"}), flush=True)


def emit_contact(name="Heard Relay", key="ab" * 32):
    contact = {"public_key": key, "adv_name": name, "type": 2, "last_advert": 123}
    pending[key] = contact
    print(json.dumps({"event": "new_contact", "contact": contact}), flush=True)


def emit_message(text="asynchronous"):
    print(json.dumps({"type": "PRIV", "pubkey_prefix": "def", "text": text}), flush=True)


def emit_data():
    print(json.dumps({"type": "DATA", "channel_idx": 0, "data_type": 1, "payload": "0102"}), flush=True)


for raw_line in sys.stdin:
    line = raw_line.strip()
    if line.startswith("$$echo "):
        print(line.split()[-1], flush=True)
    elif line in ("$$set print_new_contacts on", "$$set json_msgs on"):
        pass
    elif line == "$$infos":
        emit_contact()
        print("Node information", flush=True)
    elif line == "$$arm_event":
        threading.Timer(0.03, emit_contact, kwargs={"name": "Idle Relay", "key": "cd" * 32}).start()
    elif line == "$$arm_message":
        threading.Timer(0.03, emit_message).start()
    elif line == "$$arm_data":
        threading.Timer(0.03, emit_data).start()
    elif line == "$$.pending_contacts":
        print(json.dumps(pending, indent=2), flush=True)
    elif line == "$$flush_pending":
        pending.clear()
        print("Pending flushed", flush=True)
    elif line == "$$add_pending Heard Relay":
        pending.pop("ab" * 32, None)
        print("Added", flush=True)
    elif line == "$$.sync_msgs":
        sync_count += 1
        messages = []
        if sync_count == 1:
            messages.append({"type": "CHAN", "channel_idx": 0, "text": "cost $$5"})
        print(json.dumps(messages), flush=True)
    elif line == "$$.recv":
        print(json.dumps({"type": "PRIV", "pubkey_prefix": "abc", "text": "from recv"}), flush=True)
    elif line == "$$.sm":
        print(json.dumps([{"type": "PRIV", "pubkey_prefix": "abc", "text": "partial $$ sync"}]), flush=True)
        time.sleep(5)
    elif line == "$$slow":
        time.sleep(0.08)
        print("slow result", flush=True)
    elif line == "$$block":
        time.sleep(5)
    elif line == "$$emit_close":
        emit_message("written before close")
        Path(os.environ["FAKE_EVENT_FILE"]).write_text("written", encoding="utf-8")
    else:
        print("unknown fake command: " + line, flush=True)
'''


class PersistentMeshCLITests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        script = Path(self.tmp_dir.name) / "fake_meshcli.py"
        script.write_text(FAKE_MESHCLI, encoding="utf-8")
        self.command = [sys.executable, "-u", str(script)]
        self.session = PersistentMeshCLI(self.command)

    def tearDown(self):
        self.session.close()
        self.tmp_dir.cleanup()

    def start(self):
        self.session.start(timeout=3)

    def test_contact_events_are_retained_between_commands(self):
        self.start()
        output = self.session.execute(["infos"], json_mode=False, timeout=1)
        self.assertEqual(output, "Node information")

        self.session.execute(["arm_event"], json_mode=False, timeout=1)
        time.sleep(0.08)  # The fake emits while no command is active.
        output = self.session.execute(["pending_contacts"], json_mode=True, timeout=1)
        merged = self.session.process_success(["pending_contacts"], True, output)
        contacts = json.loads(merged)
        self.assertEqual(contacts["ab" * 32]["adv_name"], "Heard Relay")
        self.assertEqual(contacts["cd" * 32]["adv_name"], "Idle Relay")

        output = self.session.execute(["add_pending", "Heard Relay"], False, 1)
        self.session.process_success(["add_pending", "Heard Relay"], False, output)
        self.assertNotIn("ab" * 32, self.session._pending_contacts)

        output = self.session.execute(["flush_pending"], False, 1)
        self.session.process_success(["flush_pending"], False, output)
        self.assertEqual(self.session._pending_contacts, {})

    def test_startup_and_async_messages_are_included_in_sync_once(self):
        self.start()
        self.session.execute(["arm_message"], json_mode=False, timeout=1)
        self.session.execute(["arm_data"], json_mode=False, timeout=1)
        time.sleep(0.08)

        output = self.session.execute(["sync_msgs"], json_mode=True, timeout=1)
        merged = self.session.process_success(["sync_msgs"], True, output)
        messages = json.loads(merged)
        self.assertEqual(
            [message.get("text", message.get("payload")) for message in messages],
            [
                "from startup",
                "second startup sync",
                "initial auto fetch",
                "asynchronous",
                "0102",
                "cost $$5",
            ],
        )

        output = self.session.execute(["sync_msgs"], json_mode=True, timeout=1)
        merged = self.session.process_success(["sync_msgs"], True, output)
        self.assertEqual(json.loads(merged), [])

    def test_recv_response_is_returned_not_stolen_for_later_sync(self):
        self.start()
        output = self.session.execute(["recv"], json_mode=True, timeout=1)
        self.assertEqual(json.loads(output)["text"], "from recv")
        self.session.process_success(["recv"], True, output)
        self.assertTrue(
            all(message.get("text") != "from recv" for message in self.session._message_buffer)
        )

    def test_partial_sync_alias_and_dollar_text_survive_timeout(self):
        self.start()
        events = self.session._events
        command = self.session._command
        with self.assertRaises(PersistentCLITimeout):
            self.session.execute(["sm"], json_mode=True, timeout=0.08)

        self.session = PersistentMeshCLI(command, events=events)
        self.start()
        output = self.session.execute(["sync_msgs"], json_mode=True, timeout=1)
        messages = json.loads(self.session.process_success(["sync_msgs"], True, output))
        self.assertIn("partial $$ sync", [message["text"] for message in messages])

    def test_plain_pending_output_is_not_replaced_by_empty_cache(self):
        key = "ab" * 32
        output = self.session.process_success(
            ["pending_contacts"], False, f"Alice: {key}"
        )
        self.assertIn(f"Alice: {key}", output)
        self.assertEqual(self.session._pending_contacts[key]["adv_name"], "Alice")

    def test_commands_are_serialized(self):
        self.start()
        outputs = []
        threads = [
            threading.Thread(
                target=lambda: outputs.append(
                    self.session.execute(["slow"], json_mode=False, timeout=1)
                )
            ),
            threading.Thread(
                target=lambda: outputs.append(
                    self.session.execute(["infos"], json_mode=False, timeout=1)
                )
            ),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2)
        self.assertCountEqual(outputs, ["slow result", "Node information"])

    def test_close_drains_events_already_written_to_pty(self):
        self.session.close()
        event_file = Path(self.tmp_dir.name) / "event-written"
        env = os.environ.copy()
        env["FAKE_EVENT_FILE"] = str(event_file)
        events = EventBuffer()
        self.session = PersistentMeshCLI(self.command, env=env, events=events)
        self.start()

        with self.session._condition:
            self.session._write_line("$$emit_close")
            deadline = time.monotonic() + 2
            while not event_file.exists() and time.monotonic() < deadline:
                time.sleep(0.005)
            self.assertTrue(event_file.exists())
            closer = threading.Thread(target=self.session.close)
            closer.start()
            time.sleep(0.02)
            # The close request may win the condition, but the reader must keep
            # draining until process EOF instead of stopping on a closing flag.
        closer.join(timeout=3)
        self.assertFalse(closer.is_alive())
        self.assertIn(
            "written before close",
            [message.get("text") for message in events.messages],
        )

    def test_timeout_closes_unusable_session(self):
        self.start()
        with self.assertRaises(PersistentCLITimeout):
            self.session.execute(["block"], json_mode=False, timeout=0.05)
        with self.assertRaises(PersistentCLIError):
            self.session.execute(["infos"], json_mode=False, timeout=0.1)


class EventBufferTests(unittest.TestCase):
    def test_spool_survives_reload_and_rotates_delivery_only_once(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "events.json"
            events = EventBuffer(path)
            events.add_messages([{"type": "PRIV", "text": "retained"}])
            events.merge_pending(
                [{"public_key": "ab" * 32, "adv_name": "Persistent Relay"}]
            )

            reloaded = EventBuffer(path)
            self.assertEqual(reloaded.messages[0]["text"], "retained")
            self.assertEqual(
                reloaded.pending_snapshot()["ab" * 32]["adv_name"],
                "Persistent Relay",
            )
            self.assertEqual(reloaded.deliver_sync([])[0]["text"], "retained")
            self.assertEqual(reloaded.deliver_sync([]), [])
            self.assertEqual(EventBuffer(path).messages, [])

    def test_identical_message_occurrences_are_not_deduplicated(self):
        events = EventBuffer()
        message = {"type": "PRIV", "text": "same", "sender_timestamp": 1234}
        events.add_messages([message])
        self.assertEqual(len(events.deliver_sync()), 1)

        events.add_messages([dict(message)])
        self.assertEqual(len(events.deliver_sync()), 1)
        self.assertEqual(events.deliver_sync(), [])

        events.add_messages([dict(message), dict(message)])
        self.assertEqual(len(events.deliver_sync()), 2)


class FullBackendProcessTests(unittest.TestCase):
    def test_contact_and_chat_stores_consume_shared_process_events(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            executable = Path(tmp_dir) / "meshcli"
            executable.write_text("#!/usr/bin/env python3\n" + FAKE_MESHCLI, encoding="utf-8")
            executable.chmod(0o755)
            config = Config(config_file=None)
            config.port = "/dev/fake"
            config.timeout = 1
            backend = MeshCoreBackend(config)
            backend._meshcli_bin = str(executable)
            try:
                ok, output = backend.run_cli(["infos"])
                self.assertTrue(ok, output)

                contacts = ContactStore(storage_path=None)
                heard = contacts.fetch_heard_nodes(backend)
                self.assertIn("Heard Relay", [node.name for node in heard])

                chats = ChatStore(storage_path=None)
                self.assertGreaterEqual(chats.sync_from_backend(backend), 3)
                self.assertEqual(chats.sync_from_backend(backend), 0)
            finally:
                backend.close()


class BackendSessionTests(unittest.TestCase):
    @patch("src.backend.executor.PersistentMeshCLI")
    def test_backend_reuses_and_restarts_one_session(self, session_class):
        first = session_class.return_value
        first.execute.return_value = "ok"
        first.process_success.side_effect = lambda _args, _json, output: output
        config = Config(config_file=None)
        config.port = "/dev/first"
        backend = MeshCoreBackend(config)

        self.assertEqual(backend.run_cli(["infos"]), (True, "ok"))
        self.assertEqual(backend.run_cli(["pending_contacts"], json_mode=True), (True, "ok"))
        session_class.assert_called_once()
        first.start.assert_called_once()
        self.assertEqual(first.execute.call_count, 2)
        command = session_class.call_args.args[0]
        self.assertIn("-i", command)
        self.assertIn("-j", command)
        self.assertIn(".sync_msgs", command)
        retained_events = session_class.call_args.kwargs["events"]
        self.assertIs(retained_events, backend._event_buffer)

        second = first  # The same mock is returned, but a new lifecycle is started.
        config.port = "/dev/second"
        backend.run_cli(["infos"])
        self.assertEqual(session_class.call_count, 2)
        self.assertIs(session_class.call_args.kwargs["events"], retained_events)
        self.assertGreaterEqual(second.close.call_count, 1)
        backend.close()
        self.assertGreaterEqual(second.close.call_count, 2)

    @patch("src.backend.executor.PersistentMeshCLI")
    def test_backend_preserves_application_errors(self, session_class):
        session = session_class.return_value
        session.execute.return_value = "Error: no contact"
        config = Config(config_file=None)
        backend = MeshCoreBackend(config)

        ok, output = backend.run_cli(["infos"])
        self.assertFalse(ok)
        self.assertIn("no contact", output)
        session.process_success.assert_not_called()
        backend.close()


if __name__ == "__main__":
    unittest.main()
