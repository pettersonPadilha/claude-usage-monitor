"""Background polling thread for the usage endpoint.

Kept free of GTK imports: the caller injects a `dispatch` function that
marshals results back onto the UI thread (GLib.idle_add in the real app).
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

from .api import UsageError, fetch_usage
from .metrics import format_wait
from .model import UsageSnapshot

log = logging.getLogger(__name__)

ResultHandler = Callable[[UsageSnapshot], None]
ErrorHandler = Callable[[str, bool], None]
Dispatch = Callable[[Callable[[], None]], None]

ERROR_BACKOFF_SECONDS = 20

# Consecutive 429s double the wait: 1m, 2m, 4m … capped at half an hour.
# The endpoint's own Retry-After is "0", so insisting only digs the hole
# deeper; the streak resets as soon as a fetch succeeds.
THROTTLE_BASE_SECONDS = 60.0
THROTTLE_MAX_SECONDS = 1800.0


class UsagePoller:
    """Fetches usage on an interval until stopped."""

    def __init__(
        self,
        on_result: ResultHandler,
        on_error: ErrorHandler,
        dispatch: Dispatch,
        interval_provider: Callable[[], int],
        fetcher: Callable[[], UsageSnapshot] = fetch_usage,
    ) -> None:
        self._on_result = on_result
        self._on_error = on_error
        self._dispatch = dispatch
        self._interval_provider = interval_provider
        self._fetcher = fetcher
        self._wake = threading.Event()
        self._stopped = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._throttle_streak = 0

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run, name="usage-poller", daemon=True
        )
        self._thread.start()

    def refresh_now(self) -> None:
        self._wake.set()

    def stop(self) -> None:
        self._stopped.set()
        self._wake.set()

    def _run(self) -> None:
        while not self._stopped.is_set():
            delay = self._poll_once()
            self._wake.wait(timeout=delay)
            self._wake.clear()

    def _poll_once(self) -> float:
        """Do one fetch; returns how long to sleep before the next one."""
        try:
            snapshot = self._fetcher()
        except UsageError as exc:
            if exc.is_throttled:
                return self._handle_throttle(exc)
            message, needs_login = str(exc), exc.needs_login
            self._dispatch(lambda: self._on_error(message, needs_login))
            return float(max(ERROR_BACKOFF_SECONDS, self._interval()))
        except Exception as exc:  # Never let the thread die on a surprise.
            log.exception("Unexpected error while fetching usage")
            message = f"Erro inesperado: {exc}"
            self._dispatch(lambda: self._on_error(message, False))
            return float(max(ERROR_BACKOFF_SECONDS, self._interval()))

        self._throttle_streak = 0
        self._dispatch(lambda: self._on_result(snapshot))
        return float(self._interval())

    def _handle_throttle(self, exc: UsageError) -> float:
        """Grow the wait on every consecutive 429 instead of insisting."""
        self._throttle_streak += 1
        delay = min(
            THROTTLE_BASE_SECONDS * (2 ** (self._throttle_streak - 1)),
            THROTTLE_MAX_SECONDS,
        )
        if exc.retry_after is not None:
            delay = max(delay, exc.retry_after)

        message = f"{exc} Nova tentativa em {format_wait(delay)}."
        self._dispatch(lambda: self._on_error(message, False))
        return delay

    def _interval(self) -> int:
        try:
            return max(1, int(self._interval_provider()))
        except Exception:
            return 60
