"""Turns a snapshot plus history into the exact strings the card renders."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from .config import SESSION_SPAN, WEEK_SPAN
from .history import SampleHistory
from .metrics import (
    elapsed_fraction,
    format_duration,
    format_pace,
    format_percent,
    format_runs_out,
    pace_delta,
    project,
)
from .model import SEVERITY_NORMAL, LimitWindow, UsageSnapshot

SPANS: dict[str, timedelta] = {"session": SESSION_SPAN, "week": WEEK_SPAN}


@dataclass(frozen=True)
class RowView:
    """Everything one progress row needs to draw itself."""

    key: str
    title: str
    percent_text: str
    pace_text: str
    resets_text: str
    runs_out_text: str
    fill: float
    pace_marker: Optional[float]
    severity: str


@dataclass(frozen=True)
class CardView:
    """Full card state, including the error/placeholder cases."""

    plan_label: str
    rows: tuple[RowView, ...]
    status_text: str = ""
    is_stale: bool = False

    @property
    def tray_label(self) -> str:
        if not self.rows:
            return "—"
        return self.rows[0].percent_text


def _row(
    window: LimitWindow, now: datetime, history: SampleHistory
) -> RowView:
    span = SPANS.get(window.key, SESSION_SPAN)
    elapsed = elapsed_fraction(window.resets_at, now, span)
    samples = history.samples(window.key)
    projection = project(window.percent, window.resets_at, now, samples)

    resets_text = (
        f"Zera em {format_duration(projection.time_to_reset)}"
        if projection.time_to_reset is not None
        else "Reset desconhecido"
    )

    return RowView(
        key=window.key,
        title=window.label,
        percent_text=format_percent(window.percent),
        pace_text=format_pace(pace_delta(window.percent, elapsed)),
        resets_text=resets_text,
        runs_out_text=format_runs_out(projection),
        fill=min(1.0, max(0.0, window.percent / 100.0)),
        pace_marker=elapsed,
        severity=window.severity,
    )


def build_card(
    snapshot: Optional[UsageSnapshot],
    history: SampleHistory,
    now: datetime,
    show_week: bool = True,
    status_text: str = "",
    is_stale: bool = False,
) -> CardView:
    """Compose the card view; `status_text` shows errors without hiding data."""
    if snapshot is None:
        return CardView(
            plan_label="",
            rows=(),
            status_text=status_text or "Carregando dados de uso…",
            is_stale=is_stale,
        )

    windows = [snapshot.session]
    if show_week:
        windows.append(snapshot.week)

    rows = tuple(_row(window, now, history) for window in windows if window)
    return CardView(
        plan_label=snapshot.plan_label,
        rows=rows,
        status_text=status_text,
        is_stale=is_stale,
    )


def empty_card(status_text: str) -> CardView:
    return CardView(plan_label="", rows=(), status_text=status_text)


def severity_class(severity: str) -> str:
    return f"severity-{severity or SEVERITY_NORMAL}"
