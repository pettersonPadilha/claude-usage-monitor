"""The floating always-on-top card window."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")

from gi.repository import Gdk, GdkPixbuf, GLib, Gtk  # noqa: E402

from ..config import (  # noqa: E402
    APP_ID,
    APP_NAME,
    APP_TITLE,
    BUNDLED_ICONS_DIR,
    ICON_NAME,
    Settings,
)
from ..viewmodel import CardView  # noqa: E402
from .row import UsageRow  # noqa: E402

STYLE_PATH = Path(__file__).with_name("style.css")
CARD_WIDTH = 344
RAIL_WIDTH = 42
CLAUDE_GLYPH = "✳"


def load_css() -> None:
    """Install the app stylesheet once per screen."""
    try:
        provider = Gtk.CssProvider()
        provider.load_from_path(str(STYLE_PATH))
    except Exception:  # A broken stylesheet must not stop the app.
        return
    screen = Gdk.Screen.get_default()
    if screen is not None:
        Gtk.StyleContext.add_provider_for_screen(
            screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )


def setup_application_identity() -> None:
    """Name the process and pick the window icon.

    The program name becomes the WM_CLASS, which is how the dock and the
    window list match the running app to its .desktop entry. The icon comes
    from the installed theme when install.sh has run, and from the bundled
    PNGs otherwise, so the app never falls back to a generic square.
    """
    GLib.set_prgname(APP_ID)
    GLib.set_application_name(APP_NAME)

    if Gtk.IconTheme.get_default().has_icon(ICON_NAME):
        Gtk.Window.set_default_icon_name(ICON_NAME)
        return

    pixbufs = []
    for path in sorted(BUNDLED_ICONS_DIR.glob(f"*/{ICON_NAME}.png")):
        try:
            pixbufs.append(GdkPixbuf.Pixbuf.new_from_file(str(path)))
        except GLib.Error:
            continue
    if pixbufs:
        Gtk.Window.set_default_icon_list(pixbufs)


class CardWindow(Gtk.Window):
    """Undecorated, draggable card that mirrors the reference design."""

    def __init__(
        self,
        settings: Settings,
        on_refresh: Callable[[], None],
        on_toggle_week: Callable[[], None],
        on_quit: Callable[[], None],
        on_toggle_on_top: Callable[[], None],
        on_toggle_notify: Callable[[], None],
    ) -> None:
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self._on_refresh = on_refresh
        self._on_toggle_week = on_toggle_week
        self._on_quit = on_quit
        self._on_toggle_on_top = on_toggle_on_top
        self._on_toggle_notify = on_toggle_notify
        self._rows: dict[str, UsageRow] = {}

        self.set_name("card-window")
        self.set_title(APP_NAME)
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_skip_pager_hint(True)
        self.stick()
        self.set_default_size(CARD_WIDTH, -1)
        self.set_app_paintable(True)
        self._enable_transparency()
        self.apply_settings(settings)

        self.add(self._build_card())
        self.connect("button-press-event", self._on_button_press)
        self.connect("delete-event", self._on_delete)

    # --- construction ----------------------------------------------------
    def _enable_transparency(self) -> None:
        screen = self.get_screen()
        visual = screen.get_rgba_visual() if screen else None
        if visual is not None:
            self.set_visual(visual)

    def _build_card(self) -> Gtk.Widget:
        card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        card.set_name("card")
        card.pack_start(self._build_rail(), False, False, 0)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        content.set_border_width(12)
        content.pack_start(self._build_header(), False, False, 0)

        self._rows_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.pack_start(self._rows_box, False, False, 0)

        self._status = Gtk.Label(label="", xalign=0.0)
        self._status.get_style_context().add_class("status")
        self._status.set_line_wrap(True)
        self._status.set_no_show_all(True)
        content.pack_start(self._status, False, False, 0)

        card.pack_start(content, True, True, 0)
        return card

    def _build_rail(self) -> Gtk.Widget:
        rail = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        rail.set_name("rail")
        rail.set_size_request(RAIL_WIDTH, -1)
        rail.set_border_width(9)

        brand = Gtk.Label(label=CLAUDE_GLYPH)
        brand.get_style_context().add_class("brand")
        rail.pack_start(brand, False, False, 2)

        rail.pack_start(
            self._icon_button(
                "view-refresh-symbolic", "Atualizar agora", lambda _b: self._on_refresh()
            ),
            False,
            False,
            0,
        )
        rail.pack_start(
            self._icon_button(
                "x-office-calendar-symbolic",
                "Mostrar ou ocultar a linha da semana",
                lambda _b: self._on_toggle_week(),
            ),
            False,
            False,
            0,
        )
        rail.pack_end(
            self._icon_button(
                "open-menu-symbolic", "Menu", lambda _b: self._popup_menu(None)
            ),
            False,
            False,
            0,
        )
        return rail

    @staticmethod
    def _icon_button(icon_name: str, tooltip: str, handler) -> Gtk.Button:
        button = Gtk.Button()
        button.set_relief(Gtk.ReliefStyle.NONE)
        button.add(Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.MENU))
        button.set_tooltip_text(tooltip)
        button.connect("clicked", handler)
        return button

    def _build_header(self) -> Gtk.Widget:
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        title = Gtk.Label(label=APP_TITLE, xalign=0.0)
        title.get_style_context().add_class("app-title")
        header.pack_start(title, False, False, 0)

        self._badge = Gtk.Label(label="")
        self._badge.get_style_context().add_class("badge")
        self._badge.set_no_show_all(True)
        header.pack_end(self._badge, False, False, 0)
        return header

    # --- state -----------------------------------------------------------
    def apply_settings(self, settings: Settings) -> None:
        self.set_keep_above(settings.always_on_top)
        self.set_skip_taskbar_hint(not settings.show_in_taskbar)
        if settings.window_x >= 0 and settings.window_y >= 0:
            self.move(settings.window_x, settings.window_y)

    def render(self, view: CardView) -> None:
        """Update the card in place; rows are created on first sight."""
        context = self.get_style_context()
        if view.is_stale:
            context.add_class("stale")
        else:
            context.remove_class("stale")

        if view.plan_label:
            self._badge.set_text(view.plan_label)
            self._badge.show()
        else:
            self._badge.hide()

        seen = set()
        for index, row_view in enumerate(view.rows):
            row = self._rows.get(row_view.key)
            if row is None:
                row = UsageRow()
                self._rows[row_view.key] = row
                self._rows_box.pack_start(row, False, False, 0)
            row.update(row_view)
            self._rows_box.reorder_child(row, index)
            row.show_all()
            seen.add(row_view.key)

        for key, row in self._rows.items():
            if key not in seen:
                row.hide()

        if view.status_text:
            self._status.set_text(view.status_text)
            self._status.show()
        else:
            self._status.hide()

    def current_position(self) -> tuple[int, int]:
        try:
            x, y = self.get_position()
            return int(x), int(y)
        except Exception:
            return (-1, -1)

    # --- interaction -----------------------------------------------------
    def _on_button_press(self, _widget, event) -> bool:
        if event.type != Gdk.EventType.BUTTON_PRESS:
            return False
        if event.button == Gdk.BUTTON_PRIMARY:
            self.begin_move_drag(
                event.button, int(event.x_root), int(event.y_root), event.time
            )
            return True
        if event.button == Gdk.BUTTON_SECONDARY:
            self._popup_menu(event)
            return True
        return False

    def _popup_menu(self, event: Optional[Gdk.Event]) -> None:
        menu = Gtk.Menu()
        for label, handler in (
            ("Atualizar agora", lambda _i: self._on_refresh()),
            ("Mostrar/ocultar a semana", lambda _i: self._on_toggle_week()),
            ("Alternar sempre no topo", lambda _i: self._on_toggle_on_top()),
            ("Alternar aviso de limite", lambda _i: self._on_toggle_notify()),
            ("Esconder", lambda _i: self.hide()),
            ("Sair", lambda _i: self._on_quit()),
        ):
            item = Gtk.MenuItem(label=label)
            item.connect("activate", handler)
            menu.append(item)
        menu.show_all()
        if event is not None:
            menu.popup_at_pointer(event)
        else:
            menu.popup_at_widget(self, Gdk.Gravity.SOUTH_WEST, Gdk.Gravity.NORTH_WEST, None)

    def _on_delete(self, *_args) -> bool:
        self.hide()
        return True  # Closing hides to the tray instead of quitting.
