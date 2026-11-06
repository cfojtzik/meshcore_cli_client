"""Unit tests for ChatStore and chat message handling."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.backend.chat_store import ChatMessage, ChatStore, ChatTarget
from src.backend.executor import MeshCoreBackend
from src.config import Config


class TestChatStore(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.storage_file = Path(self.tmp_dir.name) / "test_chat.json"
        self.chat_store = ChatStore(storage_path=self.storage_file)

        self.config = Config(config_file=None)
        self.config.simulation_mode = True
        self.backend = MeshCoreBackend(self.config)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_default_targets(self):
        self.assertTrue(len(self.chat_store.targets) >= 3)
        tags = [t.display_tag for t in self.chat_store.targets]
        self.assertIn("#Public (0)", tags)

    def test_get_or_create_target(self):
        target = self.chat_store.get_or_create_target("Mobile-Bravo", is_channel=False)
        self.assertEqual(target.name, "Mobile-Bravo")
        self.assertFalse(target.is_channel)
        self.assertEqual(target.display_tag, "@Mobile-Bravo")

        # Creating again should return the same target
        target2 = self.chat_store.get_or_create_target("Mobile-Bravo", is_channel=False)
        self.assertEqual(target.id, target2.id)

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

    def test_send_message_channel(self):
        target = self.chat_store.targets[0]  # Public (0)
        ok, res = self.chat_store.send_message(self.backend, target, "Hallo Public!")
        self.assertTrue(ok)
        history = self.chat_store.get_history(target.id)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].sender, "Ich")
        self.assertEqual(history[0].text, "Hallo Public!")
        self.assertEqual(history[0].status, "[ACK]")

    def test_send_message_direct(self):
        target = self.chat_store.get_or_create_target("BaseStation-1", is_channel=False)
        ok, res = self.chat_store.send_message(self.backend, target, "DM Testnachricht")
        self.assertTrue(ok)
        history = self.chat_store.get_history(target.id)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].sender, "Ich")
        self.assertEqual(history[0].text, "DM Testnachricht")

    def test_sync_from_backend(self):
        new_msgs = self.chat_store.sync_from_backend(self.backend)
        self.assertTrue(new_msgs > 0)
        # Verify messages routed to targets
        target = self.chat_store.targets[0]
        history = self.chat_store.get_history(target.id)
        self.assertTrue(len(history) > 0)

    def test_persistence_save_and_load(self):
        target = self.chat_store.get_or_create_target("PersistTest", is_channel=False)
        msg = ChatMessage(sender="Ich", text="Gespeicherte Nachricht", timestamp="14:00", is_outgoing=True)
        self.chat_store.add_message(target.id, msg)

        # Create new store from same file
        new_store = ChatStore(storage_path=self.storage_file)
        history = new_store.get_history(target.id)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].text, "Gespeicherte Nachricht")


if __name__ == "__main__":
    unittest.main()
