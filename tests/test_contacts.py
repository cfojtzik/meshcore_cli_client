"""Unit tests for ContactStore and heard node management."""

import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.backend.contact_store import ContactStore, NodeItem
from src.backend.executor import MeshCoreBackend
from src.config import Config


class ScriptedBackend:
    """Small run_cli replacement with ordered responses and call recording."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def run_cli(self, args, json_mode=False, timeout=None):
        self.calls.append((list(args), json_mode))
        if not self.responses:
            return False, "No scripted response"
        return self.responses.pop(0)


def contact_record(name, key, type_id, **extra):
    record = {
        "public_key": key,
        "type": type_id,
        "flags": 0,
        "out_path_len": -1,
        "out_path": "",
        "out_path_hash_mode": 0,
        "adv_name": name,
        "last_advert": 1762432800,
        "adv_lat": 0,
        "adv_lon": 0,
        "lastmod": 1762432801,
    }
    record.update(extra)
    return record


def keyed_output(*records):
    return json.dumps({record["public_key"][:12]: record for record in records}, indent=4)


def ansi_contact_row(name, type_name, key, age, path):
    """The exact default columns/cursor positioning used by meshcore-cli 1.6.9."""
    return (
        f"{name:30} \x1b[34G {type_name:4} {key:12} "
        f"{age:>4} {path:12}"
    )


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
        names = [contact.name for contact in contacts]
        self.assertIn("BaseStation-1", names)
        self.assertIn("Mobile-Bravo", names)
        self.assertEqual(
            {contact.name: contact.type_id for contact in contacts}["Sensor-Weather"],
            4,
        )

    def test_real_contacts_json_dict_preserves_keys_types_and_paths(self):
        companion_key = "11" * 32
        repeater_key = "22" * 32
        room_key = "33" * 32
        sensor_key = "44" * 32
        output = keyed_output(
            contact_record("CF T-Deck", companion_key, 1),
            contact_record(
                "Repeater North",
                repeater_key,
                2,
                out_path_len=2,
                out_path="a1b2c3",
                snr=6.5,
                rssi=-78,
            ),
            contact_record("Club Room", room_key, 3, out_path_len=0),
            contact_record("Garden Sensor", sensor_key, 4),
        )
        backend = ScriptedBackend((True, output))

        contacts = self.store.fetch_saved_contacts(backend)

        self.assertEqual(backend.calls, [(["contacts"], True)])
        self.assertEqual(len(contacts), 4)
        by_name = {contact.name: contact for contact in contacts}
        self.assertEqual(by_name["CF T-Deck"].key, companion_key)
        self.assertEqual(by_name["CF T-Deck"].type_name, "Companion")
        self.assertEqual(by_name["CF T-Deck"].type_id, 1)
        self.assertEqual(by_name["Repeater North"].key, repeater_key)
        self.assertEqual(by_name["Repeater North"].type_name, "Repeater")
        self.assertEqual(by_name["Repeater North"].type_id, 2)
        self.assertEqual(by_name["Repeater North"].path, "a1,b2")
        self.assertEqual(by_name["Repeater North"].hops, 2)
        self.assertEqual(by_name["Repeater North"].snr, "6.5")
        self.assertEqual(by_name["Repeater North"].rssi, "-78")
        self.assertEqual(by_name["Club Room"].type_name, "Room")
        self.assertEqual(by_name["Club Room"].type_id, 3)
        self.assertEqual(by_name["Club Room"].path, "0 hop")
        self.assertEqual(by_name["Club Room"].hops, 0)
        self.assertEqual(by_name["Garden Sensor"].type_name, "Sensor")
        self.assertEqual(by_name["Garden Sensor"].type_id, 4)
        self.assertEqual(by_name["Garden Sensor"].path, "Flood")

    def test_real_contacts_json_list_is_supported(self):
        key = "ab" * 32
        output = json.dumps([contact_record("Filtered CLI", key, 1)])
        backend = ScriptedBackend((True, output))

        contacts = self.store.fetch_saved_contacts(backend)

        self.assertEqual(len(contacts), 1)
        self.assertEqual(contacts[0].name, "Filtered CLI")
        self.assertEqual(contacts[0].key, key)
        self.assertEqual(contacts[0].type_id, 1)

    def test_ansi_fixed_columns_and_contact_summary(self):
        output = "\n".join(
            [
                ansi_contact_row("CF T-Deck", "CLI", "c7f0d1e2c3d4", "5m", "0 hop"),
                ansi_contact_row("Relay With Spaces", "REP", "a1b2c3d4e5f6", "2h", "aa,bb"),
                ansi_contact_row("Club Room", "ROOM", "b2c3d4e5f6a1", "1d", "Flood"),
                ansi_contact_row("Weather", "SENS", "c3d4e5f6a1b2", "30s", "0 hop"),
                "> 4 from 9 contacts in device",
            ]
        )
        backend = ScriptedBackend((True, output))

        contacts = self.store.fetch_saved_contacts(backend)

        self.assertEqual(len(contacts), 4)
        self.assertNotIn("> 4 from 9 contacts in device", [c.name for c in contacts])
        by_name = {contact.name: contact for contact in contacts}
        self.assertEqual(by_name["CF T-Deck"].key, "c7f0d1e2c3d4")
        self.assertEqual(by_name["CF T-Deck"].type_id, 1)
        self.assertEqual(by_name["CF T-Deck"].last_seen, "5m")
        self.assertEqual(by_name["CF T-Deck"].path, "0 hop")
        self.assertEqual(by_name["CF T-Deck"].hops, 0)
        self.assertEqual(by_name["Relay With Spaces"].type_name, "Repeater")
        self.assertEqual(by_name["Relay With Spaces"].type_id, 2)
        self.assertEqual(by_name["Relay With Spaces"].path, "aa,bb")
        self.assertEqual(by_name["Relay With Spaces"].hops, 2)
        self.assertEqual(by_name["Club Room"].type_id, 3)
        self.assertEqual(by_name["Weather"].type_id, 4)

    def test_fetch_heard_nodes(self):
        heard = self.store.fetch_heard_nodes(self.backend)
        self.assertTrue(len(heard) >= 4)
        by_name = {node.name: node for node in heard}
        self.assertIn("Delta-Repeater-9", by_name)
        self.assertIn("Sensor-Forest-12", by_name)
        self.assertEqual(by_name["Delta-Repeater-9"].type_id, 2)
        self.assertEqual(by_name["Delta-Repeater-9"].last_seen, "vor 30s")
        self.assertEqual(by_name["Sensor-Forest-12"].type_id, 4)
        self.assertEqual(by_name["Sensor-Forest-12"].last_seen, "vor 1m")

    def test_real_pending_json_preserves_type_and_timestamp(self):
        key = "55" * 32
        timestamp = 1762432800
        output = keyed_output(
            contact_record(
                "Pending Room",
                key,
                3,
                last_advert=timestamp,
                snr=4.25,
                rssi=-82,
                out_path_len=1,
                out_path="a1",
            )
        )
        backend = ScriptedBackend((True, output))

        heard = self.store.fetch_heard_nodes(backend)

        self.assertEqual(backend.calls, [(["pending_contacts"], True)])
        self.assertEqual(len(heard), 1)
        self.assertEqual(heard[0].name, "Pending Room")
        self.assertEqual(heard[0].key, key)
        self.assertEqual(heard[0].type_id, 3)
        self.assertEqual(heard[0].type_name, "Room")
        self.assertEqual(heard[0].snr, "4.25")
        self.assertEqual(heard[0].rssi, "-82")
        self.assertEqual(heard[0].path, "a1")
        self.assertEqual(heard[0].hops, 1)
        self.assertEqual(
            heard[0].last_seen,
            datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S"),
        )

    def test_pending_plain_text_keeps_full_public_key(self):
        key = "66" * 32
        backend = ScriptedBackend((True, f"Pending:CLI: {key}"))

        heard = self.store.fetch_heard_nodes(backend)

        self.assertEqual(len(heard), 1)
        self.assertEqual(heard[0].name, "Pending:CLI")
        self.assertEqual(heard[0].key, key)
        self.assertEqual(heard[0].last_seen, "n/a")

    def test_adverts_include_auto_saved_and_unknown_nodes(self):
        saved_key = "aa" * 32
        unknown_key = "bb" * 32
        self.store.cached_contacts = [
            NodeItem(
                name="Auto Saved",
                key=saved_key,
                type_id=2,
                type_name="Repeater",
                is_saved=True,
            )
        ]
        backend = ScriptedBackend((True, "{}"))
        backend.get_heard_adverts = lambda: [
            {"public_key": saved_key, "last_heard": 1762432800},
            {"public_key": unknown_key, "last_heard": 1762432801},
        ]

        heard = self.store.fetch_heard_nodes(backend)

        by_name = {node.name: node for node in heard}
        self.assertIn("Auto Saved", by_name)
        self.assertTrue(by_name["Auto Saved"].is_saved)
        self.assertIn(unknown_key[:12], by_name)
        self.assertFalse(by_name[unknown_key[:12]].is_saved)

    def test_deleted_contact_heard_again_is_no_longer_marked_saved(self):
        key = "cc" * 32
        self.store.cached_heard = [
            NodeItem(name="Was Saved", key=key, is_saved=True)
        ]
        self.store.cached_contacts = [NodeItem(name="Other", key="dd" * 32, is_saved=True)]
        backend = ScriptedBackend((True, "{}"))

        heard = self.store.fetch_heard_nodes(backend)

        self.assertEqual([node.name for node in heard], ["Was Saved"])
        self.assertFalse(heard[0].is_saved)

    def test_advert_placeholder_keeps_known_name_and_invalid_advert_api(self):
        key = "ee" * 32
        self.store.cached_heard = [
            NodeItem(name="Known Relay", key=key, type_id=2, type_name="Repeater")
        ]
        backend = ScriptedBackend((True, "{}"))
        backend.get_heard_adverts = lambda: [{"public_key": key, "last_heard": 1762432800}]

        heard = self.store.fetch_heard_nodes(backend)
        self.assertEqual(heard[0].name, "Known Relay")
        self.assertEqual(heard[0].type_id, 2)

        broken = ScriptedBackend((True, "{}"))
        broken.get_heard_adverts = lambda: object()
        self.assertEqual(self.store.fetch_heard_nodes(broken)[0].name, "Known Relay")

    def test_discover_runs_before_pending_fetch(self):
        key = "77" * 32
        discovered = json.dumps([{"pubkey": "88" * 32, "node_type": 2}])
        pending = keyed_output(contact_record("Discovered Pending", key, 2))
        backend = ScriptedBackend((True, discovered), (True, pending))

        heard = self.store.fetch_heard_nodes(backend, discover=True)

        self.assertEqual(
            backend.calls,
            [(["node_discover"], True), (["pending_contacts"], True)],
        )
        self.assertEqual(
            [node.name for node in heard],
            [("88" * 32)[:12], "Discovered Pending"],
        )
        self.assertEqual([node.type_id for node in heard], [2, 2])

    def test_dismiss_heard_node_survives_refresh_and_reload(self):
        key = "99" * 32
        pending = keyed_output(contact_record("Dismiss Me", key, 2))
        backend = ScriptedBackend((True, pending), (True, pending))
        heard = self.store.fetch_heard_nodes(backend)
        target = heard[0]

        self.store.dismiss_heard_node(target)

        self.assertEqual(self.store.cached_heard, [])
        stored = json.loads(self.storage_file.read_text(encoding="utf-8"))
        self.assertEqual(stored["nodes"], [])
        self.assertEqual(stored["dismissed"], [f"key:{key}"])

        reloaded = ContactStore(storage_path=self.storage_file)
        refreshed = reloaded.fetch_heard_nodes(backend)
        self.assertEqual(refreshed, [])

    def test_dismiss_heard_node_uses_name_without_key(self):
        target = NodeItem(name="Name Only", key="")
        self.store.cached_heard = [target]

        self.store.dismiss_heard_node(target)

        stored = json.loads(self.storage_file.read_text(encoding="utf-8"))
        self.assertEqual(stored["dismissed"], ["name:name only"])
        reloaded = ContactStore(storage_path=self.storage_file)
        self.assertEqual(reloaded.cached_heard, [])
        self.assertIn("name:name only", reloaded.dismissed_heard)

    def test_legacy_heard_list_file_is_loaded_and_migrated(self):
        legacy_file = Path(self.tmp_dir.name) / "legacy.json"
        legacy_file.write_text(
            json.dumps([NodeItem(name="Legacy", type_id=3, type_name="Room").to_dict()]),
            encoding="utf-8",
        )

        store = ContactStore(storage_path=legacy_file)
        self.assertEqual(len(store.cached_heard), 1)
        self.assertEqual(store.cached_heard[0].type_id, 3)
        store.save_heard_cache()
        stored = json.loads(legacy_file.read_text(encoding="utf-8"))
        self.assertEqual(stored["dismissed"], [])
        self.assertEqual(stored["nodes"][0]["name"], "Legacy")

    def test_save_heard_node_to_contacts(self):
        heard = self.store.fetch_heard_nodes(self.backend)
        self.assertTrue(len(heard) > 0)
        target_node = heard[0]
        initial_heard_count = len(self.store.cached_heard)

        ok, msg = self.store.save_heard_node_to_contacts(
            self.backend,
            target_node,
            custom_name="Mein-Delta-Repeater",
        )
        self.assertTrue(ok)
        self.assertIn("erfolgreich", msg)

        saved_names = [contact.name for contact in self.store.cached_contacts]
        self.assertIn("Mein-Delta-Repeater", saved_names)
        heard_names = [node.name for node in self.store.cached_heard]
        self.assertNotIn(target_node.name, heard_names)
        self.assertEqual(len(self.store.cached_heard), initial_heard_count - 1)

    def test_save_heard_node_uses_actual_type_id(self):
        key = "aa" * 32
        pending = keyed_output(contact_record("Room To Save", key, 3))
        saved = keyed_output(contact_record("Room To Save", key, 3))
        backend = ScriptedBackend((True, pending), (True, "added"), (True, saved))
        target = self.store.fetch_heard_nodes(backend)[0]

        ok, _ = self.store.save_heard_node_to_contacts(backend, target)

        self.assertTrue(ok)
        self.assertEqual(
            backend.calls[1],
            (["add_contact", key, "3", "Room To Save"], False),
        )
        self.assertEqual(self.store.cached_contacts[0].type_id, 3)

    def test_delete_saved_contact(self):
        contacts = self.store.fetch_saved_contacts(self.backend)
        self.assertTrue(len(contacts) > 0)
        to_delete = contacts[0].name

        ok, msg = self.store.delete_saved_contact(self.backend, to_delete)
        self.assertTrue(ok)
        new_names = [contact.name for contact in self.store.cached_contacts]
        self.assertNotIn(to_delete, new_names)

    def test_delete_contact_with_spaces_and_key(self):
        ok, msg = self.store.delete_saved_contact(
            self.backend,
            "CF T-Deck",
            key="c7f0d1e2c3d40101",
        )
        self.assertTrue(ok)
        new_names = [contact.name for contact in self.store.cached_contacts]
        self.assertNotIn("CF T-Deck", new_names)

    def test_delete_uses_loaded_key_after_any_name_failure(self):
        key = "c7" + "f0" * 31
        contacts = keyed_output(contact_record("CF T-Deck", key, 1))
        backend = ScriptedBackend(
            (True, contacts),
            (False, "name quoting rejected"),
            (True, "removed by key"),
            (True, "{}"),
        )
        loaded = self.store.fetch_saved_contacts(backend)[0]
        self.assertEqual(loaded.key, key)

        ok, _ = self.store.delete_saved_contact(backend, loaded.name, key=loaded.key)

        self.assertTrue(ok)
        self.assertEqual(backend.calls[1], (["remove_contact", "CF T-Deck"], False))
        self.assertEqual(backend.calls[2], (["remove_contact", key[:12]], False))
        self.assertEqual(self.store.cached_contacts, [])

    def test_delete_returns_fallback_failure(self):
        backend = ScriptedBackend(
            (False, "name rejected"),
            (False, "key rejected"),
        )

        ok, message = self.store.delete_saved_contact(
            backend, "Odd Name", key="a1b2c3d4e5f6"
        )

        self.assertFalse(ok)
        self.assertIn("key rejected", message)
        self.assertEqual(len(backend.calls), 2)

    def test_flush_heard_nodes(self):
        self.store.fetch_heard_nodes(self.backend)
        self.assertTrue(len(self.store.cached_heard) > 0)

        ok, msg = self.store.flush_heard_nodes(self.backend)
        self.assertTrue(ok)
        self.assertEqual(len(self.store.cached_heard), 0)

    def test_flush_failure_keeps_cache_and_disk_state(self):
        self.store.cached_heard = [NodeItem(name="Keep Me", key="bb" * 32)]
        self.store.dismissed_heard = {"name:old dismissal"}
        self.store.save_heard_cache()
        before = self.storage_file.read_bytes()
        backend = ScriptedBackend((False, "radio busy"))

        ok, message = self.store.flush_heard_nodes(backend)

        self.assertFalse(ok)
        self.assertIn("radio busy", message)
        self.assertEqual([node.name for node in self.store.cached_heard], ["Keep Me"])
        self.assertEqual(self.store.dismissed_heard, {"name:old dismissal"})
        self.assertEqual(self.storage_file.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
