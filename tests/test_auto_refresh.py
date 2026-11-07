"""Hardware-free tests for contact auto-refresh and interval selection."""

import curses
import sys
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.backend.contact_store import NodeItem
from src.ui.async_task import AsyncResult
from src.ui.views.connection import run_connection_view
from src.ui.views.contacts import (
    AUTO_DISCOVERY,
    AUTO_REFRESH,
    discovery_interval,
    next_auto_action,
    run_contacts_view,
    stable_selection_index,
)


class FakeWindow:
    """Small curses-window double with input polling and bounds checks."""

    def __init__(self, height=20, width=120, keys=None):
        self.height = height
        self.width = width
        self.keys = list(keys or [])
        self.writes = []
        self.timeouts = []

    def getmaxyx(self):
        return self.height, self.width

    def get_wch(self):
        if not self.keys:
            raise curses.error("no input")
        return self.keys.pop(0)

    def addstr(self, y, x, text, attr=0):
        if not (0 <= y < self.height and 0 <= x < self.width):
            raise AssertionError(f"write outside fake window: {(y, x)}")
        self.writes.append((y, x, text, attr))

    def refresh(self):
        pass

    def clear(self):
        pass

    def timeout(self, milliseconds):
        self.timeouts.append(milliseconds)


class InlineTask:
    """Deterministic BackgroundTask double; one operation is never overlapped."""

    def __init__(self):
        self.busy = False
        self.result = None
        self.closed = False

    def start(self, func):
        if self.busy or self.closed:
            return False
        self.busy = True
        try:
            self.result = AsyncResult(True, func())
        except Exception as exc:  # Match BackgroundTask's error transport.
            self.result = AsyncResult(False, exc)
        return True

    def poll(self):
        if not self.busy:
            return None
        self.busy = False
        result, self.result = self.result, None
        return result

    def close(self):
        self.closed = True
        self.busy = False
        self.result = None


def immediate_progress(stdscr, task, title, func):
    """Complete initial/manual I/O synchronously and emulate its timeout reset."""
    stdscr.timeout(-1)
    try:
        return AsyncResult(True, func())
    except Exception as exc:
        return AsyncResult(False, exc)


class FakeContactStore:
    def __init__(self, auto_error=None, auto_delay=0):
        self.cached_heard = [NodeItem(name="Relay", key="relay-key")]
        self.cached_contacts = []
        self.discover_calls = []
        self.saved_calls = 0
        self.auto_error = auto_error
        self.auto_delay = auto_delay
        self.auto_completed = threading.Event()
        self.auto_save = None
        self.auto_save_reads = 0
        self.auto_save_writes = []

    def fetch_auto_save(self, backend):
        self.auto_save_reads += 1
        self.auto_save = True
        return self.auto_save

    def set_auto_save(self, backend, enabled):
        self.auto_save_writes.append(enabled)
        self.auto_save = enabled
        return True, "ok"

    def fetch_saved_contacts(self, backend):
        self.saved_calls += 1
        return self.cached_contacts

    def fetch_heard_nodes(self, backend, discover=False):
        self.discover_calls.append(discover)
        if not discover:
            try:
                if self.auto_delay:
                    time.sleep(self.auto_delay)
                if self.auto_error is not None:
                    raise self.auto_error
            finally:
                self.auto_completed.set()
        return self.cached_heard


class PersistentConfig(SimpleNamespace):
    """Config double whose refresh property records every persistent write."""

    def __init__(self):
        super().__init__(port="/dev/test", baudrate=115200, simulation_mode=True)
        self._refresh_interval = 5
        self.saved_intervals = []

    @property
    def refresh_interval(self):
        return self._refresh_interval

    @refresh_interval.setter
    def refresh_interval(self, value):
        self._refresh_interval = value
        self.saved_intervals.append(value)


class AutoRefreshSchedulerTests(unittest.TestCase):
    def test_discovery_uses_thirty_second_floor_then_six_refresh_intervals(self):
        self.assertEqual(discovery_interval(1), 30)
        self.assertEqual(discovery_interval(5), 30)
        self.assertEqual(discovery_interval(10), 60)
        self.assertEqual(discovery_interval(60), 360)

    def test_scheduler_waits_refreshes_and_prioritizes_discovery(self):
        self.assertIsNone(next_auto_action(104.9, 100, 100, 5))
        self.assertEqual(next_auto_action(105, 100, 100, 5), AUTO_REFRESH)
        self.assertEqual(next_auto_action(130, 105, 100, 5), AUTO_DISCOVERY)
        self.assertEqual(next_auto_action(200, 0, 0, 5), AUTO_DISCOVERY)

    def test_selection_follows_node_identity_and_clamps_fallback(self):
        selected = NodeItem(name="Old name", key="AbCd")
        refreshed = [
            NodeItem(name="Other", key="other"),
            NodeItem(name="New name", key="aBcD"),
        ]
        self.assertEqual(stable_selection_index(refreshed, selected, 0), 1)

        named = NodeItem(name="Relay", key="")
        self.assertEqual(
            stable_selection_index([NodeItem(name="relay")], named, 0), 0
        )
        self.assertEqual(stable_selection_index(refreshed, named, 99), 1)
        self.assertEqual(stable_selection_index([], selected, 4), 0)


class ContactsAutoRefreshTests(unittest.TestCase):
    def test_opens_without_load_screen_then_refreshes_and_discovers(self):
        store = FakeContactStore()
        window = FakeWindow(keys=[None, None, 27])
        config = SimpleNamespace(
            simulation_mode=True, port="/dev/test", refresh_interval=5
        )

        with (
            patch("src.ui.views.contacts.ContactStore", return_value=store),
            patch("src.ui.views.contacts.BackgroundTask", InlineTask),
            patch("src.ui.views.contacts.run_with_progress") as progress,
            patch("src.ui.views.contacts.show_message") as show_message,
        ):
            run_contacts_view(window, object(), config)

        progress.assert_not_called()  # No blocking load screen on open.
        # Quick refresh first, then exactly one discovery right after it.
        self.assertEqual(store.discover_calls, [False, True])
        self.assertEqual(store.saved_calls, 2)
        show_message.assert_not_called()
        self.assertEqual(window.timeouts[0], 100)
        self.assertEqual(window.timeouts[-1], -1)
        rendered = "".join(write[2] for write in window.writes)
        self.assertIn("Relay", rendered)  # Cached data is shown immediately.
        self.assertIn("Auto: 5s", rendered)

    def test_key_m_toggles_auto_save_after_confirmation(self):
        store = FakeContactStore()
        window = FakeWindow(keys=[None, None, ord("m"), ord("M"), None, 27])
        config = SimpleNamespace(
            simulation_mode=True, port="/dev/test", refresh_interval=5
        )

        with (
            patch("src.ui.views.contacts.ContactStore", return_value=store),
            patch("src.ui.views.contacts.BackgroundTask", InlineTask),
            patch("src.ui.views.contacts.run_with_progress", side_effect=immediate_progress),
            # First toggle confirmed, second one cancelled.
            patch("src.ui.views.contacts.prompt_confirm", side_effect=[True, False]) as confirm,
            patch("src.ui.views.contacts.show_message") as show_message,
        ):
            run_contacts_view(window, object(), config)

        self.assertEqual(store.auto_save_reads, 1)  # Read once in the background.
        self.assertEqual(store.auto_save_writes, [False])
        self.assertIs(store.auto_save, False)
        self.assertEqual(confirm.call_args_list[0].args[2], "Auto-Speichern ist AN. Ausschalten?")
        self.assertEqual(confirm.call_args_list[1].args[2], "Auto-Speichern ist AUS. Einschalten?")
        show_message.assert_called_once()
        rendered = "".join(write[2] for write in window.writes)
        self.assertIn("Auto-Speichern: an", rendered)
        self.assertIn("Auto-Speichern: aus", rendered)

    def test_busy_background_task_finishes_before_exit(self):
        store = FakeContactStore(auto_delay=0.02)
        window = FakeWindow(keys=[27])
        config = SimpleNamespace(
            simulation_mode=True, port="/dev/test", refresh_interval=5
        )

        with (
            patch("src.ui.views.contacts.ContactStore", return_value=store),
            patch("src.ui.views.contacts.show_message") as show_message,
        ):
            run_contacts_view(window, object(), config)

        self.assertEqual(store.discover_calls, [False])
        self.assertTrue(store.auto_completed.is_set())
        show_message.assert_not_called()
        self.assertEqual(window.timeouts[-1], -1)

    def test_auto_error_is_status_only_and_does_not_open_popup(self):
        store = FakeContactStore(auto_error=RuntimeError("offline"))
        window = FakeWindow(keys=[None, 27])
        config = SimpleNamespace(
            simulation_mode=True, port="/dev/test", refresh_interval=5
        )

        with (
            patch("src.ui.views.contacts.ContactStore", return_value=store),
            patch("src.ui.views.contacts.BackgroundTask", InlineTask),
            patch("src.ui.views.contacts.run_with_progress", side_effect=immediate_progress),
            patch(
                "src.ui.views.contacts.next_auto_action",
                side_effect=[AUTO_REFRESH, None],
            ),
            patch("src.ui.views.contacts.show_message") as show_message,
        ):
            run_contacts_view(window, object(), config)

        show_message.assert_not_called()
        rendered = "".join(write[2] for write in window.writes)
        self.assertIn("Kontakte laden fehlgeschlagen: offline", rendered)
        self.assertEqual(store.discover_calls, [False])
        self.assertEqual(window.timeouts[-1], -1)


class ConnectionIntervalTests(unittest.TestCase):
    def test_key_six_cycles_persists_and_renders_refresh_interval(self):
        config = PersistentConfig()
        backend = SimpleNamespace(list_serial_ports=lambda: [])
        window = FakeWindow(keys=[ord("6")] * 5 + [27])

        with patch(
            "src.ui.views.connection.run_with_progress",
            side_effect=immediate_progress,
        ):
            run_connection_view(window, backend, config)

        self.assertEqual(config.saved_intervals, [10, 30, 60, 2, 5])
        self.assertEqual(config.refresh_interval, 5)
        rendered = "".join(write[2] for write in window.writes)
        self.assertIn("[6] Auto-Refresh", rendered)
        self.assertIn("Auto-Refresh:     60 Sekunden", rendered)
        self.assertIn("Auto: 5s", rendered)


if __name__ == "__main__":
    unittest.main()
