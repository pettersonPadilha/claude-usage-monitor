import unittest
from datetime import datetime, timedelta, timezone

from claude_usage.config import SESSION_SPAN
from claude_usage.metrics import (
    burn_rate_per_hour,
    elapsed_fraction,
    format_duration,
    format_pace,
    format_percent,
    format_runs_out,
    pace_delta,
    project,
)

NOW = datetime(2026, 7, 25, 18, 0, tzinfo=timezone.utc)


class ElapsedFractionTest(unittest.TestCase):
    def test_returns_none_without_reset_time(self):
        self.assertIsNone(elapsed_fraction(None, NOW, SESSION_SPAN))

    def test_midway_through_a_five_hour_window(self):
        resets = NOW + timedelta(hours=2, minutes=30)

        self.assertAlmostEqual(elapsed_fraction(resets, NOW, SESSION_SPAN), 0.5)

    def test_clamps_when_reset_is_in_the_past(self):
        resets = NOW - timedelta(hours=1)

        self.assertEqual(elapsed_fraction(resets, NOW, SESSION_SPAN), 1.0)

    def test_clamps_when_reset_is_further_away_than_the_span(self):
        resets = NOW + timedelta(hours=9)

        self.assertEqual(elapsed_fraction(resets, NOW, SESSION_SPAN), 0.0)


class PaceDeltaTest(unittest.TestCase):
    def test_matches_the_reference_design(self):
        # 99% used with 44m left in a 5h window is "14% de déficit".
        resets = NOW + timedelta(minutes=44)
        elapsed = elapsed_fraction(resets, NOW, SESSION_SPAN)

        self.assertEqual(format_pace(pace_delta(99.0, elapsed)), "14% de déficit")

    def test_spending_below_the_clock_reads_as_ahead(self):
        self.assertEqual(format_pace(pace_delta(20.0, 0.5)), "30% de folga")

    def test_exactly_on_pace(self):
        self.assertEqual(format_pace(pace_delta(50.0, 0.5)), "no ritmo")

    def test_no_elapsed_means_no_text(self):
        self.assertEqual(format_pace(pace_delta(50.0, None)), "")


class BurnRateTest(unittest.TestCase):
    def test_needs_at_least_two_samples(self):
        self.assertIsNone(burn_rate_per_hour([(NOW, 10.0)], NOW))

    def test_ignores_samples_taken_too_close_together(self):
        samples = [(NOW - timedelta(seconds=10), 10.0), (NOW, 11.0)]

        self.assertIsNone(burn_rate_per_hour(samples, NOW))

    def test_computes_points_per_hour(self):
        samples = [(NOW - timedelta(minutes=30), 10.0), (NOW, 20.0)]

        self.assertAlmostEqual(burn_rate_per_hour(samples, NOW), 20.0)

    def test_discards_samples_before_a_window_reset(self):
        samples = [
            (NOW - timedelta(minutes=40), 95.0),
            (NOW - timedelta(minutes=20), 2.0),  # window reset here
            (NOW, 6.0),
        ]

        self.assertAlmostEqual(burn_rate_per_hour(samples, NOW), 12.0)

    def test_ignores_samples_outside_the_lookback(self):
        samples = [(NOW - timedelta(hours=6), 0.0), (NOW - timedelta(hours=5), 50.0)]

        self.assertIsNone(burn_rate_per_hour(samples, NOW))

    def test_flat_usage_gives_zero_burn(self):
        samples = [(NOW - timedelta(minutes=30), 40.0), (NOW, 40.0)]

        self.assertAlmostEqual(burn_rate_per_hour(samples, NOW), 0.0)


class ProjectionTest(unittest.TestCase):
    def test_projects_the_reference_two_minute_runway(self):
        # 99% used, burning ~30 points/hour -> 1% left is about 2 minutes.
        samples = [(NOW - timedelta(minutes=30), 84.0), (NOW, 99.0)]
        projection = project(99.0, NOW + timedelta(minutes=44), NOW, samples)

        self.assertEqual(format_runs_out(projection), "Acaba em 2m")

    def test_reports_reset_first_when_the_window_ends_sooner(self):
        samples = [(NOW - timedelta(minutes=30), 9.0), (NOW, 10.0)]
        projection = project(10.0, NOW + timedelta(minutes=20), NOW, samples)

        self.assertTrue(projection.resets_first)
        self.assertEqual(format_runs_out(projection), "Zera antes")

    def test_no_burn_means_no_projection(self):
        projection = project(10.0, NOW + timedelta(hours=1), NOW, [])

        self.assertIsNone(projection.time_to_full)
        self.assertEqual(format_runs_out(projection), "Acaba em —")

    def test_already_exhausted(self):
        projection = project(100.0, NOW + timedelta(hours=1), NOW, [])

        self.assertEqual(projection.time_to_full, timedelta(0))
        self.assertEqual(format_runs_out(projection), "Acaba em agora")

    def test_time_to_reset_never_goes_negative(self):
        projection = project(50.0, NOW - timedelta(minutes=5), NOW, [])

        self.assertEqual(projection.time_to_reset, timedelta(0))

    def test_a_burn_of_float_noise_does_not_overflow(self):
        # Percentuais que só variam na última casa decimal davam uma
        # inclinação positiva minúscula, e `timedelta` estourava: o card
        # ficava preso em "Carregando uso…" para sempre.
        samples = [
            (NOW - timedelta(minutes=40 - index * 10), 7.0 + index * 1e-12)
            for index in range(5)
        ]

        projection = project(7.0, NOW + timedelta(days=6), NOW, samples)

        self.assertIsNone(projection.time_to_full)
        self.assertEqual(format_runs_out(projection), "Acaba em —")

    def test_a_projection_past_the_horizon_reads_as_no_projection(self):
        # 0,0015 ponto por hora leva séculos para encher a janela.
        samples = [
            (NOW - timedelta(minutes=40), 10.0),
            (NOW, 10.001),
        ]

        projection = project(10.0, NOW + timedelta(days=6), NOW, samples)

        self.assertIsNone(projection.time_to_full)


class FormattingTest(unittest.TestCase):
    def test_duration_variants(self):
        cases = {
            None: "—",
            timedelta(seconds=0): "agora",
            timedelta(seconds=30): "<1m",
            timedelta(minutes=44): "44m",
            timedelta(hours=3): "3h",
            timedelta(hours=3, minutes=5): "3h 5m",
            timedelta(days=2): "2d",
            timedelta(days=2, hours=4): "2d 4h",
        }
        for delta, expected in cases.items():
            with self.subTest(delta=delta):
                self.assertEqual(format_duration(delta), expected)

    def test_percent_rounds_to_whole_numbers(self):
        self.assertEqual(format_percent(19.0), "19%")
        self.assertEqual(format_percent(None), "—")


if __name__ == "__main__":
    unittest.main()
