"""Progress bar with a pace marker, built from CSS-styled boxes.

Uses plain widgets rather than Cairo so the app needs no extra system
packages (python3-gi-cairo is not installed by default on Ubuntu).
"""

from __future__ import annotations

from typing import Optional

import gi

gi.require_version("Gtk", "3.0")

from gi.repository import Gtk  # noqa: E402

from ..model import SEVERITY_NORMAL  # noqa: E402

BAR_HEIGHT = 12
MARKER_WIDTH = 2
SEVERITY_CLASSES = ("severity-normal", "severity-warning", "severity-critical")


def apply_severity(widget: Gtk.Widget, severity: str) -> None:
    """Swap the severity CSS class on a widget."""
    context = widget.get_style_context()
    for name in SEVERITY_CLASSES:
        context.remove_class(name)
    context.add_class(f"severity-{severity or SEVERITY_NORMAL}")


class UsageBar(Gtk.Overlay):
    """Track, fill and a thin marker showing where the clock is."""

    def __init__(self) -> None:
        super().__init__()
        self._fraction = 0.0
        self._marker: Optional[float] = None

        track = Gtk.Box()
        track.get_style_context().add_class("bar-track")
        track.set_size_request(-1, BAR_HEIGHT)
        self.add(track)

        # Both overlay children keep the default FILL alignment: any other
        # halign makes GTK shrink them back to their natural width, ignoring
        # the allocation returned from get-child-position.
        self._fill = Gtk.Box()
        self._fill.get_style_context().add_class("bar-fill")
        apply_severity(self._fill, SEVERITY_NORMAL)
        self.add_overlay(self._fill)

        self._marker_box = Gtk.Box()
        self._marker_box.get_style_context().add_class("bar-marker")
        self.add_overlay(self._marker_box)

        self.set_overlay_pass_through(self._fill, True)
        self.set_overlay_pass_through(self._marker_box, True)
        self.connect("get-child-position", self._on_child_position)

    def update(self, fraction: float, marker: Optional[float], severity: str) -> None:
        self._fraction = min(1.0, max(0.0, fraction))
        self._marker = marker
        apply_severity(self._fill, severity)
        self._fill.set_visible(self._fraction > 0)
        self._marker_box.set_visible(marker is not None)
        self.queue_resize()

    def _on_child_position(self, _overlay, widget, allocation):
        """GTK reads the allocation back from the returned tuple, not in place."""
        width = self.get_allocated_width()
        height = self.get_allocated_height()
        if width <= 0 or height <= 0:
            return (False, allocation)

        allocation.y = 0
        allocation.height = height

        if widget is self._fill:
            allocation.x = 0
            allocation.width = max(0, int(round(width * self._fraction)))
            return (True, allocation)

        if widget is self._marker_box and self._marker is not None:
            position = int(round(width * min(1.0, max(0.0, self._marker))))
            allocation.x = min(max(0, position - MARKER_WIDTH // 2), width - MARKER_WIDTH)
            allocation.width = MARKER_WIDTH
            return (True, allocation)

        return (False, allocation)
