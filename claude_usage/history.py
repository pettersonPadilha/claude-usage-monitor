"""Rolling store of usage samples, used to derive burn rate across restarts."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional

from .config import HISTORY_PATH, HISTORY_RETENTION, MAX_HISTORY_SAMPLES
from .metrics import Sample
from .model import UsageSnapshot, parse_timestamp

log = logging.getLogger(__name__)

TRACKED_KEYS = ("session", "week")


class SampleHistory:
    """Append-only (pruned) history of percentages per window."""

    def __init__(
        self,
        path: Path = HISTORY_PATH,
        retention: timedelta = HISTORY_RETENTION,
        max_samples: int = MAX_HISTORY_SAMPLES,
    ) -> None:
        self._path = path
        self._retention = retention
        self._max_samples = max_samples
        self._samples: dict[str, list[Sample]] = {key: [] for key in TRACKED_KEYS}

    # --- reading ---------------------------------------------------------
    def samples(self, key: str) -> list[Sample]:
        return list(self._samples.get(key, ()))

    # --- writing ---------------------------------------------------------
    def record(self, snapshot: UsageSnapshot) -> None:
        for key in TRACKED_KEYS:
            window = snapshot.window(key)
            if window is None:
                continue
            self._append(key, snapshot.fetched_at, window.percent)
        self._prune(snapshot.fetched_at)

    def _append(self, key: str, timestamp: datetime, percent: float) -> None:
        bucket = self._samples.setdefault(key, [])
        if bucket and bucket[-1][0] >= timestamp:
            return  # Out-of-order or duplicate reading; keep the series clean.
        bucket.append((timestamp, percent))

    def _prune(self, now: datetime) -> None:
        cutoff = now - self._retention
        for key, bucket in self._samples.items():
            kept = [item for item in bucket if item[0] >= cutoff]
            if len(kept) > self._max_samples:
                kept = kept[-self._max_samples :]
            self._samples[key] = kept

    # --- persistence -----------------------------------------------------
    def load(self) -> None:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("Ignoring unreadable history at %s: %s", self._path, exc)
            return

        if not isinstance(raw, dict):
            return
        for key in TRACKED_KEYS:
            self._samples[key] = list(_decode_samples(raw.get(key)))
        self._prune(datetime.now(timezone.utc))

    def save(self) -> bool:
        payload = {
            key: [[timestamp.isoformat(), percent] for timestamp, percent in bucket]
            for key, bucket in self._samples.items()
        }
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload), encoding="utf-8")
            tmp.replace(self._path)
            return True
        except OSError as exc:
            log.warning("Could not save history to %s: %s", self._path, exc)
            return False


def _decode_samples(raw: object) -> Iterable[Sample]:
    if not isinstance(raw, list):
        return
    for entry in raw:
        if not isinstance(entry, (list, tuple)) or len(entry) != 2:
            continue
        timestamp: Optional[datetime] = parse_timestamp(entry[0])
        percent = entry[1]
        if timestamp is None or isinstance(percent, bool):
            continue
        if not isinstance(percent, (int, float)):
            continue
        yield (timestamp, float(percent))
