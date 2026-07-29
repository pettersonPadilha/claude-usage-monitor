import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from claude_usage.api import UsageError
from claude_usage.config import (
    MIN_POLL_SECONDS,
    Settings,
    load_settings,
    save_settings,
)
from claude_usage.history import SampleHistory
from claude_usage.model import snapshot_from_payload
from claude_usage.poller import THROTTLE_MAX_SECONDS, UsagePoller
from claude_usage.viewmodel import build_card

NOW = datetime(2026, 7, 25, 18, 0, tzinfo=timezone.utc)


def make_snapshot(session_pct=50.0, week_pct=19.0, at=NOW, minutes_to_reset=44):
    resets = (at + timedelta(minutes=minutes_to_reset)).isoformat()
    return snapshot_from_payload(
        {
            "five_hour": {"utilization": session_pct, "resets_at": resets},
            "seven_day": {"utilization": week_pct, "resets_at": resets},
        },
        at,
        "Team 5x",
    )


class HistoryTest(unittest.TestCase):
    def setUp(self):
        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.path = Path(self._dir.name) / "history.json"

    def test_records_both_windows(self):
        history = SampleHistory(self.path)
        history.record(make_snapshot())

        self.assertEqual(len(history.samples("session")), 1)
        self.assertEqual(history.samples("week")[0][1], 19.0)

    def test_ignores_out_of_order_samples(self):
        history = SampleHistory(self.path)
        history.record(make_snapshot(at=NOW))
        history.record(make_snapshot(at=NOW - timedelta(minutes=5)))

        self.assertEqual(len(history.samples("session")), 1)

    def test_prunes_beyond_retention(self):
        history = SampleHistory(self.path, retention=timedelta(minutes=30))
        history.record(make_snapshot(at=NOW - timedelta(hours=2)))
        history.record(make_snapshot(at=NOW))

        self.assertEqual(len(history.samples("session")), 1)

    def test_caps_the_number_of_samples(self):
        history = SampleHistory(self.path, max_samples=3)
        for index in range(10):
            history.record(make_snapshot(at=NOW + timedelta(minutes=index)))

        self.assertEqual(len(history.samples("session")), 3)

    def test_round_trips_through_disk(self):
        history = SampleHistory(self.path)
        history.record(make_snapshot(at=datetime.now(timezone.utc)))
        self.assertTrue(history.save())

        restored = SampleHistory(self.path)
        restored.load()

        self.assertEqual(len(restored.samples("session")), 1)

    def test_load_survives_corrupt_file(self):
        self.path.write_text("{oops", encoding="utf-8")
        history = SampleHistory(self.path)
        history.load()

        self.assertEqual(history.samples("session"), [])

    def test_load_skips_malformed_entries(self):
        self.path.write_text(
            '{"session": [["nope", 1], [1, 2, 3], ["2026-07-25T18:00:00Z", "x"]]}',
            encoding="utf-8",
        )
        history = SampleHistory(self.path)
        history.load()

        self.assertEqual(history.samples("session"), [])


class ViewModelTest(unittest.TestCase):
    def setUp(self):
        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.history = SampleHistory(Path(self._dir.name) / "h.json")

    def test_builds_rows_for_both_windows(self):
        view = build_card(make_snapshot(), self.history, NOW)

        self.assertEqual([row.key for row in view.rows], ["session", "week"])
        self.assertEqual(view.plan_label, "Team 5x")
        self.assertEqual(view.rows[0].percent_text, "50%")
        self.assertEqual(view.rows[0].resets_text, "Zera em 44m")
        self.assertEqual(view.tray_label, "50%")

    def test_week_row_can_be_hidden(self):
        view = build_card(make_snapshot(), self.history, NOW, show_week=False)

        self.assertEqual([row.key for row in view.rows], ["session"])

    def test_reference_card_matches_the_design(self):
        history = SampleHistory(Path(self._dir.name) / "ref.json")
        history.record(make_snapshot(session_pct=84.0, at=NOW - timedelta(minutes=30)))
        history.record(make_snapshot(session_pct=99.0, at=NOW))

        row = build_card(make_snapshot(session_pct=99.0), history, NOW).rows[0]

        self.assertEqual(row.percent_text, "99%")
        self.assertEqual(row.pace_text, "14% de déficit")
        self.assertEqual(row.resets_text, "Zera em 44m")
        self.assertEqual(row.runs_out_text, "Acaba em 2m")

    def test_placeholder_without_a_snapshot(self):
        view = build_card(None, self.history, NOW, status_text="boom")

        self.assertEqual(view.rows, ())
        self.assertEqual(view.status_text, "boom")
        self.assertEqual(view.tray_label, "—")

    def test_unknown_reset_time(self):
        snapshot = snapshot_from_payload({"five_hour": {"utilization": 5.0}}, NOW)

        row = build_card(snapshot, self.history, NOW).rows[0]

        self.assertEqual(row.resets_text, "Reset desconhecido")
        self.assertIsNone(row.pace_marker)


class SettingsTest(unittest.TestCase):
    def setUp(self):
        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.path = Path(self._dir.name) / "config.json"

    def test_defaults_when_absent(self):
        self.assertEqual(load_settings(self.path), Settings())

    def test_round_trip(self):
        save_settings(Settings(poll_seconds=90, show_week=False), self.path)

        loaded = load_settings(self.path)

        self.assertEqual(loaded.poll_seconds, 90)
        self.assertFalse(loaded.show_week)

    def test_taskbar_flag_round_trips(self):
        self.assertTrue(Settings().show_in_taskbar)
        save_settings(Settings(show_in_taskbar=False), self.path)

        self.assertFalse(load_settings(self.path).show_in_taskbar)

    def test_clamps_a_too_small_interval(self):
        self.path.write_text('{"poll_seconds": 1}', encoding="utf-8")

        self.assertEqual(load_settings(self.path).poll_seconds, MIN_POLL_SECONDS)

    def test_ignores_junk_values(self):
        self.path.write_text(
            '{"poll_seconds": "abc", "always_on_top": "yes", "window_x": "left"}',
            encoding="utf-8",
        )

        loaded = load_settings(self.path)

        self.assertEqual(loaded.poll_seconds, Settings().poll_seconds)
        self.assertTrue(loaded.always_on_top)
        self.assertEqual(loaded.window_x, -1)

    def test_corrupt_file_falls_back(self):
        self.path.write_text("[]", encoding="utf-8")

        self.assertEqual(load_settings(self.path), Settings())


class PollerTest(unittest.TestCase):
    def test_delivers_a_snapshot_then_stops(self):
        done = threading.Event()
        received = []

        def fetcher():
            return make_snapshot()

        def on_result(snapshot):
            received.append(snapshot)
            poller.stop()
            done.set()

        poller = UsagePoller(
            on_result=on_result,
            on_error=lambda message, needs_login: None,
            dispatch=lambda fn: fn(),
            interval_provider=lambda: 60,
            fetcher=fetcher,
        )
        poller.start()

        self.assertTrue(done.wait(5))
        self.assertEqual(len(received), 1)

    def test_reports_usage_errors_with_the_login_flag(self):
        done = threading.Event()
        errors = []

        def fetcher():
            raise UsageError("expired", needs_login=True)

        def on_error(message, needs_login):
            errors.append((message, needs_login))
            poller.stop()
            done.set()

        poller = UsagePoller(
            on_result=lambda snapshot: None,
            on_error=on_error,
            dispatch=lambda fn: fn(),
            interval_provider=lambda: 60,
            fetcher=fetcher,
        )
        poller.start()

        self.assertTrue(done.wait(5))
        self.assertEqual(errors[0], ("expired", True))

    def test_survives_unexpected_exceptions(self):
        done = threading.Event()
        errors = []

        def fetcher():
            raise RuntimeError("kaboom")

        def on_error(message, needs_login):
            errors.append(message)
            poller.stop()
            done.set()

        poller = UsagePoller(
            on_result=lambda snapshot: None,
            on_error=on_error,
            dispatch=lambda fn: fn(),
            interval_provider=lambda: 60,
            fetcher=fetcher,
        )
        poller.start()

        self.assertTrue(done.wait(5))
        self.assertIn("kaboom", errors[0])


if __name__ == "__main__":
    unittest.main()


class ThrottlingTest(unittest.TestCase):
    """Consecutive 429s must back off instead of hammering the endpoint."""

    def _poller(self, fetcher, messages=None):
        return UsagePoller(
            on_result=lambda snapshot: None,
            on_error=lambda message, needs_login: (
                messages.append(message) if messages is not None else None
            ),
            dispatch=lambda fn: fn(),
            interval_provider=lambda: 60,
            fetcher=fetcher,
        )

    def test_backoff_doubles_on_each_consecutive_throttle(self):
        poller = self._poller(
            lambda: (_ for _ in ()).throw(UsageError("devagar", is_throttled=True))
        )

        delays = [poller._poll_once() for _ in range(5)]

        self.assertEqual(delays, [60.0, 120.0, 240.0, 480.0, 960.0])

    def test_backoff_is_capped(self):
        poller = self._poller(
            lambda: (_ for _ in ()).throw(UsageError("devagar", is_throttled=True))
        )

        for _ in range(12):
            delay = poller._poll_once()

        self.assertEqual(delay, THROTTLE_MAX_SECONDS)

    def test_a_success_resets_the_streak(self):
        responses = [
            UsageError("devagar", is_throttled=True),
            UsageError("devagar", is_throttled=True),
            None,
            UsageError("devagar", is_throttled=True),
        ]

        def fetcher():
            item = responses.pop(0)
            if item is not None:
                raise item
            return make_snapshot()

        poller = self._poller(fetcher)
        delays = [poller._poll_once() for _ in range(4)]

        self.assertEqual(delays, [60.0, 120.0, 60.0, 60.0])

    def test_a_longer_server_wait_wins(self):
        poller = self._poller(
            lambda: (_ for _ in ()).throw(
                UsageError("devagar", is_throttled=True, retry_after=600.0)
            )
        )

        self.assertEqual(poller._poll_once(), 600.0)

    def test_message_tells_the_user_when_it_retries(self):
        messages = []
        poller = self._poller(
            lambda: (_ for _ in ()).throw(UsageError("Consultas demais.", is_throttled=True)),
            messages,
        )

        poller._poll_once()

        self.assertEqual(messages[0], "Consultas demais. Nova tentativa em 1m.")

    def test_plain_errors_keep_the_regular_backoff(self):
        poller = self._poller(lambda: (_ for _ in ()).throw(UsageError("falhou")))

        self.assertEqual(poller._poll_once(), 60.0)
