"""Calendar boundaries and empty-history behavior for the website outlook."""

import os
import unittest
from datetime import date

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from web.app import today_rain_outlook  # noqa: E402


class TodayRainOutlookTests(unittest.TestCase):
    def test_year_wrap_and_rain_threshold(self):
        rows = [
            {"weather_date": date(2020, 12, 31), "rainfall_mm": 0.1},
            {"weather_date": date(2021, 1, 1), "rainfall_mm": 0.09},
            {"weather_date": date(2021, 7, 1), "rainfall_mm": 20.0},
        ]
        result = today_rain_outlook(rows, date(2026, 1, 1), 1, date(2025, 12, 31))
        self.assertEqual((result["wet_samples"], result["sample_count"]), (1, 2))
        self.assertEqual(result["probability_pct"], 50)
        self.assertTrue(result["likely_rain"])

    def test_empty_history_does_not_claim_a_forecast(self):
        result = today_rain_outlook([], date(2026, 10, 4), None, date(2026, 9, 26))
        self.assertIsNone(result["probability_pct"])
        self.assertIsNone(result["likely_rain"])


if __name__ == "__main__":
    unittest.main()
