"""Unit tests for ContactStore and heard node management."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.backend.contact_store import ContactStore, NodeItem
from src.backend.executor import MeshCoreBackend
from src.config import Config


class TestContactStore(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.storage_file = Path(self.tmp_dir.name) / "test_heard.json"
        self.store = ContactStore(storage_path=self.storage_file)

        self.config = Config(config_file=None)
        self.config.simulation_mode = True
        self.backend = MeshCoreBackend(self.config)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_fetch_saved_contacts(self):
        contacts = self.store.fetch_saved_contacts(self.backend)
        self.assertTrue(len(contacts) >= 4)
        names = [c.name for c in contacts]
        self.assertIn("BaseStation-1", names)
        self.assertIn("Mobile-Bravo", names)

    def test_fetch_heard_nodes(self):
        heard = self.store.fetch_heard_nodes(self.backend)
        self.assertTrue(len(heard) >= 4)
        names = [h.name for h in heard]
        self.assertIn("Delta-Repeater-9", names)
        self.assertIn("Sensor-Forest-12", names)

    def test_save_heard_node_to_contacts(self):
        heard = self.store.fetch_heard_nodes(self.backend)
        self.assertTrue(len(heard) > 0)
        target_node = heard[0]
        initial_heard_count = len(self.store.cached_heard)
        initial_saved_count = len(self.store.cached_contacts)

        # Save to contacts
        ok, msg = self.store.save_heard_node_to_contacts(
            self.backend,
            target_node,
            custom_name="Mein-Delta-Repeater",
        )
        self.assertTrue(ok)
        self.assertIn("erfolgreich", msg)

        # Verify it was added to contacts
        saved_names = [c.name for c in self.store.cached_contacts]
        self.assertIn("Mein-Delta-Repeater", saved_names)

        # Verify it was removed from heard list
        heard_names = [h.name for h in self.store.cached_heard]
        self.assertNotIn(target_node.name, heard_names)
        self.assertEqual(len(self.store.cached_heard), initial_heard_count - 1)

    def test_delete_saved_contact(self):
        contacts = self.store.fetch_saved_contacts(self.backend)
        self.assertTrue(len(contacts) > 0)
        to_delete = contacts[0].name

        ok, msg = self.store.delete_saved_contact(self.backend, to_delete)
        self.assertTrue(ok)
        new_names = [c.name for c in self.store.cached_contacts]
        self.assertNotIn(to_delete, new_names)

    def test_flush_heard_nodes(self):
        self.store.fetch_heard_nodes(self.backend)
        self.assertTrue(len(self.store.cached_heard) > 0)

        ok, msg = self.store.flush_heard_nodes(self.backend)
        self.assertTrue(ok)
        self.assertEqual(len(self.store.cached_heard), 0)


if __name__ == "__main__":
    unittest.main()
