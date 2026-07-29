"""Tests for the threshold alert logic."""

import unittest
from datetime import datetime, timedelta, timezone

from claude_usage.alerts import (
    URGENCY_CRITICAL,
    URGENCY_NORMAL,
    AlertTracker,
)
from claude_usage.model import LimitWindow, UsageSnapshot

NOW = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)
RESET = NOW + timedelta(hours=2)


def window(key, percent, resets_at=RESET):
    label = "Sessão" if key == "session" else "Semana"
    return LimitWindow(key=key, label=label, percent=percent, resets_at=resets_at)


def snapshot(session=None, week=None, fetched_at=NOW):
    return UsageSnapshot(fetched_at=fetched_at, session=session, week=week)


class ThresholdCrossingTests(unittest.TestCase):
    def test_fires_when_percent_reaches_threshold(self):
        # Arrange
        tracker = AlertTracker(threshold=80.0)

        # Act
        alerts = tracker.evaluate(snapshot(session=window("session", 82.0)))

        # Assert
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].key, "session")
        self.assertIn("82%", alerts[0].title)

    def test_fires_exactly_at_the_threshold(self):
        tracker = AlertTracker(threshold=80.0)

        alerts = tracker.evaluate(snapshot(session=window("session", 80.0)))

        self.assertEqual(len(alerts), 1)

    def test_stays_quiet_below_the_threshold(self):
        tracker = AlertTracker(threshold=80.0)

        alerts = tracker.evaluate(snapshot(session=window("session", 79.9)))

        self.assertEqual(alerts, [])

    def test_fires_only_once_while_still_above(self):
        tracker = AlertTracker(threshold=80.0)
        tracker.evaluate(snapshot(session=window("session", 82.0)))

        again = tracker.evaluate(snapshot(session=window("session", 91.0)))

        self.assertEqual(again, [])

    def test_missing_window_is_ignored(self):
        tracker = AlertTracker(threshold=80.0)

        self.assertEqual(tracker.evaluate(snapshot()), [])


class ReArmTests(unittest.TestCase):
    def test_re_arms_when_the_window_resets(self):
        tracker = AlertTracker(threshold=80.0)
        tracker.evaluate(snapshot(session=window("session", 95.0)))

        # A new window: different resets_at, usage back near zero, then high again.
        later = RESET + timedelta(hours=5)
        tracker.evaluate(snapshot(session=window("session", 3.0, resets_at=later)))
        alerts = tracker.evaluate(snapshot(session=window("session", 85.0, resets_at=later)))

        self.assertEqual(len(alerts), 1)

    def test_re_arms_when_percent_drops_below_threshold(self):
        # Some accounts keep resets_at empty; a drop is then the only signal.
        tracker = AlertTracker(threshold=80.0)
        tracker.evaluate(snapshot(session=window("session", 85.0, resets_at=None)))

        tracker.evaluate(snapshot(session=window("session", 10.0, resets_at=None)))
        alerts = tracker.evaluate(snapshot(session=window("session", 88.0, resets_at=None)))

        self.assertEqual(len(alerts), 1)

    def test_new_window_still_above_threshold_fires_again(self):
        tracker = AlertTracker(threshold=80.0)
        tracker.evaluate(snapshot(session=window("session", 95.0)))

        later = RESET + timedelta(hours=5)
        alerts = tracker.evaluate(snapshot(session=window("session", 90.0, resets_at=later)))

        self.assertEqual(len(alerts), 1)


class IndependentWindowTests(unittest.TestCase):
    def test_session_and_week_alert_separately(self):
        tracker = AlertTracker(threshold=80.0)

        alerts = tracker.evaluate(
            snapshot(session=window("session", 81.0), week=window("week", 84.0))
        )

        self.assertEqual({alert.key for alert in alerts}, {"session", "week"})

    def test_week_alert_does_not_silence_session(self):
        tracker = AlertTracker(threshold=80.0)
        tracker.evaluate(snapshot(week=window("week", 84.0)))

        alerts = tracker.evaluate(
            snapshot(session=window("session", 81.0), week=window("week", 85.0))
        )

        self.assertEqual([alert.key for alert in alerts], ["session"])


class UrgencyTests(unittest.TestCase):
    def test_normal_urgency_below_critical(self):
        tracker = AlertTracker(threshold=80.0)

        alerts = tracker.evaluate(snapshot(session=window("session", 82.0)))

        self.assertEqual(alerts[0].urgency, URGENCY_NORMAL)

    def test_critical_urgency_at_ninety(self):
        tracker = AlertTracker(threshold=80.0)

        alerts = tracker.evaluate(snapshot(session=window("session", 93.0)))

        self.assertEqual(alerts[0].urgency, URGENCY_CRITICAL)


class DisabledTests(unittest.TestCase):
    def test_disabled_tracker_never_alerts(self):
        tracker = AlertTracker(threshold=80.0, enabled=False)

        alerts = tracker.evaluate(snapshot(session=window("session", 99.0)))

        self.assertEqual(alerts, [])

    def test_enabling_later_does_not_replay_old_crossings(self):
        # Turning alerts on should not dump a backlog of notifications for
        # crossings that already happened while they were muted.
        tracker = AlertTracker(threshold=80.0, enabled=False)
        tracker.evaluate(snapshot(session=window("session", 99.0)))

        tracker.configure(threshold=80.0, enabled=True)
        alerts = tracker.evaluate(snapshot(session=window("session", 99.0)))

        self.assertEqual(alerts, [])

    def test_enabling_later_still_catches_the_next_crossing(self):
        tracker = AlertTracker(threshold=80.0, enabled=False)
        tracker.evaluate(snapshot(session=window("session", 99.0)))
        tracker.configure(threshold=80.0, enabled=True)

        # New cycle: usage resets, then climbs past the threshold again.
        later = RESET + timedelta(hours=5)
        tracker.evaluate(snapshot(session=window("session", 5.0, resets_at=later)))
        alerts = tracker.evaluate(snapshot(session=window("session", 82.0, resets_at=later)))

        self.assertEqual(len(alerts), 1)


class ConfigureTests(unittest.TestCase):
    def test_lowering_the_threshold_can_fire_again(self):
        tracker = AlertTracker(threshold=90.0)
        self.assertEqual(tracker.evaluate(snapshot(session=window("session", 85.0))), [])

        tracker.configure(threshold=80.0, enabled=True)
        alerts = tracker.evaluate(snapshot(session=window("session", 85.0)))

        self.assertEqual(len(alerts), 1)

    def test_same_threshold_does_not_re_fire(self):
        tracker = AlertTracker(threshold=80.0)
        tracker.evaluate(snapshot(session=window("session", 85.0)))

        tracker.configure(threshold=80.0, enabled=True)
        alerts = tracker.evaluate(snapshot(session=window("session", 85.0)))

        self.assertEqual(alerts, [])


class MessageTests(unittest.TestCase):
    def test_body_mentions_the_reset_countdown(self):
        tracker = AlertTracker(threshold=80.0)

        alerts = tracker.evaluate(snapshot(session=window("session", 82.0)))

        self.assertIn("Zera em", alerts[0].body)

    def test_body_without_reset_time_is_still_useful(self):
        tracker = AlertTracker(threshold=80.0)

        alerts = tracker.evaluate(
            snapshot(session=window("session", 82.0, resets_at=None))
        )

        self.assertTrue(alerts[0].body)

    def test_title_names_the_window(self):
        tracker = AlertTracker(threshold=80.0)

        alerts = tracker.evaluate(snapshot(week=window("week", 84.0)))

        self.assertIn("Semana", alerts[0].title)


if __name__ == "__main__":
    unittest.main()
