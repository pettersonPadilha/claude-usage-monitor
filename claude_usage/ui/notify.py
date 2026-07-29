"""Desktop notifications, with the same graceful degradation as the tray.

Prefers libnotify through GI (lets us replace a window's previous notification
instead of stacking a new one), falls back to the `notify-send` binary, and
finally to a log line — the app never depends on any of them being present.
"""

from __future__ import annotations

import logging
import shutil
import subprocess

import gi

from ..alerts import URGENCY_CRITICAL, Alert
from ..config import APP_NAME, ICON_NAME

log = logging.getLogger(__name__)

NOTIFY_SEND = "notify-send"


def _load_notify_module():
    try:
        gi.require_version("Notify", "0.7")
        from gi.repository import Notify

        if not Notify.is_initted() and not Notify.init(APP_NAME):
            return None
        return Notify
    except (ValueError, ImportError, AttributeError) as exc:
        log.debug("libnotify unavailable (%s)", exc)
        return None


class Notifier:
    """Shows threshold alerts on the desktop; `backend` reports what we got."""

    def __init__(self) -> None:
        self._notify = _load_notify_module()
        self._handles: dict[str, object] = {}
        self._has_notify_send = shutil.which(NOTIFY_SEND) is not None
        if self._notify is None and not self._has_notify_send:
            log.info(
                "Sem backend de notificação (instale libnotify-bin para receber avisos)"
            )

    @property
    def backend(self) -> str:
        if self._notify is not None:
            return "libnotify"
        return NOTIFY_SEND if self._has_notify_send else "none"

    def send(self, alert: Alert) -> bool:
        """Show one alert. Returns False when no backend could deliver it."""
        if self._notify is not None and self._send_via_libnotify(alert):
            return True
        if self._has_notify_send:
            return self._send_via_binary(alert)
        log.info("Alerta não entregue: %s — %s", alert.title, alert.body)
        return False

    def close(self) -> None:
        for handle in self._handles.values():
            try:
                handle.close()  # type: ignore[attr-defined]
            except Exception:  # Shutting down; a failure here is noise.
                pass
        self._handles.clear()

    # --- backends --------------------------------------------------------
    def _send_via_libnotify(self, alert: Alert) -> bool:
        assert self._notify is not None
        try:
            # Reusing the handle per window updates the existing bubble rather
            # than queueing another one behind it.
            handle = self._handles.get(alert.key)
            if handle is None:
                handle = self._notify.Notification.new(
                    alert.title, alert.body, ICON_NAME
                )
                self._handles[alert.key] = handle
            else:
                handle.update(alert.title, alert.body, ICON_NAME)
            handle.set_urgency(self._urgency(alert))
            handle.show()
            return True
        except Exception as exc:
            log.warning("libnotify falhou (%s); usando %s", exc, NOTIFY_SEND)
            self._notify = None
            self._handles.clear()
            return False

    def _urgency(self, alert: Alert):
        assert self._notify is not None
        urgency = self._notify.Urgency
        return (
            urgency.CRITICAL if alert.urgency == URGENCY_CRITICAL else urgency.NORMAL
        )

    def _send_via_binary(self, alert: Alert) -> bool:
        command = [
            NOTIFY_SEND,
            "--app-name",
            APP_NAME,
            "--icon",
            ICON_NAME,
            "--urgency",
            alert.urgency,
            alert.title,
            alert.body,
        ]
        try:
            subprocess.run(command, check=True, timeout=10)
            return True
        except (OSError, subprocess.SubprocessError) as exc:
            log.warning("%s falhou: %s", NOTIFY_SEND, exc)
            self._has_notify_send = False
            return False
