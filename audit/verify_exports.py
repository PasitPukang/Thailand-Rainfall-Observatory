"""Recheck exported weather rows and backtest the website's simple estimates.

Run from the project root: python audit/verify_exports.py
The script reads files only and prints JSON; it does not connect to PostgreSQL.
"""

from __future__ import annotations

import calendar
import csv
import json
import statistics
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HISTORY_YEARS = range(2018, 2026)
VALIDATION_YEAR = 2026


def calendar_index(day: date) -> int:
    return date(2000, day.month, day.day).timetuple().tm_yday - 1


def median(values: list[float]) -> float:
    return float(statistics.median(values))


def probabilities(history: dict[tuple[int, int], list[int]], province_id: int,
                  excluded_year: int | None = None) -> tuple[list[float], float]:
    wet = [0] * 366
    observed = [0] * 366
    for year in HISTORY_YEARS:
        if year == excluded_year:
            continue
        for index, value in enumerate(history[(province_id, year)]):
            if value >= 0:
                observed[index] += 1
                wet[index] += value
    result = []
    for index in range(366):
        indices = ((index + offset) % 366 for offset in range(-15, 16))
        days = list(indices)
        positives = sum(wet[i] for i in days)
        samples = sum(observed[i] for i in days)
        result.append((positives + 1) / (samples + 2) if samples else 0.5)
    overall = (sum(wet) + 1) / (sum(observed) + 2)
    return result, overall


def evaluate_wet_days(rows: list[tuple[int, date, float]], history: dict[tuple[int, int], list[int]],
                      excluded_year: int | None) -> dict:
    prediction_cache = {}
    counts = defaultdict(int)
    brier = baseline_brier = 0.0
    for province_id, day, rainfall in rows:
        if province_id not in prediction_cache:
            prediction_cache[province_id] = probabilities(history, province_id, excluded_year)
        predicted, baseline = prediction_cache[province_id]
        p = predicted[calendar_index(day)]
        actual = int(rainfall >= 0.1)
        decision = int(p >= 0.5)
        counts["samples"] += 1
        counts["wet_days"] += actual
        counts["correct"] += decision == actual
        counts["true_positive"] += decision == 1 and actual == 1
        counts["false_positive"] += decision == 1 and actual == 0
        counts["false_negative"] += decision == 0 and actual == 1
        counts["true_negative"] += decision == 0 and actual == 0
        brier += (p - actual) ** 2
        baseline_brier += (baseline - actual) ** 2
    n = counts["samples"]
    tp, fp, fn = (counts[name] for name in ("true_positive", "false_positive", "false_negative"))
    return {
        "samples": n,
        "wet_rate_pct": round(100 * counts["wet_days"] / n, 2),
        "accuracy_pct": round(100 * counts["correct"] / n, 2),
        "always_wet_accuracy_pct": round(100 * counts["wet_days"] / n, 2),
        "always_dry_accuracy_pct": round(100 * (n - counts["wet_days"]) / n, 2),
        "precision_pct": round(100 * tp / (tp + fp), 2) if tp + fp else None,
        "recall_pct": round(100 * tp / (tp + fn), 2) if tp + fn else None,
        "brier_score": round(brier / n, 4),
        "province_base_rate_brier_score": round(baseline_brier / n, 4),
        "confusion": {key: counts[key] for key in (
            "true_positive", "false_positive", "false_negative", "true_negative")},
    }


def main() -> None:
    provinces = {}
    with (ROOT / "data/provinces.csv").open(encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source):
            provinces[int(row["province_id"])] = row["province_name"]
    assert len(provinces) == 77

    daily = {}
    history = defaultdict(lambda: [-1] * 366)
    wet_history_rows = []
    wet_2026_rows = []
    monthly = defaultdict(list)
    daily_findings = defaultdict(int)
    daily_file = ROOT / "powerbi/export/mart_weather_daily.csv"
    with daily_file.open(encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source):
            province_id = int(row["province_id"])
            day = date.fromisoformat(row["weather_date"])
            key = (province_id, day)
            assert key not in daily, f"Duplicate daily key: {key}"
            rainfall = float(row["rainfall_mm"])
            hours = int(row["observed_hours"])
            expected_class = "incomplete" if hours != 24 else (
                "very_heavy" if rainfall >= 90.1 else "heavy" if rainfall >= 35.1 else "other")
            daily_findings["class_mismatch"] += row["rain_class"] != expected_class
            daily_findings["incomplete"] += hours != 24
            daily_findings["negative_rain"] += rainfall < 0
            daily[key] = row
            monthly[(province_id, day.year, day.month)].append(rainfall)
            if day.year in HISTORY_YEARS:
                history[(province_id, day.year)][calendar_index(day)] = int(rainfall >= 0.1)
                wet_history_rows.append((province_id, day, rainfall))
            elif day.year == VALIDATION_YEAR:
                wet_2026_rows.append((province_id, day, rainfall))

    hourly_findings = defaultdict(int)
    aggregates = defaultdict(lambda: [0, 0.0, 0.0, -1000.0, 0.0, -1000.0])
    first = last = None
    for path in sorted((ROOT / "database/export").glob("fact_weather_hourly_*.csv")):
        previous_key = None
        with path.open(encoding="utf-8-sig", newline="") as source:
            for row in csv.DictReader(source):
                province_id = int(row["province_id"])
                timestamp = datetime.fromisoformat(row["weather_time"])
                key = (province_id, timestamp)
                hourly_findings["unsorted_or_duplicate_key"] += previous_key is not None and key <= previous_key
                previous_key = key
                hourly_findings["province_name_mismatch"] += row["province_name"] != provinces[province_id]
                hourly_findings["year_file_mismatch"] += str(timestamp.year) not in path.stem
                hourly_findings["source_model_mismatch"] += row["source_model"] != "era5"
                rain = float(row["precipitation_mm"])
                temp = float(row["temperature_c"])
                humidity = float(row["relative_humidity_pct"])
                wind = float(row["wind_speed_kmh"])
                hourly_findings["out_of_range"] += not (
                    0 <= rain <= 1000 and -100 <= temp <= 70 and
                    0 <= humidity <= 100 and 0 <= wind <= 500)
                metrics = aggregates[(province_id, timestamp.date())]
                metrics[0] += 1
                metrics[1] += rain
                metrics[2] += temp
                metrics[3] = max(metrics[3], temp)
                metrics[4] += humidity
                metrics[5] = max(metrics[5], wind)
                hourly_findings["rows"] += 1
                first = timestamp if first is None or timestamp < first else first
                last = timestamp if last is None or timestamp > last else last
    for key, values in aggregates.items():
        expected = daily.get(key)
        hourly_findings["missing_daily"] += expected is None
        if expected is None:
            continue
        n, rain, temp_sum, temp_max, humidity_sum, wind_max = values
        hourly_findings["incomplete_day"] += n != 24
        hourly_findings["rainfall_mismatch"] += abs(float(expected["rainfall_mm"]) - rain) > 1e-6
        hourly_findings["temperature_mismatch"] += abs(float(expected["average_temperature_c"]) - temp_sum / n) > 1e-6
        hourly_findings["maximum_temperature_mismatch"] += abs(float(expected["maximum_temperature_c"]) - temp_max) > 1e-6
        hourly_findings["humidity_mismatch"] += abs(float(expected["average_humidity_pct"]) - humidity_sum / n) > 1e-6
        hourly_findings["wind_mismatch"] += abs(float(expected["maximum_wind_kmh"]) - wind_max) > 1e-6
    hourly_findings["orphan_daily"] = len(set(daily) - set(aggregates))

    folds = []
    for year in HISTORY_YEARS:
        held_out = [row for row in wet_history_rows if row[1].year == year]
        folds.append(evaluate_wet_days(held_out, history, year))
    out_of_time = evaluate_wet_days(wet_2026_rows, history, None)
    historical_confusion = {name: sum(fold["confusion"][name] for fold in folds)
                            for name in folds[0]["confusion"]}
    historical_n = sum(fold["samples"] for fold in folds)
    historical_correct = historical_confusion["true_positive"] + historical_confusion["true_negative"]
    historical_wet = historical_confusion["true_positive"] + historical_confusion["false_negative"]

    monthly_cv_errors = []
    monthly_2026_errors = []
    monthly_2026_actual = 0.0
    for province_id in provinces:
        for month in range(1, 13):
            totals = [sum(monthly[(province_id, year, month)]) for year in HISTORY_YEARS]
            for index, actual in enumerate(totals):
                monthly_cv_errors.append(abs(actual - median(totals[:index] + totals[index + 1:])))
            if month <= 8:
                actual = sum(monthly[(province_id, 2026, month)])
                monthly_2026_errors.append(abs(actual - median(totals)))
                monthly_2026_actual += actual

    print(json.dumps({
        "daily_csv": {"rows": len(daily), "province_count": len({key[0] for key in daily}),
                      "first": min(day for _, day in daily).isoformat(),
                      "last": max(day for _, day in daily).isoformat(), **daily_findings},
        "hourly_csv": {"rows": hourly_findings["rows"], "day_points": len(aggregates),
                       "first": first.isoformat(), "last": last.isoformat(),
                       **{key: value for key, value in hourly_findings.items() if key != "rows"}},
        "rain_outlook_2018_2025_leave_one_year_out": {
            "samples": historical_n,
            "wet_rate_pct": round(100 * historical_wet / historical_n, 2),
            "accuracy_pct": round(100 * historical_correct / historical_n, 2),
            "always_wet_accuracy_pct": round(100 * historical_wet / historical_n, 2),
            "always_dry_accuracy_pct": round(100 * (historical_n - historical_wet) / historical_n, 2),
            "brier_score": round(sum(f["brier_score"] * f["samples"] for f in folds) / historical_n, 4),
            "confusion": historical_confusion,
        },
        "rain_outlook_2026_out_of_time": out_of_time,
        "monthly_2018_2025_leave_one_year_out": {
            "samples": len(monthly_cv_errors),
            "mae_mm": round(statistics.mean(monthly_cv_errors), 1),
            "median_absolute_error_mm": round(median(monthly_cv_errors), 1),
        },
        "monthly_2026_jan_aug_out_of_time": {
            "samples": len(monthly_2026_errors),
            "mae_mm": round(statistics.mean(monthly_2026_errors), 1),
            "median_absolute_error_mm": round(median(monthly_2026_errors), 1),
            "weighted_absolute_percentage_error_pct": round(100 * sum(monthly_2026_errors) / monthly_2026_actual, 1),
        },
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
