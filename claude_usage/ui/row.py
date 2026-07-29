"""The usage row: title, status dot, progress bar and four metric labels."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Pango", "1.0")

from gi.repository import Gtk, Pango  # noqa: E402

from ..viewmodel import RowView  # noqa: E402
from .bar import UsageBar, apply_severity  # noqa: E402

DOT_SIZE = 9


class UsageRow(Gtk.Box):
    """One limit window rendered as in the reference design."""

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)

        self._title = Gtk.Label(label="", xalign=0.0)
        self._title.get_style_context().add_class("row-title")

        self._dot = Gtk.Box()
        self._dot.get_style_context().add_class("dot")
        self._dot.set_size_request(DOT_SIZE, DOT_SIZE)
        self._dot.set_valign(Gtk.Align.CENTER)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=7)
        header.pack_start(self._title, False, False, 0)
        header.pack_start(self._dot, False, False, 0)
        self.pack_start(header, False, False, 0)

        self._bar = UsageBar()
        self.pack_start(self._bar, False, False, 0)

        self._percent = self._metric(0.0)
        self._pace = self._metric(0.0)
        self._resets = self._metric(1.0)
        self._runs_out = self._metric(1.0)

        grid = Gtk.Grid(column_homogeneous=True, row_spacing=1, column_spacing=8)
        grid.attach(self._percent, 0, 0, 1, 1)
        grid.attach(self._resets, 1, 0, 1, 1)
        grid.attach(self._pace, 0, 1, 1, 1)
        grid.attach(self._runs_out, 1, 1, 1, 1)
        self.pack_start(grid, False, False, 0)

    @staticmethod
    def _metric(xalign: float) -> Gtk.Label:
        label = Gtk.Label(label="", xalign=xalign)
        label.get_style_context().add_class("metric")
        label.set_ellipsize(Pango.EllipsizeMode.END)
        return label

    def update(self, view: RowView) -> None:
        self._title.set_text(view.title)
        self._percent.set_text(view.percent_text)
        self._pace.set_text(view.pace_text)
        self._resets.set_text(view.resets_text)
        self._runs_out.set_text(view.runs_out_text)
        apply_severity(self._dot, view.severity)
        self._bar.update(view.fill, view.pace_marker, view.severity)
