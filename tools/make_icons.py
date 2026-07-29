#!/usr/bin/env python3
"""Generate the application icon at every size the desktop needs.

Writes PNGs into icons/<size>x<size>/ plus a scalable SVG. Run it after
changing the design; install.sh copies the result into the hicolor theme.

Usage: tools/make_icons.py [output_dir]
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import cairo

SIZES = (16, 22, 24, 32, 48, 64, 128, 256, 512)

BACKGROUND = (0.106, 0.102, 0.098)  # #1b1a19
BACKGROUND_EDGE = (0.180, 0.173, 0.165)
MARK = (0.851, 0.471, 0.310)  # #d9784f, the Claude orange
SPOKES = 8
# Alternating spoke lengths give the mark its off-balance, hand-drawn feel.
LONG, SHORT = 1.0, 0.74
TILT = math.radians(11)


def _rounded_rect(cr: cairo.Context, size: float, radius: float) -> None:
    cr.new_sub_path()
    cr.arc(size - radius, radius, radius, -math.pi / 2, 0)
    cr.arc(size - radius, size - radius, radius, 0, math.pi / 2)
    cr.arc(radius, size - radius, radius, math.pi / 2, math.pi)
    cr.arc(radius, radius, radius, math.pi, 1.5 * math.pi)
    cr.close_path()


def draw(cr: cairo.Context, size: float, with_background: bool = True) -> None:
    """Draw the icon into a `size` x `size` context."""
    if with_background:
        _rounded_rect(cr, size, size * 0.22)
        cr.set_source_rgb(*BACKGROUND)
        cr.fill_preserve()
        cr.set_source_rgb(*BACKGROUND_EDGE)
        cr.set_line_width(max(1.0, size * 0.015))
        cr.stroke()

    center = size / 2
    radius = size * 0.30
    cr.set_source_rgb(*MARK)
    cr.set_line_width(max(1.5, size * 0.085))
    cr.set_line_cap(cairo.LINE_CAP_ROUND)

    for index in range(SPOKES):
        angle = math.tau * index / SPOKES + TILT
        length = radius * (LONG if index % 2 == 0 else SHORT)
        cr.move_to(center, center)
        cr.line_to(center + math.cos(angle) * length,
                   center + math.sin(angle) * length)
        cr.stroke()


def write_png(path: Path, size: int) -> None:
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    draw(cairo.Context(surface), size)
    path.parent.mkdir(parents=True, exist_ok=True)
    surface.write_to_png(str(path))


def write_svg(path: Path, size: int = 256) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    surface = cairo.SVGSurface(str(path), size, size)
    draw(cairo.Context(surface), size)
    surface.finish()


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "icons")
    for size in SIZES:
        write_png(root / f"{size}x{size}" / "claude-usage-monitor.png", size)
    write_svg(root / "scalable" / "claude-usage-monitor.svg")
    print(f"Wrote {len(SIZES)} PNGs and 1 SVG into {root}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
