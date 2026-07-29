#!/usr/bin/env python3
"""Render the card and save it as a PNG.

Development helper: check the layout without waiting for real usage to
move. Usage: tools/preview.py [output.png] [--live]

With --live it performs one real fetch instead of using sample data.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("GDK_BACKEND", "x11")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")

from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from claude_usage.config import Settings  # noqa: E402
from claude_usage.history import SampleHistory  # noqa: E402
from claude_usage.model import snapshot_from_payload  # noqa: E402
from claude_usage.ui.window import CardWindow, load_css  # noqa: E402
from claude_usage.viewmodel import build_card  # noqa: E402

NOW = datetime.now(timezone.utc)


def sample_snapshot(session_percent: float, week_percent: float):
    return snapshot_from_payload(
        {
            "five_hour": {
                "utilization": session_percent,
                "resets_at": (NOW + timedelta(minutes=44)).isoformat(),
            },
            "seven_day": {
                "utilization": week_percent,
                "resets_at": (NOW + timedelta(days=5, hours=6)).isoformat(),
            },
        },
        NOW,
        "Team 5x",
    )


def main() -> int:
    arguments = [value for value in sys.argv[1:] if not value.startswith("--")]
    live = "--live" in sys.argv
    output = Path(arguments[0] if arguments else "preview.png")

    if live:
        from claude_usage.api import fetch_usage

        snapshot = fetch_usage()
        history = SampleHistory(Path("/tmp/claude-usage-preview.json"))
        history.load()
        history.record(snapshot)
    else:
        snapshot = sample_snapshot(62.0, 19.0)
        history = SampleHistory(Path("/tmp/claude-usage-preview.json"))
        history.record(sample_snapshot(47.0, 18.0))
        history._samples["session"][0] = (NOW - timedelta(minutes=30), 47.0)
        history._samples["week"][0] = (NOW - timedelta(minutes=30), 18.0)
        history.record(snapshot)

    load_css()
    window = CardWindow(
        settings=Settings(window_x=80, window_y=80),
        on_refresh=lambda: None,
        on_toggle_week=lambda: None,
        on_quit=Gtk.main_quit,
        on_toggle_on_top=lambda: None,
    )
    window.render(build_card(snapshot, history, NOW, show_week=True))
    window.show_all()

    def grab() -> bool:
        gdk_window = window.get_window()
        width, height = window.get_size()
        pixbuf = Gdk.pixbuf_get_from_window(gdk_window, 0, 0, width, height)
        if pixbuf is None:
            print("Could not grab the window", file=sys.stderr)
        else:
            pixbuf.savev(str(output), "png", [], [])
            print(f"Wrote {output} ({width}x{height})")
        Gtk.main_quit()
        return GLib.SOURCE_REMOVE

    GLib.timeout_add(700, grab)
    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
