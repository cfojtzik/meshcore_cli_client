"""Small background-task helper used by curses views.

Only the UI thread touches curses.  A view owns at most one ``BackgroundTask``;
workers perform backend I/O and return their result through a queue.  Closing a
view detaches its still-running daemon thread and discards its eventual result.
"""

from dataclasses import dataclass
import curses
import queue
import threading
from typing import Any, Callable, Optional

from .colors import COLOR_WARNING, get_color
from .widgets import draw_header, draw_status_bar, read_key, safe_addstr


# Also protects against overlap when a user leaves a chat with I/O in flight
# and immediately opens another view.
_BACKEND_IO_LOCK = threading.Lock()


@dataclass
class AsyncResult:
    """Result of a completed background operation."""

    success: bool
    value: Any


class BackgroundTask:
    """Run one callable at a time without doing curses work in the thread."""

    def __init__(self) -> None:
        self._results: queue.Queue = queue.Queue(maxsize=1)
        self._thread: Optional[threading.Thread] = None
        self._active = False
        self._closed = False

    @property
    def busy(self) -> bool:
        return self._active

    def start(self, func: Callable[[], Any]) -> bool:
        """Start *func*, or return ``False`` if another operation is pending."""
        if self._active or self._closed:
            return False

        self._active = True

        def run() -> None:
            try:
                with _BACKEND_IO_LOCK:
                    result = AsyncResult(True, func())
            except Exception as exc:  # Backend errors must reach the UI thread.
                result = AsyncResult(False, exc)
            self._results.put(result)

        self._thread = threading.Thread(target=run, daemon=True, name="meshcore-ui-io")
        self._thread.start()
        return True

    def poll(self) -> Optional[AsyncResult]:
        """Return a finished result once, or ``None`` while work is pending."""
        if not self._active:
            return None
        try:
            result = self._results.get_nowait()
        except queue.Empty:
            return None
        self._active = False
        self._thread = None
        if self._closed:
            return None
        return result

    def close(self) -> None:
        """Detach from the worker; never join serial I/O on the UI thread."""
        self._closed = True
        self._active = False
        self._thread = None
        while True:
            try:
                self._results.get_nowait()
            except queue.Empty:
                break


def run_with_progress(
    stdscr: curses.window,
    task: BackgroundTask,
    title: str,
    func: Callable[[], Any],
) -> AsyncResult:
    """Run a non-chat action while continuing to poll input and resize.

    Other keys are deliberately ignored while a serial command is active.  This
    keeps one command per view and avoids queuing duplicate destructive actions.
    Chat uses ``BackgroundTask`` directly so typing can continue there.
    """
    if not task.start(func):
        return AsyncResult(False, RuntimeError("Es läuft bereits eine Backend-Aktion."))

    stdscr.timeout(100)
    try:
        while True:
            result = task.poll()
            if result is not None:
                return result

            max_y, max_x = stdscr.getmaxyx()
            stdscr.clear()
            draw_header(stdscr, title, "Backend-Aktion läuft")
            draw_status_bar(stdscr, "Bitte warten … Fenster kann weiterhin vergrößert/verkleinert werden.")
            text = "Serielle Kommunikation läuft; kein weiterer Befehl wird parallel gestartet."
            safe_addstr(
                stdscr,
                max(1, max_y // 2),
                max(0, (max_x - len(text)) // 2),
                text,
                get_color(COLOR_WARNING),
            )
            stdscr.refresh()
            # Reading is required both for KEY_RESIZE and to avoid a blocking UI.
            read_key(stdscr)
    finally:
        stdscr.timeout(-1)
