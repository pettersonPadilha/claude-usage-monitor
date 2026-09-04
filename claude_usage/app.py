"""Application wiring: settings, polling, history and the GTK widgets."""

from __future__ import annotations

import logging
import signal
import sys
from datetime import datetime, timezone
from typing import Optional

import gi

gi.require_version("Gtk", "3.0")

from gi.repository import GLib, Gtk  # noqa: E402

from .alerts import AlertTracker  # noqa: E402
from .config import (  # noqa: E402
    LOG_BACKUP_COUNT,
    LOG_MAX_BYTES,
    LOG_PATH,
    MAX_NOTIFY_THRESHOLD,
    MIN_NOTIFY_THRESHOLD,
    MIN_POLL_SECONDS,
    Settings,
    load_settings,
    save_settings,
)
from .history import SampleHistory  # noqa: E402
from .model import UsageSnapshot  # noqa: E402
from .poller import UsagePoller  # noqa: E402
from .ui.notify import Notifier  # noqa: E402
from .ui.tray import Tray  # noqa: E402
from .ui.window import CardWindow, load_css, setup_application_identity  # noqa: E402
from .viewmodel import CardView, build_card, empty_card  # noqa: E402

log = logging.getLogger(__name__)

TICK_SECONDS = 20


class UsageApp:
    """Owns application state and keeps the widgets in sync with it."""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self._settings = settings or load_settings()
        self._history = SampleHistory()
        self._history.load()
        self._snapshot: Optional[UsageSnapshot] = None
        self._status_text = "Carregando uso…"
        self._is_stale = False

        setup_application_identity()
        load_css()
        self._window = CardWindow(
            settings=self._settings,
            on_refresh=self.refresh_now,
            on_toggle_week=self.toggle_week,
            on_quit=self.quit,
            on_toggle_on_top=self.toggle_on_top,
            on_toggle_notify=self.toggle_notify,
        )
        self._tray = Tray(self.toggle_window, self.refresh_now, self.quit) \
            if self._settings.enable_tray else None

        self._notifier = Notifier()
        self._alerts = AlertTracker(
            threshold=self._settings.notify_threshold,
            enabled=self._settings.notify_enabled,
        )

        self._poller = UsagePoller(
            on_result=self._on_snapshot,
            on_error=self._on_error,
            dispatch=lambda fn: GLib.idle_add(fn),
            interval_provider=lambda: self._settings.poll_seconds,
        )

    # --- lifecycle -------------------------------------------------------
    def run(self) -> int:
        if not self._settings.start_hidden:
            self._window.show_all()
        self._render()
        self._poller.start()
        GLib.timeout_add_seconds(TICK_SECONDS, self._on_tick)
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, self._on_signal)
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, self._on_signal)
        Gtk.main()
        return 0

    def _on_signal(self) -> bool:
        self.quit()
        return GLib.SOURCE_REMOVE

    def quit(self) -> None:
        self._persist_position()
        self._poller.stop()
        self._history.save()
        self._notifier.close()
        Gtk.main_quit()

    # --- data ------------------------------------------------------------
    def _on_snapshot(self, snapshot: UsageSnapshot) -> bool:
        self._snapshot = snapshot
        self._status_text = ""
        self._is_stale = False
        self._history.record(snapshot)
        self._history.save()
        self._render()
        self._notify_alerts(snapshot)
        return GLib.SOURCE_REMOVE

    def _notify_alerts(self, snapshot: UsageSnapshot) -> None:
        for alert in self._alerts.evaluate(snapshot):
            log.info("Alerta: %s — %s", alert.title, alert.body)
            self._notifier.send(alert)

    def _on_error(self, message: str, needs_login: bool) -> bool:
        log.warning("Usage fetch failed: %s", message)
        self._status_text = message
        self._is_stale = self._snapshot is not None
        self._render()
        return GLib.SOURCE_REMOVE

    def _on_tick(self) -> bool:
        self._render()  # Countdowns move even between fetches.
        return GLib.SOURCE_CONTINUE

    def _render(self) -> None:
        """Redesenha o card. Nunca levanta exceção — ver o comentário abaixo."""
        try:
            view = self._build_view()
        except Exception:
            # Um quadro ruim não pode derrubar o resto. O GLib remove um
            # timeout cuja função levanta exceção, então deixar isto escapar
            # mataria o tique de 20s: os contadores param e o card fica preso
            # no último quadro desenhado para sempre.
            log.exception("Falhei ao montar o card")
            view = empty_card("Erro ao montar o card. Veja o log.")

        try:
            self._window.render(view)
            if self._tray is not None:
                self._tray.update(view)
        except Exception:
            log.exception("Falhei ao desenhar o card")

    def _build_view(self) -> CardView:
        return build_card(
            snapshot=self._snapshot,
            history=self._history,
            now=datetime.now(timezone.utc),
            show_week=self._settings.show_week,
            status_text=self._status_text,
            is_stale=self._is_stale,
        )

    # --- actions ---------------------------------------------------------
    def refresh_now(self) -> None:
        self._poller.refresh_now()

    def toggle_week(self) -> None:
        # The window is not resizable, so hiding the row shrinks it for us.
        self._update_settings(show_week=not self._settings.show_week)
        self._render()

    def toggle_on_top(self) -> None:
        self._update_settings(always_on_top=not self._settings.always_on_top)
        self._window.set_keep_above(self._settings.always_on_top)

    def toggle_notify(self) -> None:
        self._update_settings(notify_enabled=not self._settings.notify_enabled)
        self._alerts.configure(
            threshold=self._settings.notify_threshold,
            enabled=self._settings.notify_enabled,
        )

    def toggle_window(self) -> None:
        if self._window.get_visible():
            self._persist_position()
            self._window.hide()
        else:
            self._window.show_all()
            self._window.apply_settings(self._settings)
            self._render()

    def _update_settings(self, **changes) -> None:
        self._settings = self._settings.with_changes(**changes)
        save_settings(self._settings)

    def _persist_position(self) -> None:
        if not self._window.get_visible():
            return
        x, y = self._window.current_position()
        if x >= 0 and y >= 0 and (x, y) != (
            self._settings.window_x,
            self._settings.window_y,
        ):
            self._update_settings(window_x=x, window_y=y)


def _log_handlers() -> list[logging.Handler]:
    """Log na tela e em arquivo; sem o arquivo, um atalho do menu não deixa rastro."""
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    try:
        from logging.handlers import RotatingFileHandler

        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(
            RotatingFileHandler(
                LOG_PATH,
                maxBytes=LOG_MAX_BYTES,
                backupCount=LOG_BACKUP_COUNT,
                encoding="utf-8",
            )
        )
    except OSError as exc:  # Não poder gravar log não impede o app de subir.
        print(f"[monitor] sem log em arquivo: {exc}", file=sys.stderr)
    return handlers


def main(argv: Optional[list[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="claude-usage-monitor",
        description="Monitor flutuante dos limites de sessão e semana do Claude Code.",
    )
    parser.add_argument(
        "--interval", type=int, default=None, help="Intervalo de consulta em segundos"
    )
    parser.add_argument(
        "--hidden", action="store_true", help="Inicia com a janela escondida"
    )
    parser.add_argument(
        "--no-tray", action="store_true", help="Desativa o indicador de painel"
    )
    parser.add_argument(
        "--no-notify", action="store_true", help="Desativa o aviso de limite"
    )
    parser.add_argument(
        "--notify-threshold",
        type=float,
        default=None,
        metavar="PERCENT",
        help="Percentual que dispara o aviso (padrão 80)",
    )
    parser.add_argument("--verbose", action="store_true", help="Log detalhado")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=_log_handlers(),
    )

    settings = load_settings()
    if args.interval:
        settings = settings.with_changes(
            poll_seconds=max(MIN_POLL_SECONDS, args.interval)
        )
    if args.hidden:
        settings = settings.with_changes(start_hidden=True)
    if args.no_tray:
        settings = settings.with_changes(enable_tray=False)
    if args.no_notify:
        settings = settings.with_changes(notify_enabled=False)
    if args.notify_threshold is not None:
        settings = settings.with_changes(
            notify_threshold=min(
                MAX_NOTIFY_THRESHOLD,
                max(MIN_NOTIFY_THRESHOLD, args.notify_threshold),
            )
        )

    return UsageApp(settings).run()
