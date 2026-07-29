import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from claude_usage.credentials import (
    CredentialsError,
    load_credentials,
    plan_label,
)
from claude_usage.model import (
    SEVERITY_CRITICAL,
    SEVERITY_NORMAL,
    SEVERITY_WARNING,
    parse_timestamp,
    severity_for,
    snapshot_from_payload,
)

NOW = datetime(2026, 7, 25, 18, 0, tzinfo=timezone.utc)

PAYLOAD = {
    "five_hour": {
        "utilization": 0.0,
        "resets_at": "2026-07-25T23:29:59.063048+00:00",
    },
    "seven_day": {
        "utilization": 19.0,
        "resets_at": "2026-07-30T23:59:59.063067+00:00",
    },
    "limits": [
        {"kind": "session", "percent": 0, "severity": "normal"},
        {"kind": "weekly_all", "percent": 19, "severity": "normal"},
    ],
}


class TimestampTest(unittest.TestCase):
    def test_parses_offset_form(self):
        parsed = parse_timestamp("2026-07-25T23:29:59.063048+00:00")

        self.assertEqual(parsed, datetime(2026, 7, 25, 23, 29, 59, 63048, timezone.utc))

    def test_parses_zulu_form(self):
        self.assertEqual(
            parse_timestamp("2026-07-25T23:29:59Z"),
            datetime(2026, 7, 25, 23, 29, 59, tzinfo=timezone.utc),
        )

    def test_rejects_garbage(self):
        for value in (None, "", "not-a-date", 17):
            with self.subTest(value=value):
                self.assertIsNone(parse_timestamp(value))


class SeverityTest(unittest.TestCase):
    def test_thresholds(self):
        self.assertEqual(severity_for(10.0), SEVERITY_NORMAL)
        self.assertEqual(severity_for(80.0), SEVERITY_WARNING)
        self.assertEqual(severity_for(95.0), SEVERITY_CRITICAL)

    def test_api_severity_wins_when_harsher(self):
        payload = dict(PAYLOAD)
        payload["limits"] = [{"kind": "session", "severity": "critical"}]

        snapshot = snapshot_from_payload(payload, NOW)

        self.assertEqual(snapshot.session.severity, SEVERITY_CRITICAL)

    def test_local_severity_wins_when_harsher(self):
        payload = {
            "five_hour": {"utilization": 97.0, "resets_at": None},
            "limits": [{"kind": "session", "severity": "normal"}],
        }

        snapshot = snapshot_from_payload(payload, NOW)

        self.assertEqual(snapshot.session.severity, SEVERITY_CRITICAL)


class SnapshotTest(unittest.TestCase):
    def test_parses_both_windows(self):
        snapshot = snapshot_from_payload(PAYLOAD, NOW, "Team 5x")

        self.assertEqual(snapshot.session.percent, 0.0)
        self.assertEqual(snapshot.session.label, "Sessão")
        self.assertEqual(snapshot.week.percent, 19.0)
        self.assertEqual(snapshot.plan_label, "Team 5x")
        self.assertEqual(snapshot.window("week"), snapshot.week)

    def test_missing_blocks_become_none(self):
        snapshot = snapshot_from_payload({}, NOW)

        self.assertIsNone(snapshot.session)
        self.assertIsNone(snapshot.week)

    def test_null_utilization_is_not_a_window(self):
        snapshot = snapshot_from_payload({"five_hour": {"utilization": None}}, NOW)

        self.assertIsNone(snapshot.session)

    def test_remaining_and_exhausted(self):
        snapshot = snapshot_from_payload({"five_hour": {"utilization": 100.0}}, NOW)

        self.assertTrue(snapshot.session.is_exhausted)
        self.assertEqual(snapshot.session.remaining_percent, 0.0)


class PlanLabelTest(unittest.TestCase):
    def test_reference_badge(self):
        self.assertEqual(plan_label("team", "default_claude_max_5x"), "Team 5x")

    def test_max_twenty(self):
        self.assertEqual(plan_label("max", "default_claude_max_20x"), "Max 20x")

    def test_unknown_subscription_is_titled(self):
        self.assertEqual(plan_label("some_plan", ""), "Some Plan")

    def test_falls_back_to_claude(self):
        self.assertEqual(plan_label("", ""), "Claude")


class LoadCredentialsTest(unittest.TestCase):
    def _write(self, payload) -> Path:
        path = Path(self._dir.name) / ".credentials.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def setUp(self):
        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)

    def test_reads_token_and_plan(self):
        path = self._write(
            {
                "claudeAiOauth": {
                    "accessToken": "secret",
                    "subscriptionType": "team",
                    "rateLimitTier": "default_claude_max_5x",
                    "expiresAt": 1785033565572,
                }
            }
        )

        credentials = load_credentials(path)

        self.assertEqual(credentials.access_token, "secret")
        self.assertEqual(credentials.plan_label, "Team 5x")
        self.assertIsNotNone(credentials.expires_at)

    def test_missing_file(self):
        with self.assertRaises(CredentialsError):
            load_credentials(Path(self._dir.name) / "nope.json")

    def test_missing_oauth_block(self):
        with self.assertRaises(CredentialsError):
            load_credentials(self._write({"other": {}}))

    def test_missing_token(self):
        with self.assertRaises(CredentialsError):
            load_credentials(self._write({"claudeAiOauth": {"subscriptionType": "pro"}}))

    def test_invalid_json(self):
        path = Path(self._dir.name) / "bad.json"
        path.write_text("{not json", encoding="utf-8")

        with self.assertRaises(CredentialsError):
            load_credentials(path)

    def test_expiry_flag(self):
        past = self._write(
            {"claudeAiOauth": {"accessToken": "t", "expiresAt": 1_000_000_000_000}}
        )

        self.assertTrue(load_credentials(past).is_expired)

    def test_bad_expiry_is_ignored(self):
        path = self._write({"claudeAiOauth": {"accessToken": "t", "expiresAt": "soon"}})

        credentials = load_credentials(path)

        self.assertIsNone(credentials.expires_at)
        self.assertFalse(credentials.is_expired)


if __name__ == "__main__":
    unittest.main()
