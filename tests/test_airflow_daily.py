import copy
import gzip
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, select

from pipeline import airflow_daily
from pipeline.airflow_daily import _raw_path, cleanse_payload, plan_missing_days
from pipeline.core import daily, hourly, metadata, province


class DailyCleansingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with gzip.open(_raw_path(1, date(2026, 9, 25)), "rt", encoding="utf-8") as source:
            cls.payload = json.load(source)

    def test_real_day_has_24_clean_rows(self):
        rows = cleanse_payload(self.payload, 1, date(2026, 9, 25))
        self.assertEqual(len(rows), 24)
        self.assertEqual(rows[0]["province_id"], 1)
        self.assertIsInstance(rows[0]["precipitation_mm"], float)

    def test_missing_weather_value_fails_before_load(self):
        payload = copy.deepcopy(self.payload)
        payload["hourly"]["temperature_2m"][0] = None
        with self.assertRaisesRegex(ValueError, "Missing or invalid temperature_c"):
            cleanse_payload(payload, 1, date(2026, 9, 25))

    def test_duplicate_hour_fails_before_load(self):
        payload = copy.deepcopy(self.payload)
        payload["hourly"]["time"][1] = payload["hourly"]["time"][0]
        with self.assertRaisesRegex(ValueError, "Duplicate hourly timestamps"):
            cleanse_payload(payload, 1, date(2026, 9, 25))

    def test_existing_data_creates_no_work(self):
        engine = create_engine("sqlite:///:memory:", future=True)
        metadata.create_all(engine)
        with engine.begin() as conn:
            conn.execute(province.insert(), [
                {"province_id": number, "province_name": str(number), "latitude": 13.0, "longitude": 100.0}
                for number in range(1, 78)
            ])
            conn.execute(daily.insert(), [
                {"province_id": number, "weather_date": date(2026, 9, 25), "observed_hours": 24, "rain_class": "other"}
                for number in range(1, 78)
            ])
        with patch.object(airflow_daily, "make_engine", return_value=engine):
            plan = plan_missing_days(date(2026, 10, 2))
        self.assertEqual(plan["days"], 0)
        self.assertEqual(plan["target"], "2026-09-25")

    def test_load_counts_new_rows_then_updates_without_duplicates(self):
        engine = create_engine("sqlite:///:memory:", future=True)
        metadata.create_all(engine)
        with engine.begin() as conn:
            conn.execute(province.insert().values(
                province_id=1, province_name="Test", latitude=13.0, longitude=100.0,
            ))
        rows = cleanse_payload(self.payload, 1, date(2026, 9, 25))
        plan = {"first": "2026-09-25", "target": "2026-09-25", "days": 1}
        with tempfile.TemporaryDirectory() as directory:
            cleaned = Path(directory) / "day.json.gz"
            with gzip.open(cleaned, "wt", encoding="utf-8") as output:
                json.dump([{**row, "weather_time": row["weather_time"].isoformat()} for row in rows], output)
            with patch.object(airflow_daily, "make_engine", return_value=engine), \
                 patch.object(airflow_daily, "provinces", return_value=[{"province_id": 1}]), \
                 patch.object(airflow_daily, "_clean_path", return_value=cleaned):
                first = airflow_daily.load_postgres(plan)
                second = airflow_daily.load_postgres(plan)
        self.assertEqual(first, {"new_hourly_rows": 24, "updated_hourly_rows": 0, "new_daily_rows": 1})
        self.assertEqual(second, {"new_hourly_rows": 0, "updated_hourly_rows": 24, "new_daily_rows": 0})
        with engine.connect() as conn:
            self.assertEqual(len(conn.execute(select(hourly)).all()), 24)
            self.assertEqual(len(conn.execute(select(daily)).all()), 1)


if __name__ == "__main__":
    unittest.main()
