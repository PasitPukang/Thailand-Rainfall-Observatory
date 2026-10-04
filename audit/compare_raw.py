"""Compare every exported hourly row with its archived Open-Meteo JSON payload.

Run from the project root: python audit/compare_raw.py
"""

from __future__ import annotations

import csv
import gzip
import json
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VARIABLES = (
    ("precipitation_mm", "precipitation"),
    ("temperature_c", "temperature_2m"),
    ("relative_humidity_pct", "relative_humidity_2m"),
    ("wind_speed_kmh", "wind_speed_10m"),
)


@lru_cache(maxsize=800)
def annual_raw_file(province_id: int, year: int) -> Path:
    directory = ROOT / "data/raw" / f"province_{province_id:02d}"
    first = date(year, 1, 1)
    matches = list(directory.glob(f"{first}_*.json.gz"))
    if not matches:
        raise FileNotFoundError((province_id, year))
    return max(matches, key=lambda item: item.name)


def raw_file(province_id: int, day: date) -> tuple[Path, date]:
    if day.year == 2026 and day >= date(2026, 9, 26):
        directory = ROOT / "data/raw" / f"province_{province_id:02d}"
        return directory / f"{day}_{day}.json.gz", day
    return annual_raw_file(province_id, day.year), date(day.year, 1, 1)


def main() -> None:
    count = 0
    mismatches = {"time": 0, **{name: 0 for name, _ in VARIABLES}}
    raw_paths = set()
    cached_path = None
    payload = None
    for export in sorted((ROOT / "database/export").glob("fact_weather_hourly_*.csv")):
        with export.open(encoding="utf-8-sig", newline="") as source:
            for row in csv.DictReader(source):
                province_id = int(row["province_id"])
                timestamp = datetime.fromisoformat(row["weather_time"])
                path, start = raw_file(province_id, timestamp.date())
                if path != cached_path:
                    with gzip.open(path, "rt", encoding="utf-8") as source_raw:
                        payload = json.load(source_raw)
                    assert payload["timezone"] == "Asia/Bangkok", path
                    cached_path = path
                    raw_paths.add(path)
                index = (timestamp.date() - start).days * 24 + timestamp.hour
                raw = payload["hourly"]
                mismatches["time"] += raw["time"][index] != timestamp.strftime("%Y-%m-%dT%H:%M")
                for export_name, raw_name in VARIABLES:
                    value = raw[raw_name][index]
                    mismatches[export_name] += value is None or abs(float(row[export_name]) - float(value)) > 1e-8
                count += 1
    print(json.dumps({"compared_hourly_rows": count, "raw_files_used": len(raw_paths),
                      "mismatches": mismatches}, indent=2))


if __name__ == "__main__":
    main()
