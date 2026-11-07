"""Unit tests for ChatStore and chat message handling."""

import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.backend.chat_store import ChatMessage, ChatStore, ChatTarget


class FakeBackend:
    """Small argv-preserving backend fake; no companion hardware is needed."""

    def __init__(self):
        self.calls = []
        self.responses = {}

    def respond(self, args, *responses):
        self.responses[tuple(args)] = list(responses)

    def run_cli(self, args, json_mode=False, timeout=None):
        args = list(args)
        self.calls.append((args, json_mode))
        responses = self.responses.get(tuple(args))
        if not responses:
            return True, "OK"
        if len(responses) > 1:
            return responses.pop(0)
        return responses[0]


class TestChatStore(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.storage_file = Path(self.tmp_dir.name) / "test_chat.json"
        self.chat_store = ChatStore(storage_path=self.storage_file)
        self.backend = FakeBackend()

    def tearDown(self):
        self.tmp_dir.cleanup()

    def _sync(self, *items):
        self.backend.respond(["sync_msgs"], (True, json.dumps(list(items))))
        return self.chat_store.sync_from_backend(self.backend)

    @staticmethod
    def _chan(text, channel_idx=3, timestamp=1794070147):
        return {
            "type": "CHAN",
            "channel_idx": channel_idx,
            "sender_timestamp": timestamp,
            "text": text,
        }

    def test_channel_sender_is_split_from_firmware_text(self):
        self.assertEqual(self._sync(self._chan("CF T-Deck: kam das an?")), 1)
        target = self.chat_store.get_or_create_target("Kanal 3", True, 3)
        message = self.chat_store.get_history(target.id)[-1]
        self.assertEqual((message.sender, message.text), ("CF T-Deck", "kam das an?"))
        # The identity stays the pre-split one, so re-delivery is no duplicate.
        self.assertIn('"sender": "Unknown"', message.dedup_key)
        self.assertEqual(self._sync(self._chan("CF T-Deck: kam das an?")), 0)

        # Names with separators, colons later in the text, and texts without
        # a sender prefix.
        self._sync(self._chan("DE|BW|LB CF-USB: Zeit: 18:00", timestamp=2))
        self._sync(self._chan("ohne Absender", timestamp=3))
        history = self.chat_store.get_history(target.id)
        self.assertEqual((history[-2].sender, history[-2].text), ("DE|BW|LB CF-USB", "Zeit: 18:00"))
        self.assertEqual((history[-1].sender, history[-1].text), ("Unknown", "ohne Absender"))

    def test_direct_messages_are_not_split(self):
        self._sync({"type": "PRIV", "pubkey_prefix": "abcdef", "sender_timestamp": 5, "text": "Hinweis: Test"})
        target = self.chat_store.get_or_create_target("abcdef", False)
        message = self.chat_store.get_history(target.id)[-1]
        self.assertEqual((message.sender, message.text), ("abcdef", "Hinweis: Test"))

    def test_legacy_channel_messages_are_split_on_load(self):
        legacy = {
            "targets": [{"id": "chan_3", "name": "#stuttgart (3)", "is_channel": True, "channel_num": 3}],
            "history": {
                "chan_3": [
                    {"sender": "Unknown", "text": "CF T-Deck: alt", "timestamp": "17:00"},
                    {"sender": "Ich", "text": "Gruß: an alle", "timestamp": "17:01", "is_outgoing": True},
                ]
            },
        }
        self.storage_file.write_text(json.dumps(legacy), encoding="utf-8")
        history = ChatStore(storage_path=self.storage_file).get_history("chan_3")
        self.assertEqual((history[0].sender, history[0].text), ("CF T-Deck", "alt"))
        self.assertEqual((history[1].sender, history[1].text), ("Ich", "Gruß: an alle"))

    def test_unread_counts_are_tracked_persisted_and_cleared(self):
        self._sync(self._chan("A: eins", timestamp=1), self._chan("B: zwei", timestamp=2))
        self._sync(self._chan("A: eins", timestamp=1))  # Duplicate is not unread.
        target = self.chat_store.get_or_create_target("Kanal 3", True, 3)
        self.assertEqual(self.chat_store.unread_count(target.id), 2)
        self.assertEqual(self.chat_store.unread_targets(), [(target, 2)])

        sent_target = self.chat_store.targets[0]
        self.chat_store.send_message(self.backend, sent_target, "eigene Nachricht")
        self.assertEqual(self.chat_store.unread_count(sent_target.id), 0)

        reloaded = ChatStore(storage_path=self.storage_file)
        self.assertEqual(reloaded.unread_count(target.id), 2)
        self.assertTrue(reloaded.mark_read(target.id))
        self.assertFalse(reloaded.mark_read(target.id))
        self.assertEqual(ChatStore(storage_path=self.storage_file).unread_count(target.id), 0)

        self._sync(self._chan("C: drei", timestamp=3))
        self.chat_store.clear_history(target.id)
        self.assertEqual(self.chat_store.unread_targets(), [])

    def test_default_targets(self):
        self.assertGreaterEqual(len(self.chat_store.targets), 3)
        tags = [target.display_tag for target in self.chat_store.targets]
        self.assertIn("#Public (0)", tags)

    def test_get_or_create_target(self):
        target = self.chat_store.get_or_create_target("Mobile-Bravo", is_channel=False)
        self.assertEqual(target.name, "Mobile-Bravo")
        self.assertFalse(target.is_channel)
        self.assertEqual(target.display_tag, "@Mobile-Bravo")

        target2 = self.chat_store.get_or_create_target("Mobile-Bravo", is_channel=False)
        self.assertIs(target, target2)

    def test_same_name_channel_and_dm_do_not_collide(self):
        dm = self.chat_store.get_or_create_target("SharedName", is_channel=False)
        channel = self.chat_store.get_or_create_target("SharedName", is_channel=True)

        self.assertEqual(dm.id, "dm_SharedName")
        self.assertEqual(channel.id, "chan_SharedName")
        self.assertIs(
            self.chat_store.get_or_create_target("sharedname", is_channel=False), dm
        )
        self.assertIs(
            self.chat_store.get_or_create_target("sharedname", is_channel=True), channel
        )

        self.chat_store.add_message(
            dm.id, ChatMessage(sender="A", text="DM", timestamp="12:00")
        )
        self.chat_store.add_message(
            channel.id, ChatMessage(sender="B", text="Channel", timestamp="12:01")
        )
        self.assertEqual([m.text for m in self.chat_store.get_history(dm.id)], ["DM"])
        self.assertEqual(
            [m.text for m in self.chat_store.get_history(channel.id)], ["Channel"]
        )

    def test_add_and_get_message(self):
        target = self.chat_store.targets[0]
        msg = ChatMessage(
            sender="TestSender",
            text="Hallo Mesh!",
            timestamp="12:00:00",
            is_outgoing=False,
            status="[RX]",
        )
        self.chat_store.add_message(target.id, msg)
        history = self.chat_store.get_history(target.id)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].text, "Hallo Mesh!")
        self.assertEqual(history[0].sender, "TestSender")

    def test_delete_message_removes_exactly_one_and_persists(self):
        target = self.chat_store.targets[0]
        other_target = self.chat_store.targets[1]
        for text in ("erste", "zweite", "dritte"):
            self.chat_store.add_message(
                target.id, ChatMessage(sender="A", text=text, timestamp="12:00")
            )
        self.chat_store.add_message(
            other_target.id,
            ChatMessage(sender="B", text="unverändert", timestamp="12:01"),
        )

        self.assertTrue(self.chat_store.delete_message(target.id, 1))
        self.assertEqual(
            [message.text for message in self.chat_store.get_history(target.id)],
            ["erste", "dritte"],
        )
        self.assertEqual(len(self.chat_store.get_history(other_target.id)), 1)

        reloaded = ChatStore(storage_path=self.storage_file)
        self.assertEqual(
            [message.text for message in reloaded.get_history(target.id)],
            ["erste", "dritte"],
        )
        self.assertEqual(len(reloaded.get_history(other_target.id)), 1)

    def test_delete_message_invalid_index_does_not_write(self):
        target = self.chat_store.targets[0]
        for text in ("erste", "zweite"):
            self.chat_store.add_message(
                target.id, ChatMessage(sender="A", text=text, timestamp="12:00")
            )
        contents_before = self.storage_file.read_bytes()
        invalid_targets_and_indexes = (
            (target.id, -1),
            (target.id, 2),
            (target.id, True),
            (target.id, "0"),
            ("missing", 0),
        )
        with patch.object(self.chat_store, "save") as mock_save:
            for target_id, index in invalid_targets_and_indexes:
                with self.subTest(target_id=target_id, index=index):
                    self.assertFalse(self.chat_store.delete_message(target_id, index))
                    self.assertEqual(len(self.chat_store.get_history(target.id)), 2)
            mock_save.assert_not_called()
        self.assertEqual(self.storage_file.read_bytes(), contents_before)

    def test_clear_history_persists_and_keeps_target(self):
        target = self.chat_store.get_or_create_target("Clear Me", is_channel=False)
        other_target = self.chat_store.targets[0]
        for text in ("erste", "zweite"):
            self.chat_store.add_message(
                target.id, ChatMessage(sender="A", text=text, timestamp="12:00")
            )
        self.chat_store.add_message(
            other_target.id, ChatMessage(sender="B", text="bleibt", timestamp="12:01")
        )

        self.assertIsNone(self.chat_store.clear_history(target.id))
        self.assertEqual(self.chat_store.get_history(target.id), [])
        self.assertIn(target, self.chat_store.targets)
        self.assertEqual(len(self.chat_store.get_history(other_target.id)), 1)

        reloaded = ChatStore(storage_path=self.storage_file)
        self.assertEqual(reloaded.get_history(target.id), [])
        self.assertIn(target.id, [item.id for item in reloaded.targets])
        self.assertEqual(len(reloaded.get_history(other_target.id)), 1)

    def test_delete_conversation_removes_target_and_history_and_persists(self):
        target = self.chat_store.get_or_create_target("Delete Me", is_channel=False)
        other_target = self.chat_store.targets[0]
        self.chat_store.add_message(
            target.id, ChatMessage(sender="A", text="löschen", timestamp="12:00")
        )
        self.chat_store.add_message(
            other_target.id, ChatMessage(sender="B", text="bleibt", timestamp="12:01")
        )

        self.assertTrue(self.chat_store.delete_conversation(target.id))
        self.assertNotIn(target.id, [item.id for item in self.chat_store.targets])
        self.assertEqual(self.chat_store.get_history(target.id), [])
        self.assertEqual(len(self.chat_store.get_history(other_target.id)), 1)
        self.assertFalse(self.chat_store.delete_conversation(target.id))

        reloaded = ChatStore(storage_path=self.storage_file)
        self.assertNotIn(target.id, [item.id for item in reloaded.targets])
        self.assertEqual(reloaded.get_history(target.id), [])
        self.assertEqual(len(reloaded.get_history(other_target.id)), 1)

    def test_send_message_public_channel(self):
        target = self.chat_store.targets[0]
        ok, _ = self.chat_store.send_message(self.backend, target, "Hallo Public!")

        self.assertTrue(ok)
        self.assertEqual(self.backend.calls, [(["public", "Hallo Public!"], False)])
        history = self.chat_store.get_history(target.id)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].sender, "Ich")
        self.assertEqual(history[0].text, "Hallo Public!")
        self.assertEqual(history[0].status, "[Sent]")

    def test_send_message_numeric_channels(self):
        for number in (1, 7):
            with self.subTest(channel=number):
                target = self.chat_store.get_or_create_target(
                    f"Kanal {number}", is_channel=True, channel_num=number
                )
                text = f"Text {number}"
                ok, _ = self.chat_store.send_message(self.backend, target, text)
                self.assertTrue(ok)
                self.assertEqual(
                    self.backend.calls[-1], (["chan", str(number), text], False)
                )
                self.assertEqual(self.chat_store.get_history(target.id)[-1].status, "[Sent]")

    def test_send_message_named_channel_is_not_public(self):
        target = self.chat_store.get_or_create_target("Team Alpha", is_channel=True)
        self.assertIsNone(target.channel_num)

        ok, _ = self.chat_store.send_message(self.backend, target, "Hallo Team")
        self.assertTrue(ok)
        self.assertEqual(
            self.backend.calls, [(["chan", "Team Alpha", "Hallo Team"], False)]
        )
        self.assertEqual(self.chat_store.get_history(target.id)[0].status, "[Sent]")

    def test_send_message_rejects_invalid_channel_numbers(self):
        for number in (-1, 8):
            with self.subTest(channel=number):
                target = ChatTarget(
                    id=f"invalid_{number}",
                    name=f"Invalid {number}",
                    is_channel=True,
                    channel_num=number,
                )
                ok, _ = self.chat_store.send_message(self.backend, target, "Nicht senden")
                self.assertFalse(ok)
                self.assertEqual(
                    self.chat_store.get_history(target.id)[-1].status, "[Fehler]"
                )
        self.assertEqual(self.backend.calls, [])

    def test_send_message_direct_waits_for_ack_and_preserves_argv(self):
        target = self.chat_store.get_or_create_target("CF T-Deck", is_channel=False)
        ok, _ = self.chat_store.send_message(self.backend, target, "Hallo T-Deck!")

        self.assertTrue(ok)
        self.assertEqual(
            self.backend.calls,
            [(["msg", "-a", "CF T-Deck", "Hallo T-Deck!"], False)],
        )
        history = self.chat_store.get_history(target.id)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].text, "Hallo T-Deck!")
        self.assertEqual(history[0].status, "[ACK]")

    def test_send_message_failures_have_error_status(self):
        public = self.chat_store.targets[0]
        self.backend.respond(["public", "Fehler"], (False, "send error"))
        ok, _ = self.chat_store.send_message(self.backend, public, "Fehler")
        self.assertFalse(ok)
        self.assertEqual(self.chat_store.get_history(public.id)[0].status, "[Fehler]")

        dm = self.chat_store.get_or_create_target("NoAck", is_channel=False)
        args = ["msg", "-a", "NoAck", "Warten"]
        self.backend.respond(args, (False, "ACK timeout"))
        ok, _ = self.chat_store.send_message(self.backend, dm, "Warten")
        self.assertFalse(ok)
        self.assertEqual(self.chat_store.get_history(dm.id)[0].status, "[Fehler]")

    def test_send_message_rejects_empty_text_or_target_without_cli(self):
        valid = self.chat_store.targets[0]
        ok, _ = self.chat_store.send_message(self.backend, valid, "   ")
        self.assertFalse(ok)

        empty_targets = (
            ChatTarget("dm_empty", "  ", is_channel=False),
            ChatTarget("chan_empty", "", is_channel=True, channel_num=None),
        )
        for target in empty_targets:
            with self.subTest(target=target.id):
                ok, _ = self.chat_store.send_message(self.backend, target, "Text")
                self.assertFalse(ok)
                self.assertEqual(self.chat_store.get_history(target.id), [])

        self.assertEqual(self.backend.calls, [])

    def test_delete_numeric_channel_removes_local_target_and_history(self):
        target = self.chat_store.get_or_create_target(
            "Operations (7)", is_channel=True, channel_num=7
        )
        other_target = self.chat_store.targets[0]
        for text in ("erste", "zweite"):
            self.chat_store.add_message(
                target.id, ChatMessage(sender="A", text=text, timestamp="12:00")
            )
        self.chat_store.add_message(
            other_target.id, ChatMessage(sender="B", text="bleibt", timestamp="12:01")
        )
        self.backend.respond(["remove_channel", "7"], (True, "channel removed"))

        ok, response = self.chat_store.delete_channel(self.backend, target)

        self.assertTrue(ok)
        self.assertEqual(response, "channel removed")
        self.assertEqual(self.backend.calls, [(["remove_channel", "7"], False)])
        self.assertNotIn(target.id, [item.id for item in self.chat_store.targets])
        self.assertNotIn(target.id, self.chat_store.history)
        self.assertEqual(len(self.chat_store.get_history(other_target.id)), 1)

        reloaded = ChatStore(storage_path=self.storage_file)
        self.assertNotIn(target.id, [item.id for item in reloaded.targets])
        self.assertNotIn(target.id, reloaded.history)
        self.assertEqual(len(reloaded.get_history(other_target.id)), 1)

    def test_delete_named_channel_uses_exact_name(self):
        target = self.chat_store.get_or_create_target("Team Alpha", is_channel=True)
        self.chat_store.add_message(
            target.id, ChatMessage(sender="A", text="lokal", timestamp="12:00")
        )
        self.backend.respond(["remove_channel", "Team Alpha"], (True, "removed"))

        ok, response = self.chat_store.delete_channel(self.backend, target)

        self.assertTrue(ok)
        self.assertEqual(response, "removed")
        self.assertEqual(
            self.backend.calls, [(["remove_channel", "Team Alpha"], False)]
        )
        self.assertNotIn(target, self.chat_store.targets)
        self.assertNotIn(target.id, self.chat_store.history)

    def test_delete_channel_backend_failure_retains_everything(self):
        target = self.chat_store.targets[2]
        self.chat_store.add_message(
            target.id, ChatMessage(sender="A", text="lokal", timestamp="12:00")
        )
        targets_before = list(self.chat_store.targets)
        history_before = list(self.chat_store.get_history(target.id))
        contents_before = self.storage_file.read_bytes()
        self.backend.respond(["remove_channel", "2"], (False, "device busy"))

        with patch.object(self.chat_store, "save") as mock_save:
            ok, response = self.chat_store.delete_channel(self.backend, target)
            mock_save.assert_not_called()

        self.assertFalse(ok)
        self.assertEqual(response, "device busy")
        self.assertEqual(self.chat_store.targets, targets_before)
        self.assertEqual(self.chat_store.get_history(target.id), history_before)
        self.assertEqual(self.storage_file.read_bytes(), contents_before)

    def test_delete_channel_rejects_public_direct_and_invalid_targets(self):
        public = self.chat_store.targets[0]
        direct = self.chat_store.get_or_create_target("BaseStation-1", is_channel=False)
        invalid = ChatTarget("chan_8", "Invalid (8)", is_channel=True, channel_num=8)
        for target in (public, direct, invalid):
            self.chat_store.add_message(
                target.id,
                ChatMessage(sender="A", text=f"History {target.id}", timestamp="12:00"),
            )
        targets_before = list(self.chat_store.targets)
        history_before = {
            target.id: list(self.chat_store.get_history(target.id))
            for target in (public, direct, invalid)
        }

        for target in (public, direct, invalid):
            with self.subTest(target=target.id):
                ok, _ = self.chat_store.delete_channel(self.backend, target)
                self.assertFalse(ok)
                self.assertEqual(
                    self.chat_store.get_history(target.id), history_before[target.id]
                )

        self.assertEqual(self.backend.calls, [])
        self.assertEqual(self.chat_store.targets, targets_before)
        self.assertIn(public, self.chat_store.targets)
        self.assertIn(direct, self.chat_store.targets)

    def test_sync_text_uses_one_call_and_routes_channels_and_dms(self):
        response = (
            "Synchronized Messages (3 received):\n"
            " [12:01] [Public (0)] Base: Text\n"
            " [12:10] [Local-Team (2)] Sensor: Text\n"
            " [12:05] Base: Hello\n"
        )
        self.backend.respond(["sync_msgs"], (True, response))

        self.assertEqual(self.chat_store.sync_from_backend(self.backend), 3)
        self.assertEqual(self.backend.calls, [(["sync_msgs"], True)])

        public = self.chat_store.get_history("chan_0")
        self.assertEqual(len(public), 1)
        self.assertEqual(
            (public[0].timestamp, public[0].sender, public[0].text),
            ("12:01", "Base", "Text"),
        )

        team = self.chat_store.get_history("chan_2")
        self.assertEqual(len(team), 1)
        self.assertEqual((team[0].sender, team[0].text), ("Sensor", "Text"))

        direct = self.chat_store.get_history("dm_Base")
        self.assertEqual(len(direct), 1)
        self.assertEqual((direct[0].sender, direct[0].text), ("Base", "Hello"))
        self.assertNotIn("Hello", [message.text for message in public])

    def test_sync_original_json_and_legacy_fields(self):
        payload = [
            {
                "type": "CHAN",
                "channel_idx": 2,
                "text": "Original channel",
                "sender_timestamp": "12:20",
            },
            {
                "type": "PRIV",
                "pubkey_prefix": "abc123def456",
                "sender": "Unknown",
                "text": "Original private",
                "sender_timestamp": "12:21",
            },
            {
                "channel": 0,
                "sender": "LegacyBase",
                "text": "Legacy public",
                "time": "12:22",
            },
            {
                "sender": "Legacy DM",
                "text": "Legacy private",
                "time": "12:23",
            },
        ]
        self.backend.respond(["sync_msgs"], (True, json.dumps(payload)))

        self.assertEqual(self.chat_store.sync_from_backend(self.backend), 4)
        self.assertEqual(self.backend.calls, [(["sync_msgs"], True)])
        self.assertEqual(self.chat_store.get_history("chan_2")[0].text, "Original channel")

        prefix_history = self.chat_store.get_history("dm_abc123def456")
        self.assertEqual(len(prefix_history), 1)
        self.assertEqual(prefix_history[0].sender, "abc123def456")
        self.assertNotEqual(prefix_history[0].sender, "Unknown")

        public = self.chat_store.get_history("chan_0")
        self.assertEqual([(m.sender, m.text) for m in public], [("LegacyBase", "Legacy public")])
        direct = self.chat_store.get_history("dm_Legacy DM")
        self.assertEqual([(m.sender, m.text) for m in direct], [("Legacy DM", "Legacy private")])
        self.assertNotIn("Legacy private", [message.text for message in public])

    def test_sync_preserves_distinct_real_data_payloads(self):
        payload = [
            {
                "type": "DATA",
                "channel_idx": 0,
                "data_type": 1,
                "data_len": 2,
                "payload": "0102",
                "sender_timestamp": 1234,
            },
            {
                "type": "DATA",
                "channel_idx": 0,
                "data_type": 1,
                "data_len": 2,
                "payload": "0304",
                "sender_timestamp": 1234,
            },
        ]
        self.backend.respond(["sync_msgs"], (True, json.dumps(payload)))

        self.assertEqual(self.chat_store.sync_from_backend(self.backend), 2)
        history = self.chat_store.get_history("chan_0")
        self.assertEqual(
            [message.text for message in history],
            ["[DATA 1] 0102", "[DATA 1] 0304"],
        )

    def test_malformed_json_does_not_trigger_second_destructive_sync(self):
        valid_second_response = json.dumps(
            [{"type": "PRIV", "pubkey_prefix": "abc123", "text": "Consumed"}]
        )
        self.backend.respond(
            ["sync_msgs"],
            (True, '[{"type": "PRIV", broken]'),
            (True, valid_second_response),
        )

        with self.assertRaisesRegex(RuntimeError, "nicht ausgewertet"):
            self.chat_store.sync_from_backend(self.backend)
        self.assertEqual(self.backend.calls, [(["sync_msgs"], True)])
        self.assertEqual(self.chat_store.get_history("dm_abc123"), [])

    def test_sync_salvages_complete_messages_before_trailing_comma(self):
        response = '[{"type":"PRIV","pubkey_prefix":"abc","text":"Gerettet"},\n]'
        self.backend.respond(["sync_msgs"], (True, response))

        with self.assertRaisesRegex(RuntimeError, "beschädigt"):
            self.chat_store.sync_from_backend(self.backend)
        self.assertEqual(self.chat_store.get_history("dm_abc")[0].text, "Gerettet")
        self.assertEqual(self.backend.calls, [(["sync_msgs"], True)])

    def test_sync_failure_still_saves_valid_consumed_payload(self):
        response = json.dumps([
            {"type": "PRIV", "pubkey_prefix": "def", "text": "Trotz Fehler sichern"}
        ])
        self.backend.respond(["sync_msgs"], (False, response))

        with self.assertRaisesRegex(RuntimeError, "def"):
            self.chat_store.sync_from_backend(self.backend)
        history = self.chat_store.get_history("dm_def")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].text, "Trotz Fehler sichern")
        self.assertEqual(self.backend.calls, [(["sync_msgs"], True)])

    def test_sync_deduplicates_messages_from_later_calls(self):
        response = "[12:05] Base: Hello"
        self.backend.respond(["sync_msgs"], (True, response))

        self.assertEqual(self.chat_store.sync_from_backend(self.backend), 1)
        self.assertEqual(self.chat_store.sync_from_backend(self.backend), 0)
        self.assertEqual(len(self.backend.calls), 2)
        self.assertEqual(len(self.chat_store.get_history("dm_Base")), 1)

    def test_populate_targets_supports_mock_and_real_text(self):
        channels = (
            "Configured Channels:\n"
            " [CH 1] Name: Ops One | Key: mock-key\n"
            "0: Public [default-key]\n"
            "3: Field Ops [0123456789abcdef]\n"
        )
        contacts = "\n".join(
            [
                "Contacts List (4 contacts in device):",
                " • Mock Kontakt [Companion] RSSI: -80",
                f"{'Base Station':30} \x1b[34G CLI  a1b2c3d4e5f6   2m 0 hop",
                f"{'CF T-Deck':30} \x1b[34G REP  c7f0d1e2c3d4   3m Flood",
                "> 4 from 4 contacts in device",
            ]
        )
        self.backend.respond(["get_channels"], (True, channels))
        self.backend.respond(["contacts"], (True, contacts))

        self.chat_store.populate_targets_from_backend(self.backend)

        self.assertEqual(self.backend.calls, [(["get_channels"], False), (["contacts"], False)])
        channel_3 = next(t for t in self.chat_store.targets if t.id == "chan_3")
        self.assertEqual(channel_3.name, "Field Ops (3)")
        self.assertEqual(channel_3.channel_num, 3)
        self.assertEqual(len([t for t in self.chat_store.targets if t.id == "chan_0"]), 1)
        channel_1 = next(t for t in self.chat_store.targets if t.id == "chan_1")
        self.assertEqual(channel_1.name, "Ops One (1)")

        dm_names = {t.name for t in self.chat_store.targets if not t.is_channel}
        self.assertEqual(dm_names, {"Mock Kontakt", "Base Station", "CF T-Deck"})
        self.assertNotIn("> 4 from 4 contacts in device", dm_names)

    def test_populate_targets_supports_json_when_available(self):
        channels = json.dumps(
            [{"channel_idx": 4, "channel_name": "JSON Team", "channel_secret": "ab"}]
        )
        contacts = json.dumps(
            {
                "a1b2c3": {"adv_name": "JSON Contact", "type": 1},
            }
        )
        self.backend.respond(["get_channels"], (True, channels))
        self.backend.respond(["contacts"], (True, contacts))

        self.chat_store.populate_targets_from_backend(self.backend)

        self.assertIn("chan_4", [target.id for target in self.chat_store.targets])
        self.assertIn("dm_JSON Contact", [target.id for target in self.chat_store.targets])

    def test_sync_resolves_known_private_sender_by_public_key(self):
        full_key = "c7f0d1e2c3d4" + "01" * 26
        self.backend.respond(["get_channels"], (True, "[]"))
        self.backend.respond(
            ["contacts"],
            (True, json.dumps({full_key: {"adv_name": "CF T-Deck", "type": 1}})),
        )
        self.chat_store.populate_targets_from_backend(self.backend)
        payload = [{
            "type": "PRIV",
            "pubkey_prefix": full_key[:12],
            "text": "Hallo vom bekannten Kontakt",
            "sender_timestamp": 1760000000,
        }]
        self.backend.respond(["sync_msgs"], (True, json.dumps(payload)))

        self.assertEqual(self.chat_store.sync_from_backend(self.backend), 1)
        history = self.chat_store.get_history("dm_CF T-Deck")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].sender, "CF T-Deck")
        self.assertEqual(self.chat_store.get_history(f"dm_{full_key[:12]}"), [])

    def test_sync_failure_is_not_reported_as_empty_success(self):
        self.backend.respond(["sync_msgs"], (False, "USB timeout"))
        with self.assertRaisesRegex(RuntimeError, "USB timeout"):
            self.chat_store.sync_from_backend(self.backend)
        self.assertEqual(self.backend.calls, [(["sync_msgs"], True)])

    def test_json_dedup_preserves_same_message_on_different_days(self):
        first_time = datetime(2026, 1, 1, 12, 0, 0)
        second_time = datetime(2026, 1, 2, 12, 0, 0)
        payload = [
            {
                "type": "PRIV",
                "pubkey_prefix": "abc123def456",
                "text": "Taeglicher Status",
                "sender_timestamp": first_time.timestamp(),
            },
            {
                "type": "PRIV",
                "pubkey_prefix": "abc123def456",
                "text": "Taeglicher Status",
                "sender_timestamp": second_time.timestamp(),
            },
        ]
        self.backend.respond(["sync_msgs"], (True, json.dumps(payload)))

        self.assertEqual(self.chat_store.sync_from_backend(self.backend), 2)
        history = self.chat_store.get_history("dm_abc123def456")
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0].timestamp, history[1].timestamp)
        self.assertNotEqual(history[0].dedup_key, history[1].dedup_key)

    def test_identical_outgoing_sends_are_not_deduplicated(self):
        target = self.chat_store.targets[0]
        message = ChatMessage("Ich", "Wiederholung", "12:00:00", True, "[Sent]")
        self.chat_store.add_message(target.id, message)
        self.chat_store.add_message(
            target.id, ChatMessage("Ich", "Wiederholung", "12:00:00", True, "[Sent]")
        )
        self.assertEqual(len(self.chat_store.get_history(target.id)), 2)

    def test_load_does_not_erase_history_before_third_instance(self):
        target = self.chat_store.get_or_create_target("PersistTest", is_channel=False)
        self.chat_store.add_message(
            target.id,
            ChatMessage(
                sender="Ich",
                text="Gespeicherte Nachricht",
                timestamp="14:00",
                is_outgoing=True,
            ),
        )

        # The old implementation rewrote the file with empty history while this
        # second instance restored its custom target. A third instance then lost it.
        second_store = ChatStore(storage_path=self.storage_file)
        self.assertEqual(len(second_store.get_history(target.id)), 1)

        third_store = ChatStore(storage_path=self.storage_file)
        history = third_store.get_history(target.id)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].text, "Gespeicherte Nachricht")
        with open(self.storage_file, "r", encoding="utf-8") as f:
            saved = json.load(f)
        self.assertEqual(len(saved["history"][target.id]), 1)


if __name__ == "__main__":
    unittest.main()
