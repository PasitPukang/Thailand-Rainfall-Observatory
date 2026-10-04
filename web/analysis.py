"""Trend summaries for the representative point of each Thai province."""

from __future__ import annotations

import calendar
import statistics
from collections import defaultdict
from datetime import date


BASELINE_YEARS = tuple(range(2018, 2026))


def _blank() -> dict:
    return {"days": 0, "heavy": 0.0, "very_heavy": 0.0, "rain": 0.0,
            "temperature": 0.0, "humidity": 0.0, "wind": 0.0}


def _add(total: dict, row: dict) -> None:
    points = int(row["province_count"])
    if points <= 0:
        raise ValueError("A weather day has no province points")
    total["days"] += 1
    total["heavy"] += int(row["heavy_points"]) / points
    total["very_heavy"] += int(row["very_heavy_points"]) / points
    total["rain"] += float(row["rainfall"])
    total["temperature"] += float(row["temperature"])
    total["humidity"] += float(row["humidity"])
    total["wind"] += float(row["wind"])


def _period_values(total: dict, year: int) -> dict:
    days = total["days"]
    return {
        "year": year,
        "observed_days": days,
        "heavy_days": round(total["heavy"], 2),
        "very_heavy_days": round(total["very_heavy"], 2),
        "rainfall_mm": round(total["rain"], 1),
        "average_temperature_c": round(total["temperature"] / days, 2) if days else None,
        "average_humidity_pct": round(total["humidity"] / days, 2) if days else None,
        "average_daily_max_wind_kmh": round(total["wind"] / days, 2) if days else None,
    }


def build_trend_analysis(rows: list[dict], last_date: date, all_provinces: bool) -> dict:
    """Summarize trends without treating a sum across provinces as national rain."""
    annual = defaultdict(_blank)
    monthly_baseline = defaultdict(_blank)
    matched_period = defaultdict(_blank)

    for row in rows:
        day = row["day"]
        _add(annual[day.year], row)
        if day.year in BASELINE_YEARS:
            _add(monthly_baseline[day.month], row)
        # A leap day would give leap years one extra day in a same-date comparison.
        if (day.month, day.day) != (2, 29) and (day.month, day.day) <= (last_date.month, last_date.day):
            _add(matched_period[day.year], row)

    annual_rows = []
    for year, values in sorted(annual.items()):
        item = _period_values(values, year)
        item["complete"] = values["days"] == 365 + calendar.isleap(year)
        annual_rows.append(item)

    baseline_count = len([year for year in BASELINE_YEARS if year in annual])
    seasonal = [
        {"month": month,
         "heavy_days_per_year": round(monthly_baseline[month]["heavy"] / baseline_count, 2),
         "very_heavy_days_per_year": round(monthly_baseline[month]["very_heavy"] / baseline_count, 2)}
        for month in range(1, 13)
    ] if baseline_count else []

    expected_days = (last_date - date(last_date.year, 1, 1)).days + 1
    if calendar.isleap(last_date.year) and last_date >= date(last_date.year, 2, 29):
        expected_days -= 1
    matched = [_period_values(matched_period[year], year)
               for year in sorted(matched_period) if matched_period[year]["days"] == expected_days]
    reference = [row for row in matched if row["year"] in BASELINE_YEARS]
    current = next((row for row in matched if row["year"] == last_date.year), None)
    median_heavy = statistics.median(matched_period[row["year"]]["heavy"] for row in reference) if reference else None
    median_rain = statistics.median(matched_period[row["year"]]["rain"] for row in reference) if reference else None
    current_heavy = matched_period[last_date.year]["heavy"] if current else None
    return {
        "basis": "mean_per_province_point" if all_provinces else "one_province_point",
        "rain_day_definition": "API hourly labels 00:00–23:00 Asia/Bangkok; precipitation is preceding-hour sum",
        "annual": annual_rows,
        "seasonal_heavy": seasonal,
        "same_period": {
            "through": last_date.strftime("%m-%d"),
            "excluded_feb29": True,
            "days": expected_days,
            "baseline_years": len(reference),
            "current_year": last_date.year,
            "current": current,
            "historical_median_heavy_days": round(median_heavy, 2) if median_heavy is not None else None,
            "historical_median_rainfall_mm": round(median_rain, 1) if median_rain is not None else None,
            "heavy_change_pct": round((current_heavy / median_heavy - 1) * 100, 1)
            if current_heavy is not None and median_heavy else None,
            "years": matched,
        },
    }
