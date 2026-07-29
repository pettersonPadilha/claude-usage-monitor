"""Domain types for a usage reading and the parsing of the API payload."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

SEVERITY_NORMAL = "normal"
SEVERITY_WARNING = "warning"
SEVERITY_CRITICAL = "critical"


def parse_timestamp(value: Any) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp into an aware datetime, or None."""
    if not isinstance(value, str) or not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _percent(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return max(0.0, float(value))


@dataclass(frozen=True)
class LimitWindow:
    """One rate-limit bucket (the 5 hour session or the 7 day week)."""

    key: str
    label: str
    percent: float
    resets_at: Optional[datetime]
    severity: str = SEVERITY_NORMAL

    @property
    def remaining_percent(self) -> float:
        return max(0.0, 100.0 - self.percent)

    @property
    def is_exhausted(self) -> bool:
        return self.percent >= 100.0


@dataclass(frozen=True)
class UsageSnapshot:
    """A full reading of the account's usage at a point in time."""

    fetched_at: datetime
    session: Optional[LimitWindow]
    week: Optional[LimitWindow]
    plan_label: str = ""

    def window(self, key: str) -> Optional[LimitWindow]:
        return self.session if key == "session" else self.week


def _window_from_payload(
    payload: dict[str, Any], payload_key: str, key: str, label: str
) -> Optional[LimitWindow]:
    block = payload.get(payload_key)
    if not isinstance(block, dict):
        return None
    percent = _percent(block.get("utilization"))
    if percent is None:
        return None
    return LimitWindow(
        key=key,
        label=label,
        percent=percent,
        resets_at=parse_timestamp(block.get("resets_at")),
        severity=severity_for(percent),
    )


def _severity_from_limits(payload: dict[str, Any], kind: str) -> Optional[str]:
    limits = payload.get("limits")
    if not isinstance(limits, list):
        return None
    for entry in limits:
        if not isinstance(entry, dict) or entry.get("kind") != kind:
            continue
        severity = entry.get("severity")
        if isinstance(severity, str) and severity:
            return severity
    return None


def severity_for(percent: float) -> str:
    """Local severity used when the API does not provide one."""
    from .config import CRITICAL_THRESHOLD, WARNING_THRESHOLD

    if percent >= CRITICAL_THRESHOLD:
        return SEVERITY_CRITICAL
    if percent >= WARNING_THRESHOLD:
        return SEVERITY_WARNING
    return SEVERITY_NORMAL


def _merge_severity(window: Optional[LimitWindow], api: Optional[str]):
    """Prefer the harsher of the API severity and our local thresholds."""
    if window is None:
        return None
    rank = {SEVERITY_NORMAL: 0, SEVERITY_WARNING: 1, SEVERITY_CRITICAL: 2}
    if api is None or rank.get(api, 0) <= rank.get(window.severity, 0):
        return window
    return LimitWindow(
        key=window.key,
        label=window.label,
        percent=window.percent,
        resets_at=window.resets_at,
        severity=api,
    )


def snapshot_from_payload(
    payload: dict[str, Any], fetched_at: datetime, plan_label: str = ""
) -> UsageSnapshot:
    """Build a snapshot from the /api/oauth/usage response body."""
    session = _window_from_payload(payload, "five_hour", "session", "Sessão")
    week = _window_from_payload(payload, "seven_day", "week", "Semana")
    return UsageSnapshot(
        fetched_at=fetched_at,
        session=_merge_severity(session, _severity_from_limits(payload, "session")),
        week=_merge_severity(week, _severity_from_limits(payload, "weekly_all")),
        plan_label=plan_label,
    )
