"""Pure math behind the card: pace, deficit, burn rate and projections.

Nothing here touches the network, disk or GTK, so it is all unit tested.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Sequence

from .config import BURN_LOOKBACK, MIN_BURN_SAMPLES

SECONDS_PER_HOUR = 3600.0
MIN_BURN_ELAPSED_SECONDS = 45.0
FULL_PERCENT = 100.0

# Até onde uma projeção ainda quer dizer algo. Uma inclinação positiva
# minúscula — ruído de ponto flutuante numa série parada — projeta séculos, e
# `timedelta` estoura muito antes disso. Além do horizonte a janela não está
# andando, e é isso que o card deve dizer.
MAX_PROJECTION = timedelta(days=365)
MAX_PROJECTION_HOURS = MAX_PROJECTION.total_seconds() / SECONDS_PER_HOUR

# A sample is a reading of one window's percentage at a point in time.
Sample = tuple[datetime, float]


def elapsed_fraction(
    resets_at: Optional[datetime], now: datetime, span: timedelta
) -> Optional[float]:
    """How far through the limit window we are, as 0.0 - 1.0."""
    if resets_at is None or span.total_seconds() <= 0:
        return None
    remaining = (resets_at - now).total_seconds()
    fraction = 1.0 - (remaining / span.total_seconds())
    return min(1.0, max(0.0, fraction))


def pace_delta(percent: float, elapsed: Optional[float]) -> Optional[float]:
    """Percentage points spent above (positive) or below the clock's pace."""
    if elapsed is None:
        return None
    return percent - elapsed * FULL_PERCENT


def _samples_since_reset(samples: Sequence[Sample]) -> list[Sample]:
    """Drop everything before the last drop in percentage (a window reset)."""
    trimmed: list[Sample] = []
    previous: Optional[float] = None
    for timestamp, percent in samples:
        if previous is not None and percent < previous - 0.001:
            trimmed = []
        trimmed.append((timestamp, percent))
        previous = percent
    return trimmed


def burn_rate_per_hour(
    samples: Sequence[Sample],
    now: datetime,
    lookback: timedelta = BURN_LOOKBACK,
) -> Optional[float]:
    """Least-squares slope of percentage over time, in points per hour."""
    recent = [
        (timestamp, percent)
        for timestamp, percent in _samples_since_reset(samples)
        if now - timestamp <= lookback
    ]
    if len(recent) < MIN_BURN_SAMPLES:
        return None

    base = recent[0][0]
    xs = [(timestamp - base).total_seconds() / SECONDS_PER_HOUR for timestamp, _ in recent]
    ys = [percent for _, percent in recent]
    if (xs[-1] - xs[0]) * SECONDS_PER_HOUR < MIN_BURN_ELAPSED_SECONDS:
        return None

    n = float(len(xs))
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    variance = sum((x - mean_x) ** 2 for x in xs)
    if variance <= 0:
        return None
    covariance = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    return covariance / variance


def _duration_from_hours(hours: float) -> Optional[timedelta]:
    """Duração para `hours`, ou None quando é longe demais para significar algo."""
    if not math.isfinite(hours) or hours > MAX_PROJECTION_HOURS:
        return None
    return timedelta(hours=hours)


@dataclass(frozen=True)
class Projection:
    """Forecast for one window given its current burn rate."""

    burn_per_hour: Optional[float]
    time_to_full: Optional[timedelta]
    time_to_reset: Optional[timedelta]

    @property
    def resets_first(self) -> bool:
        if self.time_to_full is None or self.time_to_reset is None:
            return self.time_to_full is None
        return self.time_to_full >= self.time_to_reset


def project(
    percent: float,
    resets_at: Optional[datetime],
    now: datetime,
    samples: Sequence[Sample],
    lookback: timedelta = BURN_LOOKBACK,
) -> Projection:
    """Combine burn rate and reset time into a forecast for the window."""
    burn = burn_rate_per_hour(samples, now, lookback)
    to_reset = max(timedelta(0), resets_at - now) if resets_at else None

    remaining = max(0.0, FULL_PERCENT - percent)
    if percent >= FULL_PERCENT:
        to_full: Optional[timedelta] = timedelta(0)
    elif burn is None or burn <= 0:
        to_full = None
    else:
        to_full = _duration_from_hours(remaining / burn)

    return Projection(burn_per_hour=burn, time_to_full=to_full, time_to_reset=to_reset)


def format_duration(delta: Optional[timedelta]) -> str:
    """Compact duration: "44m", "3h 5m", "2d 4h"."""
    if delta is None:
        return "—"
    seconds = int(delta.total_seconds())
    if seconds <= 0:
        return "agora"
    if seconds < 60:
        return "<1m"

    minutes, hours = (seconds // 60) % 60, seconds // 3600
    if hours == 0:
        return f"{minutes}m"
    if hours < 24:
        return f"{hours}h" if minutes == 0 else f"{hours}h {minutes}m"

    days, rest_hours = hours // 24, hours % 24
    return f"{days}d" if rest_hours == 0 else f"{days}d {rest_hours}h"


def format_wait(seconds: float) -> str:
    """Short wait for retry messages: "45s", "5m", "30m"."""
    if seconds < 60:
        return f"{int(seconds)}s"
    return format_duration(timedelta(seconds=seconds))


def format_percent(percent: Optional[float]) -> str:
    if percent is None:
        return "—"
    return f"{percent:.0f}%"


def format_pace(delta: Optional[float]) -> str:
    """"14% de déficit" / "6% de folga" / "no ritmo"."""
    if delta is None:
        return ""
    rounded = round(delta)
    if rounded == 0:
        return "no ritmo"
    if rounded > 0:
        return f"{rounded}% de déficit"
    return f"{abs(rounded)}% de folga"


def format_runs_out(projection: Projection) -> str:
    """Full text for the "Acaba em" slot, including the label."""
    if projection.time_to_full is None:
        return "Acaba em —"
    if projection.resets_first:
        return "Zera antes"
    return f"Acaba em {format_duration(projection.time_to_full)}"
