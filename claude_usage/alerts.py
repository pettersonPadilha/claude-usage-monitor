"""Decides when a usage window deserves a desktop notification.

Pure logic — no GTK, no libnotify. The app feeds snapshots in and gets back
the alerts worth showing: at most one per window per rate-limit cycle, so a
card sitting above 80% for hours does not notify on every poll.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .config import CRITICAL_THRESHOLD, DEFAULT_NOTIFY_THRESHOLD
from .metrics import format_duration, format_percent
from .model import LimitWindow, UsageSnapshot

URGENCY_NORMAL = "normal"
URGENCY_CRITICAL = "critical"

TRACKED_KEYS = ("session", "week")


@dataclass(frozen=True)
class Alert:
    """One notification to show, already worded for the user."""

    key: str
    title: str
    body: str
    urgency: str


@dataclass(frozen=True)
class _Fired:
    """Marks the window cycle an alert was already shown for."""

    resets_at: Optional[datetime]


class AlertTracker:
    """Emits an alert the first time a window crosses the threshold.

    A window is considered a new cycle when its `resets_at` changes, or when
    usage falls back below the threshold (accounts without `resets_at` rely on
    that second signal).
    """

    def __init__(
        self,
        threshold: float = DEFAULT_NOTIFY_THRESHOLD,
        enabled: bool = True,
    ) -> None:
        self._threshold = float(threshold)
        self._enabled = bool(enabled)
        self._fired: dict[str, _Fired] = {}

    def configure(self, threshold: float, enabled: bool) -> None:
        """Apply new settings; a changed threshold re-arms every window."""
        if float(threshold) != self._threshold:
            self._fired.clear()
        self._threshold = float(threshold)
        self._enabled = bool(enabled)

    def evaluate(self, snapshot: UsageSnapshot) -> list[Alert]:
        """Alerts to show for this reading, in session-then-week order."""
        alerts: list[Alert] = []
        for key in TRACKED_KEYS:
            window = snapshot.window(key)
            if window is None:
                continue
            if window.percent < self._threshold:
                # Back under the line: the next crossing is worth announcing.
                self._fired.pop(key, None)
                continue
            if not self._should_fire(key, window):
                continue
            self._fired[key] = _Fired(resets_at=window.resets_at)
            # Muted trackers still follow the state so enabling them later
            # announces the next crossing instead of replaying this one.
            if self._enabled:
                alerts.append(self._build(window, snapshot.fetched_at))
        return alerts

    def _should_fire(self, key: str, window: LimitWindow) -> bool:
        previous = self._fired.get(key)
        if previous is None:
            return True
        return previous.resets_at != window.resets_at

    def _build(self, window: LimitWindow, now: datetime) -> Alert:
        urgency = (
            URGENCY_CRITICAL
            if window.percent >= CRITICAL_THRESHOLD
            else URGENCY_NORMAL
        )
        return Alert(
            key=window.key,
            title=f"{window.label} em {format_percent(window.percent)}",
            body=self._body(window, now),
            urgency=urgency,
        )

    @staticmethod
    def _body(window: LimitWindow, now: datetime) -> str:
        if window.is_exhausted:
            headline = "Limite esgotado."
        else:
            headline = f"Restam {format_percent(window.remaining_percent)}."
        if window.resets_at is None:
            return headline
        return f"{headline} Zera em {format_duration(window.resets_at - now)}."
