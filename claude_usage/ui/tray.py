"""Optional panel indicator.

Uses Ayatana AppIndicator when the typelib is installed and degrades to a
plain Gtk.StatusIcon otherwise; the app works fine with neither.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

import gi

gi.require_version("Gtk", "3.0")

from gi.repository import Gtk  # noqa: E402

from ..config import APP_ID  # noqa: E402
from ..model import SEVERITY_CRITICAL, SEVERITY_WARNING  # noqa: E402
from ..viewmodel import CardView  # noqa: E402

log = logging.getLogger(__name__)

INSTALL_HINT = (
    "Indicador de painel indisponível. Instale com: "
    "sudo apt install gir1.2-ayatanaappindicator3-0.1"
)

ICON_NORMAL = "utilities-system-monitor-symbolic"
ICON_WARNING = "dialog-warning-symbolic"
ICON_CRITICAL = "dialog-error-symbolic"

SEVERITY_ICONS = {
    SEVERITY_WARNING: ICON_WARNING,
    SEVERITY_CRITICAL: ICON_CRITICAL,
}


def _load_indicator_module():
    for namespace in ("AyatanaAppIndicator3", "AppIndicator3"):
        try:
            gi.require_version(namespace, "0.1")
            module = __import__("gi.repository", fromlist=[namespace])
            return getattr(module, namespace)
        except (ValueError, ImportError, AttributeError):
            continue
    return None


class Tray:
    """Panel presence for the monitor; `available` reports what we got."""

    def __init__(
        self,
        on_toggle_window: Callable[[], None],
        on_refresh: Callable[[], None],
        on_quit: Callable[[], None],
    ) -> None:
        self._on_toggle_window = on_toggle_window
        self._on_refresh = on_refresh
        self._on_quit = on_quit
        self._indicator = None
        self._status_icon: Optional[Gtk.StatusIcon] = None
        self._menu = self._build_menu()

        module = _load_indicator_module()
        if module is not None:
            self._indicator = module.Indicator.new(
                APP_ID, ICON_NORMAL, module.IndicatorCategory.SYSTEM_SERVICES
            )
            self._indicator.set_status(module.IndicatorStatus.ACTIVE)
            self._indicator.set_menu(self._menu)
            self._indicator.set_title("Uso do Claude")
        else:
            log.info(INSTALL_HINT)
            self._status_icon = Gtk.StatusIcon.new_from_icon_name(ICON_NORMAL)
            self._status_icon.connect("activate", lambda _i: self._on_toggle_window())
            self._status_icon.connect("popup-menu", self._on_status_popup)

    @property
    def available(self) -> bool:
        return self._indicator is not None

    def _build_menu(self) -> Gtk.Menu:
        menu = Gtk.Menu()
        for label, handler in (
            ("Mostrar / esconder", lambda _i: self._on_toggle_window()),
            ("Atualizar agora", lambda _i: self._on_refresh()),
            ("Sair", lambda _i: self._on_quit()),
        ):
            item = Gtk.MenuItem(label=label)
            item.connect("activate", handler)
            menu.append(item)
        menu.show_all()
        return menu

    def _on_status_popup(self, icon, button, time) -> None:
        self._menu.popup(None, None, Gtk.StatusIcon.position_menu, icon, button, time)

    def update(self, view: CardView) -> None:
        """Refresh the panel label, tooltip and icon."""
        tooltip = self._tooltip(view)
        icon_name = self._icon_name(view)

        if self._indicator is not None:
            self._indicator.set_label(view.tray_label, "100%")
            self._indicator.set_title(tooltip)
            self._indicator.set_icon_full(icon_name, tooltip)
        elif self._status_icon is not None:
            self._status_icon.set_tooltip_text(tooltip)
            self._status_icon.set_from_icon_name(icon_name)

    @staticmethod
    def _icon_name(view: CardView) -> str:
        if not view.rows:
            return ICON_NORMAL
        return SEVERITY_ICONS.get(view.rows[0].severity, ICON_NORMAL)

    @staticmethod
    def _tooltip(view: CardView) -> str:
        if not view.rows:
            return view.status_text or "Uso do Claude"
        parts = [
            f"{row.title}: {row.percent_text} · {row.resets_text}"
            for row in view.rows
        ]
        if view.status_text:
            parts.append(view.status_text)
        return "\n".join(parts)
