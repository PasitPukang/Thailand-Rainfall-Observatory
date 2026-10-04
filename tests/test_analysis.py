"""Check province-point denominators and matched calendar periods."""

import unittest
from datetime import date

from web.analysis import build_trend_analysis


class TrendAnalysisTests(unittest.TestCase):
    def test_same_period_compares_equal_days_and_mean_per_point(self):
        rows = []
        for year in range(2018, 2027):
            for day in (1, 2):
                rows.append({
                    "day": date(year, 1, day), "rainfall": 5.0,
                    "temperature": 28.0, "humidity": 75.0, "wind": 12.0,
                    "province_count": 2,
                    "heavy_points": 2 if year == 2026 else 1,
                    "very_heavy_points": 1 if year == 2026 else 0,
                })
        result = build_trend_analysis(rows, date(2026, 1, 2), all_provinces=True)
        period = result["same_period"]
        self.assertEqual(period["baseline_years"], 8)
        self.assertEqual(period["days"], 2)
        self.assertEqual(period["current"]["heavy_days"], 2.0)
        self.assertEqual(period["historical_median_heavy_days"], 1.0)
        self.assertEqual(period["heavy_change_pct"], 100.0)
        self.assertEqual(period["current"]["very_heavy_days"], 1.0)
        self.assertEqual(result["seasonal_heavy"][0]["heavy_days_per_year"], 1.0)

    def test_leap_day_is_excluded_from_equal_period(self):
        rows = []
        for year in (2024, 2026):
            for month, day in ((2, 28), (3, 1)):
                rows.append({"day": date(year, month, day), "rainfall": 0.0,
                             "temperature": 28.0, "humidity": 75.0, "wind": 12.0,
                             "province_count": 1, "heavy_points": 0, "very_heavy_points": 0})
        rows.append({"day": date(2024, 2, 29), "rainfall": 100.0,
                     "temperature": 28.0, "humidity": 75.0, "wind": 12.0,
                     "province_count": 1, "heavy_points": 1, "very_heavy_points": 1})
        result = build_trend_analysis(rows, date(2026, 3, 1), all_provinces=False)
        self.assertEqual(result["annual"][0]["heavy_days"], 1.0)
        self.assertEqual(result["same_period"]["excluded_feb29"], True)
        self.assertEqual(result["same_period"]["days"], 60)
        self.assertEqual(result["same_period"]["years"], [])


if __name__ == "__main__":
    unittest.main()
