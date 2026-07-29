"""Paths, tunable constants and on-disk user configuration."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, replace
from datetime import timedelta
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

APP_ID = "claude-usage-monitor"
APP_TITLE = "Claude"
APP_NAME = "Claude Usage Monitor"
ICON_NAME = "claude-usage-monitor"
BUNDLED_ICONS_DIR = Path(__file__).resolve().parent.parent / "icons"

# --- Data sources -----------------------------------------------------------
CLAUDE_HOME = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
CREDENTIALS_PATH = CLAUDE_HOME / ".credentials.json"
USAGE_ENDPOINT = "https://api.anthropic.com/api/oauth/usage"
OAUTH_BETA_HEADER = "oauth-2025-04-20"
USER_AGENT = "claude-usage-monitor/1.0 (linux; gtk)"
REQUEST_TIMEOUT_SECONDS = 20

# --- Rate limit windows -----------------------------------------------------
SESSION_SPAN = timedelta(hours=5)
WEEK_SPAN = timedelta(days=7)

# --- Burn rate --------------------------------------------------------------
BURN_LOOKBACK = timedelta(minutes=45)
MIN_BURN_SAMPLES = 2
HISTORY_RETENTION = timedelta(hours=12)
MAX_HISTORY_SAMPLES = 2000

# --- Severity thresholds (percent used) -------------------------------------
WARNING_THRESHOLD = 75.0
CRITICAL_THRESHOLD = 90.0

# --- Threshold alerts -------------------------------------------------------
DEFAULT_NOTIFY_THRESHOLD = 80.0
MIN_NOTIFY_THRESHOLD = 1.0
MAX_NOTIFY_THRESHOLD = 100.0

# --- User config ------------------------------------------------------------
CONFIG_DIR = Path(
    os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")
) / APP_ID
CONFIG_PATH = CONFIG_DIR / "config.json"
DATA_DIR = Path(
    os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")
) / APP_ID
HISTORY_PATH = DATA_DIR / "history.json"

# The usage endpoint rate limits aggressive clients, and the percentages it
# returns are whole numbers that move slowly, so polling hard buys nothing:
# the countdowns are recomputed locally every tick regardless.
MIN_POLL_SECONDS = 60
DEFAULT_POLL_SECONDS = 300


@dataclass(frozen=True)
class Settings:
    """Immutable user settings; use `with_changes` to derive a new value."""

    poll_seconds: int = DEFAULT_POLL_SECONDS
    always_on_top: bool = True
    show_week: bool = True
    start_hidden: bool = False
    enable_tray: bool = True
    show_in_taskbar: bool = True
    notify_enabled: bool = True
    notify_threshold: float = DEFAULT_NOTIFY_THRESHOLD
    window_x: int = -1
    window_y: int = -1

    def with_changes(self, **changes: Any) -> "Settings":
        return replace(self, **changes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "poll_seconds": self.poll_seconds,
            "always_on_top": self.always_on_top,
            "show_week": self.show_week,
            "start_hidden": self.start_hidden,
            "enable_tray": self.enable_tray,
            "show_in_taskbar": self.show_in_taskbar,
            "notify_enabled": self.notify_enabled,
            "notify_threshold": self.notify_threshold,
            "window_x": self.window_x,
            "window_y": self.window_y,
        }


def _coerce(raw: dict[str, Any]) -> Settings:
    defaults = Settings()
    poll = raw.get("poll_seconds", defaults.poll_seconds)
    try:
        poll = max(MIN_POLL_SECONDS, int(poll))
    except (TypeError, ValueError):
        poll = defaults.poll_seconds

    def flag(key: str, fallback: bool) -> bool:
        value = raw.get(key, fallback)
        return bool(value) if isinstance(value, bool) else fallback

    def coord(key: str) -> int:
        try:
            return int(raw.get(key, -1))
        except (TypeError, ValueError):
            return -1

    threshold = raw.get("notify_threshold", defaults.notify_threshold)
    try:
        threshold = min(
            MAX_NOTIFY_THRESHOLD, max(MIN_NOTIFY_THRESHOLD, float(threshold))
        )
    except (TypeError, ValueError):
        threshold = defaults.notify_threshold

    return Settings(
        poll_seconds=poll,
        always_on_top=flag("always_on_top", defaults.always_on_top),
        show_week=flag("show_week", defaults.show_week),
        start_hidden=flag("start_hidden", defaults.start_hidden),
        enable_tray=flag("enable_tray", defaults.enable_tray),
        show_in_taskbar=flag("show_in_taskbar", defaults.show_in_taskbar),
        notify_enabled=flag("notify_enabled", defaults.notify_enabled),
        notify_threshold=threshold,
        window_x=coord("window_x"),
        window_y=coord("window_y"),
    )


def load_settings(path: Path = CONFIG_PATH) -> Settings:
    """Read settings from disk, falling back to defaults on any problem."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return Settings()
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Could not read %s (%s); using defaults", path, exc)
        return Settings()

    if not isinstance(raw, dict):
        log.warning("Config at %s is not an object; using defaults", path)
        return Settings()
    return _coerce(raw)


def save_settings(settings: Settings, path: Path = CONFIG_PATH) -> bool:
    """Persist settings atomically. Returns False when the write failed."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(settings.to_dict(), indent=2) + "\n", encoding="utf-8"
        )
        tmp.replace(path)
        return True
    except OSError as exc:
        log.warning("Could not save settings to %s: %s", path, exc)
        return False
