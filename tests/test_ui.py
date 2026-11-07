"""Hardware-free tests for curses geometry, Unicode input and async UI tasks."""

import curses
import sys
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.backend.chat_store import ChatMessage, ChatStore
from src.backend.executor import MeshCoreBackend
from src.config import Config
from src.ui.async_task import BackgroundTask
from src.ui.colors import COLOR_SELECTED, get_color, init_colors
from src.ui.views.chat_view import (
    ChatSyncScheduler,
    ensure_history_message_visible,
    format_history_entries,
    format_history_lines,
    run_chat_view,
    update_message_selection,
)
from src.ui.widgets import (
    dialog_geometry,
    ensure_visible,
    prompt_input,
    read_key,
    safe_move,
    show_message,
    wrap_text_lines,
)


class FakeWindow:
    """Small curses-window double which rejects out-of-bounds cursor moves."""

    def __init__(self, height=12, width=40, keys=None):
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
        key = self.keys.pop(0)
        if key == curses.KEY_RESIZE:
            self.height, self.width = 5, 24
        return key

    def addstr(self, y, x, text, attr=0):
        if not (0 <= y < self.height and 0 <= x < self.width):
            raise AssertionError(f"write outside fake window: {(y, x)}")
        self.writes.append((y, x, text, attr))

    def move(self, y, x):
        if not (0 <= y < self.height and 0 <= x < self.width):
            raise AssertionError(f"cursor outside fake window: {(y, x)}")

    def refresh(self):
        pass

    def clear(self):
        pass

    def timeout(self, milliseconds):
        self.timeouts.append(milliseconds)


class ImmediateBackgroundTask:
    """Synchronous test double with the same one-result polling contract."""

    def __init__(self):
        self.busy = False
        self.result = None

    def start(self, operation):
        if self.busy:
            return False
        try:
            self.result = SimpleNamespace(success=True, value=operation())
        except Exception as exc:
            self.result = SimpleNamespace(success=False, value=exc)
        self.busy = True
        return True

    def poll(self):
        if not self.busy:
            return None
        self.busy = False
        result, self.result = self.result, None
        return result

    def close(self):
        self.busy = False
        self.result = None


class MainArgumentTests(unittest.TestCase):
    def test_explicit_serial_disables_autoselect_and_saved_baud_is_kept(self):
        import src.main as main_module

        app = SimpleNamespace(
            config=SimpleNamespace(port="saved-port", baudrate=9600, simulation_mode=False),
            run=lambda: None,
        )
        with (
            patch.object(main_module, "MeshCoreTUIApp", return_value=app) as app_class,
            patch.object(sys, "argv", ["meshcore", "-s", "/dev/ttyACM7"]),
        ):
            main_module.main()
        app_class.assert_called_once_with(auto_select_port=False)
        self.assertEqual(app.config.port, "/dev/ttyACM7")
        self.assertEqual(app.config.baudrate, 9600)

    def test_baud_is_only_overridden_when_explicit(self):
        import src.main as main_module

        app = SimpleNamespace(
            config=SimpleNamespace(port="saved-port", baudrate=9600, simulation_mode=False),
            run=lambda: None,
        )
        with (
            patch.object(main_module, "MeshCoreTUIApp", return_value=app) as app_class,
            patch.object(sys, "argv", ["meshcore", "-b", "57600"]),
        ):
            main_module.main()
        app_class.assert_called_once_with(auto_select_port=True)
        self.assertEqual(app.config.port, "saved-port")
        self.assertEqual(app.config.baudrate, 57600)

    def test_saved_custom_port_is_not_replaced_by_usb_autoselect(self):
        from src.ui.app import MeshCoreTUIApp

        app = MeshCoreTUIApp.__new__(MeshCoreTUIApp)
        app.config = SimpleNamespace(port="/dev/serial/by-id/custom-node", simulation_mode=False)
        app.backend = SimpleNamespace(list_serial_ports=Mock(side_effect=AssertionError("must not scan")))
        app.auto_select_port = True
        app.selected_index = 0
        app.menu_offset = 0

        with patch("src.ui.app.init_colors"):
            app._main_loop(FakeWindow(keys=[27, ord("y")]))

        self.assertEqual(app.config.port, "/dev/serial/by-id/custom-node")
        app.backend.list_serial_ports.assert_not_called()


class GeometryTests(unittest.TestCase):
    def test_dialog_geometry_is_bounded_for_tiny_windows(self):
        for height, width in ((1, 1), (2, 3), (5, 8), (24, 80)):
            y, x, dlg_h, dlg_w = dialog_geometry(height, width, 60, 7)
            self.assertGreaterEqual(y, 0)
            self.assertGreaterEqual(x, 0)
            self.assertGreaterEqual(dlg_h, 1)
            self.assertGreaterEqual(dlg_w, 1)
            self.assertLessEqual(y + dlg_h, height)
            self.assertLessEqual(x + dlg_w, width)

    def test_selection_remains_visible_and_offset_clamps_after_resize(self):
        self.assertEqual(ensure_visible(8, 0, 4, 10), 5)
        self.assertEqual(ensure_visible(1, 5, 4, 10), 1)
        self.assertEqual(ensure_visible(9, 20, 20, 10), 0)
        self.assertEqual(ensure_visible(0, 0, 0, 10), 0)

    def test_safe_move_ignores_out_of_bounds_positions(self):
        window = FakeWindow(2, 3)
        safe_move(window, -1, 0)
        safe_move(window, 2, 0)
        safe_move(window, 0, 3)
        safe_move(window, 1, 2)  # Valid; FakeWindow validates it.

    def test_long_unbroken_uri_is_wrapped_without_losing_tail(self):
        uri = "meshcore://" + "a" * 180 + "TAIL"
        lines = wrap_text_lines(uri, 24)
        self.assertGreater(len(lines), 2)
        self.assertEqual("".join(lines), uri)
        self.assertTrue(all(len(line) <= 24 for line in lines))


class UnicodeAndDialogTests(unittest.TestCase):
    def test_prompt_input_preserves_unicode_and_resize(self):
        window = FakeWindow(keys=[curses.KEY_RESIZE, "Ä", "ö", " ", "😀", 10])
        self.assertEqual(prompt_input(window, "Unicode", "Text:"), "Äö 😀")

    def test_show_message_can_scroll_to_long_uri_tail(self):
        uri = "meshcore://" + "0123456789" * 15 + "END"
        window = FakeWindow(height=7, width=30, keys=[curses.KEY_END, 10])
        show_message(window, "Export", uri)
        self.assertIn("END", "".join(write[2] for write in window.writes))

    def test_function_keys_and_unicode_are_distinguished(self):
        window = FakeWindow(keys=[curses.KEY_UP, "ä", "x"])
        self.assertEqual(read_key(window), curses.KEY_UP)
        self.assertEqual(read_key(window), "ä")
        self.assertEqual(read_key(window), ord("x"))
        self.assertIsNone(read_key(window))


class RenderingTests(unittest.TestCase):
    def test_chat_history_wraps_long_messages(self):
        message = ChatMessage(
            sender="Ich",
            text="Anfang " + "x" * 100 + " Ende",
            timestamp="12:00",
            is_outgoing=True,
        )
        lines = format_history_lines([message], 25)
        self.assertGreater(len(lines), 3)
        self.assertTrue(all(len(line) <= 25 for line, _ in lines))
        self.assertTrue(lines[-1][0].endswith("Ende"))

    def test_monochrome_selection_uses_reverse_video(self):
        with patch("src.ui.colors.curses.has_colors", return_value=False):
            self.assertTrue(get_color(COLOR_SELECTED) & curses.A_REVERSE)

    def test_default_color_failure_falls_back_to_normal_background(self):
        initialized = []
        with (
            patch("src.ui.colors.curses.has_colors", return_value=True),
            patch("src.ui.colors.curses.start_color"),
            patch("src.ui.colors.curses.use_default_colors", side_effect=curses.error()),
            patch("src.ui.colors.curses.init_pair", side_effect=lambda *args: initialized.append(args)),
        ):
            init_colors()
        self.assertTrue(initialized)
        self.assertTrue(all(args[2] != -1 for args in initialized))


class ChatSyncSchedulerTests(unittest.TestCase):
    def test_next_sync_is_relative_to_completion_and_claimed_only_once(self):
        scheduler = ChatSyncScheduler(5)
        self.assertFalse(scheduler.start_if_due(100))

        scheduler.schedule(10)
        self.assertEqual(scheduler.next_sync_at, 15)
        self.assertFalse(scheduler.start_if_due(14.99))
        self.assertTrue(scheduler.start_if_due(15))
        self.assertIsNone(scheduler.next_sync_at)
        self.assertFalse(scheduler.start_if_due(100))

        # Completion after a slow sync creates a fresh full interval.
        scheduler.schedule(21)
        self.assertEqual(scheduler.next_sync_at, 26)

    def test_manual_sync_can_postpone_an_existing_deadline(self):
        scheduler = ChatSyncScheduler(5)
        scheduler.schedule(10)
        scheduler.schedule(12)
        self.assertEqual(scheduler.next_sync_at, 17)
        self.assertFalse(scheduler.start_if_due(16))


class HistorySelectionTests(unittest.TestCase):
    @staticmethod
    def message(text):
        return ChatMessage(sender="Alice", text=text, timestamp="12:00")

    def test_wrapped_entries_keep_message_indices_and_legacy_api(self):
        history = [self.message("x" * 60), self.message("zweite")]
        entries = format_history_entries(history, 20)
        self.assertGreater(len(entries), 3)
        message_indices = [index for _, _, index in entries]
        first_second_message = message_indices.index(1)
        self.assertTrue(all(index == 0 for index in message_indices[:first_second_message]))
        self.assertTrue(all(index == 1 for index in message_indices[first_second_message:]))
        self.assertEqual(
            format_history_lines(history, 20),
            [(text, color) for text, color, _ in entries],
        )

    def test_new_messages_only_move_selection_when_following_latest(self):
        selected = update_message_selection(None, 0, 2, follow_latest=True)
        self.assertEqual(selected, 1)
        self.assertEqual(update_message_selection(selected, 2, 3, follow_latest=True), 2)
        self.assertEqual(update_message_selection(0, 2, 3, follow_latest=False), 0)
        self.assertEqual(update_message_selection(2, 3, 1, follow_latest=False), 0)
        self.assertIsNone(update_message_selection(0, 1, 0, follow_latest=False))

    def test_selection_is_scrolled_into_viewport_without_changing_page_model(self):
        history = [self.message(text) for text in ("erste", "zweite", "dritte")]
        entries = format_history_entries(history, 120)
        self.assertEqual(len(entries), 3)

        older_offset = ensure_history_message_visible(entries, 0, 2, 0)
        self.assertEqual(older_offset, 1)
        newest_offset = ensure_history_message_visible(entries, 2, 2, older_offset)
        self.assertEqual(newest_offset, 0)
        self.assertEqual(ensure_history_message_visible(entries, 1, 2, 0), 0)


class ChatStoreLocalDeletionTests(unittest.TestCase):
    def setUp(self):
        self.store = ChatStore(storage_path=None)
        self.target = self.store.targets[0]
        self.other_target = self.store.targets[1]
        self.store.history[self.target.id] = [
            ChatMessage(sender="Alice", text="erste", timestamp="12:00"),
            ChatMessage(sender="Bob", text="zweite", timestamp="12:01"),
        ]
        self.store.history[self.other_target.id] = [
            ChatMessage(sender="Carol", text="bleibt", timestamp="12:02")
        ]

    def test_delete_message_removes_exactly_one_local_entry(self):
        self.assertFalse(self.store.delete_message(self.target.id, -1))
        self.assertFalse(self.store.delete_message(self.target.id, 2))
        self.assertTrue(self.store.delete_message(self.target.id, 0))
        self.assertEqual([msg.text for msg in self.store.get_history(self.target.id)], ["zweite"])
        self.assertEqual([msg.text for msg in self.store.get_history(self.other_target.id)], ["bleibt"])

    def test_clear_history_preserves_target_and_other_rooms(self):
        self.store.clear_history(self.target.id)
        self.assertEqual(self.store.get_history(self.target.id), [])
        self.assertIn(self.target, self.store.targets)
        self.assertEqual([msg.text for msg in self.store.get_history(self.other_target.id)], ["bleibt"])


class ChatViewTests(unittest.TestCase):
    def test_chat_accepts_unicode_survives_tiny_resize_and_restores_timeout(self):
        config = Config(config_file=None)
        config.simulation_mode = True
        backend = MeshCoreBackend(config)
        store = ChatStore(storage_path=None)
        window = FakeWindow(
            height=12,
            width=60,
            keys=["ä", curses.KEY_RESIZE, 27, ord("y")],
        )
        run_chat_view(window, backend, config, chat_store=store)
        self.assertEqual(window.timeouts[0], 100)
        self.assertEqual(window.timeouts[-1], -1)
        self.assertIn("ä", "".join(write[2] for write in window.writes))

    def test_auto_sync_runs_after_idle_interval_without_error_popup(self):
        config = Config(config_file=None)
        config.simulation_mode = True
        backend = Mock()

        def run_cli(args, **_kwargs):
            if args == ["sync_msgs"]:
                return False, "offline"
            return True, ""

        backend.run_cli.side_effect = run_cli
        store = ChatStore(storage_path=None)
        window = FakeWindow(height=14, width=100, keys=[ord("x"), 27])

        with (
            patch("src.ui.views.chat_view.BackgroundTask", ImmediateBackgroundTask),
            patch("src.ui.views.chat_view.time.monotonic", side_effect=[0, 0, 5, 5]),
            patch("src.ui.views.chat_view.show_message") as error_popup,
        ):
            run_chat_view(window, backend, config, chat_store=store)

        sync_calls = [call for call in backend.run_cli.call_args_list if call.args[0] == ["sync_msgs"]]
        self.assertEqual(len(sync_calls), 2)  # Initial sync and one automatic sync.
        error_popup.assert_not_called()

    def test_auto_sync_does_not_change_manually_selected_message_before_delete(self):
        config = Config(config_file=None)
        config.simulation_mode = True
        backend = Mock()
        store = ChatStore(storage_path=None)
        target = store.targets[0]
        store.history[target.id] = [
            ChatMessage(sender="Alice", text="erste", timestamp="12:00"),
            ChatMessage(sender="Bob", text="zweite", timestamp="12:01"),
        ]
        sync_calls = 0

        def run_cli(args, **_kwargs):
            nonlocal sync_calls
            if args != ["sync_msgs"]:
                return True, ""
            sync_calls += 1
            if sync_calls == 2:
                store.add_message(
                    target.id, ChatMessage(sender="Carol", text="dritte", timestamp="12:02")
                )
            return True, ""

        backend.run_cli.side_effect = run_cli
        window = FakeWindow(
            height=16,
            width=110,
            keys=[
                ord("\t"), ord("\t"), curses.KEY_UP, curses.KEY_LEFT,
                curses.KEY_DC, ord("y"), 27, 27, ord("y"),
            ],
        )

        with (
            patch("src.ui.views.chat_view.BackgroundTask", ImmediateBackgroundTask),
            patch(
                "src.ui.views.chat_view.time.monotonic",
                side_effect=[0, 0, 0, 0, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5],
            ),
        ):
            run_chat_view(window, backend, config, chat_store=store)

        self.assertEqual(sync_calls, 2)
        self.assertEqual(
            [msg.text for msg in store.get_history(target.id)],
            ["zweite", "dritte"],
            "The manually selected first message, not the newly arrived third, is deleted.",
        )

    def test_room_list_delete_removes_complete_local_conversation(self):
        config = Config(config_file=None)
        config.simulation_mode = True
        backend = Mock()
        backend.run_cli.return_value = (True, "")
        store = ChatStore(storage_path=None)
        target = store.get_or_create_target("Delete Me", is_channel=False)
        store.add_message(
            target.id, ChatMessage(sender="Alice", text="kompletter Verlauf", timestamp="12:00")
        )
        other_target = store.targets[0]
        store.add_message(
            other_target.id, ChatMessage(sender="Bob", text="bleibt", timestamp="12:01")
        )
        window = FakeWindow(
            height=16,
            width=110,
            keys=[ord("\t"), curses.KEY_DC, ord("y"), 27, 27, ord("y")],
        )

        with patch("src.ui.views.chat_view.BackgroundTask", ImmediateBackgroundTask):
            run_chat_view(
                window,
                backend,
                config,
                initial_target="@Delete Me",
                chat_store=store,
            )

        self.assertNotIn(target.id, [item.id for item in store.targets])
        self.assertEqual(store.get_history(target.id), [])
        self.assertEqual([msg.text for msg in store.get_history(other_target.id)], ["bleibt"])
        self.assertFalse(
            any(
                call.args[0] and call.args[0][0] == "remove_channel"
                for call in backend.run_cli.call_args_list
            )
        )
        self.assertIn("Chat und lokaler Verlauf gelöscht.", "".join(write[2] for write in window.writes))

    def test_history_selection_deletes_only_confirmed_local_message(self):
        config = Config(config_file=None)
        config.simulation_mode = True
        backend = Mock()
        backend.run_cli.return_value = (True, "")
        store = ChatStore(storage_path=None)
        target = store.targets[0]
        store.history[target.id] = [
            ChatMessage(sender="Alice", text="erste", timestamp="12:00"),
            ChatMessage(sender="Bob", text="zweite", timestamp="12:01"),
        ]
        window = FakeWindow(
            height=16,
            width=110,
            keys=[ord("\t"), ord("\t"), curses.KEY_UP, curses.KEY_DC, ord("y"), 27, 27, ord("y")],
        )

        with patch("src.ui.views.chat_view.BackgroundTask", ImmediateBackgroundTask):
            run_chat_view(window, backend, config, chat_store=store)

        self.assertEqual([msg.text for msg in store.get_history(target.id)], ["zweite"])
        self.assertIn("Lokale Nachricht gelöscht.", "".join(write[2] for write in window.writes))
        self.assertTrue(
            any("erste" in text and attr & curses.A_REVERSE for _, _, text, attr in window.writes),
            "The selected message must be visibly highlighted before deletion.",
        )


class BackgroundTaskTests(unittest.TestCase):
    def test_only_one_worker_runs_and_result_is_polled_once(self):
        task = BackgroundTask()
        release = threading.Event()
        calls = []

        def operation():
            calls.append(threading.current_thread().name)
            release.wait(1)
            return 42

        self.assertTrue(task.start(operation))
        self.assertFalse(task.start(lambda: calls.append("parallel")))
        release.set()
        deadline = time.monotonic() + 2
        result = task.poll()
        while result is None and time.monotonic() < deadline:
            time.sleep(0.001)
            result = task.poll()
        self.assertIsNotNone(result)
        self.assertTrue(result.success)
        self.assertEqual(result.value, 42)
        self.assertEqual(len(calls), 1)
        self.assertIsNone(task.poll())
        task.close()


if __name__ == "__main__":
    unittest.main()
