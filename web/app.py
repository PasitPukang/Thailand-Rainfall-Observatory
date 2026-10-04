"""Local, read-only dashboard for the Thailand rainfall project."""

from __future__ import annotations

import calendar
import os
import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import Flask, abort, jsonify, render_template, request, send_file
from sqlalchemy import create_engine, text


ROOT = Path(os.getenv("PROJECT_ROOT", Path(__file__).resolve().parents[1]))
engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
app = Flask(__name__)

DOWNLOADS = {
    "daily_csv": ROOT / "powerbi/export/mart_weather_daily.csv",
    "provinces_csv": ROOT / "powerbi/export/dim_province.csv",
    "powerbi": ROOT / "powerbi/Thailand_Rainfall_2018_2026.pbix",
    "project_guide": ROOT / "README.md",
    "design": ROOT / "DESIGN.md",
    "database_guide": ROOT / "database/README_TH.md",
    "powerbi_guide": ROOT / "powerbi/README.md",
    "web_guide": ROOT / "web/README_TH.md",
}


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * q
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def next_month(year: int, month: int, offset: int) -> tuple[int, int]:
    index = year * 12 + month - 1 + offset
    return index // 12, index % 12 + 1


def today_rain_outlook(rows: list[dict], today: date, selected_province_id: int | None,
                       last_date: date) -> dict:
    """Historical wet-day frequency near today's calendar date, not a live forecast."""
    target_day = date(2000, today.month, today.day).timetuple().tm_yday
    selected = []
    for row in rows:
        day = row["weather_date"]
        sample_day = date(2000, day.month, day.day).timetuple().tm_yday
        distance = abs(sample_day - target_day)
        if min(distance, 366 - distance) <= 15:
            selected.append(row)
    wet = sum(float(row["rainfall_mm"] or 0) >= 0.1 for row in selected)
    total = len(selected)
    probability = (wet + 1) / (total + 2) if total else None
    return {
        "date": today.isoformat(),
        "probability_pct": round(probability * 100) if probability is not None else None,
        "likely_rain": probability >= 0.5 if probability is not None else None,
        "wet_samples": wet,
        "sample_count": total,
        "window_days": 15,
        "rain_threshold_mm": 0.1,
        "history_start_year": 2018,
        "history_end_year": 2025,
        "basis": "one_province_point" if selected_province_id is not None else "mean_province_point",
        "historical_data_through": last_date.isoformat(),
        "historical_lag_days": (today - last_date).days,
    }


def forecast(daily_rows: list[dict], last_date: date) -> dict:
    monthly = defaultdict(lambda: {"rain": 0.0, "days": 0})
    for row in daily_rows:
        day = row["day"]
        if day.year > 2025:
            continue
        item = monthly[(day.year, day.month)]
        item["rain"] += float(row["rainfall"] or 0)
        item["days"] += 1

    history = defaultdict(list)
    for (year, month), values in monthly.items():
        if values["days"] == calendar.monthrange(year, month)[1]:
            history[month].append(round(values["rain"], 2))

    estimates = []
    for offset in range(1, 4):
        year, month = next_month(last_date.year, last_date.month, offset)
        samples = history[month]
        if len(samples) < 5:
            continue
        loo_errors = [
            abs(value - statistics.median(samples[:i] + samples[i + 1:]))
            for i, value in enumerate(samples)
        ]
        estimates.append({
            "year": year,
            "month": month,
            "label": f"{calendar.month_abbr[month]} {year}",
            "estimate_mm": round(statistics.median(samples), 1),
            "low_mm": round(percentile(samples, 0.1), 1),
            "high_mm": round(percentile(samples, 0.9), 1),
            "backtest_mae_mm": round(statistics.mean(loo_errors), 1),
            "history_years": len(samples),
        })
    climatology = [
        {"month": month, "rainfall_mm": round(statistics.median(history[month]), 1)}
        for month in range(1, 13) if history[month]
    ]
    return {"months": estimates, "climatology": climatology}


def file_inventory() -> list[dict]:
    groups = [
        ("ข้อมูลดิบจาก Open-Meteo", ROOT / "data/raw", "*.json.gz"),
        ("ข้อมูลที่ผ่านการตรวจและทำความสะอาด", ROOT / "data/cleaned", "*.json.gz"),
        ("ไฟล์สำหรับ Power BI", ROOT / "powerbi/export", "*.csv"),
        ("ไฟล์รายชั่วโมงแยกตามปี", ROOT / "database/export", "*.csv"),
    ]
    result = []
    for label, directory, pattern in groups:
        files = list(directory.rglob(pattern)) if directory.exists() else []
        result.append({
            "label": label,
            "path": str(directory.relative_to(ROOT)).replace("\\", "/"),
            "count": len(files),
            "size_mb": round(sum(path.stat().st_size for path in files) / 1048576, 1),
        })
    return result


def run_json(row: dict) -> dict:
    utc = row["finished_at"].replace(tzinfo=timezone.utc)
    return {
        **row,
        "target_date": row["target_date"].isoformat(),
        "finished_at": utc.isoformat(),
        "finished_at_th": utc.astimezone(ZoneInfo("Asia/Bangkok")).strftime("%Y-%m-%d %H:%M"),
    }


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/dashboard")
def dashboard():
    province_id = request.args.get("province_id", type=int)
    today = datetime.now(ZoneInfo("Asia/Bangkok")).date()
    neighbor_months = ((today.month - 2) % 12 + 1, today.month, today.month % 12 + 1)
    with engine.connect() as conn:
        provinces = [dict(row) for row in conn.execute(text(
            "SELECT province_id, province_name FROM dim_province ORDER BY province_name"
        )).mappings()]
        valid_ids = {item["province_id"] for item in provinces}
        if province_id is not None and province_id not in valid_ids:
            abort(400, "Unknown province")

        if province_id is None:
            daily_rows = [dict(row) for row in conn.execute(text("""
                SELECT weather_date AS day, AVG(rainfall_mm) AS rainfall,
                       AVG(average_temperature_c) AS temperature,
                       COUNT(*) AS province_count
                FROM mart_weather_daily
                GROUP BY weather_date ORDER BY weather_date
            """)).mappings()]
        else:
            daily_rows = [dict(row) for row in conn.execute(text("""
                SELECT weather_date AS day, rainfall_mm AS rainfall,
                       average_temperature_c AS temperature,
                       1 AS province_count
                FROM mart_weather_daily WHERE province_id = :province_id
                ORDER BY weather_date
            """), {"province_id": province_id}).mappings()]

        counts = dict(conn.execute(text("""
            SELECT (SELECT COUNT(*) FROM fact_weather_hourly) AS hourly_rows,
                   (SELECT COUNT(*) FROM mart_weather_daily) AS daily_rows,
                   (SELECT COUNT(*) FROM dim_province) AS province_count
        """)).mappings().one())
        runs = [dict(row) for row in conn.execute(text("""
            SELECT run_id, status, target_date, new_hourly_rows,
                   updated_hourly_rows, new_daily_rows, finished_at
            FROM pipeline_run_audit ORDER BY finished_at DESC LIMIT 10
        """)).mappings()]
        ranking = [dict(row) for row in conn.execute(text("""
            SELECT p.province_name, COUNT(*) FILTER (WHERE d.rain_class IN ('heavy', 'very_heavy')) AS heavy_days,
                   ROUND(SUM(d.rainfall_mm)::numeric, 1) AS rainfall_mm
            FROM mart_weather_daily d JOIN dim_province p USING (province_id)
            GROUP BY p.province_name ORDER BY heavy_days DESC, p.province_name LIMIT 10
        """)).mappings()]
        history_rain = [dict(row) for row in conn.execute(text("""
            SELECT weather_date, rainfall_mm FROM mart_weather_daily
            WHERE weather_date >= DATE '2018-01-01'
              AND weather_date < DATE '2026-01-01'
              AND (:province_id IS NULL OR province_id = :province_id)
              AND EXTRACT(MONTH FROM weather_date) IN (:month_a, :month_b, :month_c)
        """), {
            "province_id": province_id,
            "month_a": neighbor_months[0],
            "month_b": neighbor_months[1],
            "month_c": neighbor_months[2],
        }).mappings()]

    if not daily_rows:
        abort(503, "No daily weather data")
    last_date = daily_rows[-1]["day"]
    cutoff = last_date - timedelta(days=29)
    recent = [row for row in daily_rows if row["day"] >= cutoff]
    annual = defaultdict(float)
    for row in daily_rows:
        annual[row["day"].year] += float(row["rainfall"] or 0)
    latest_year = last_date.year
    result = {
        "provinces": provinces,
        "selected_province_id": province_id,
        "selected_name": next((p["province_name"] for p in provinces if p["province_id"] == province_id), "เฉลี่ย 77 จุดตัวแทน"),
        "last_date": last_date.isoformat(),
        "counts": counts,
        "latest_run": run_json(runs[0]) if runs else None,
        "runs": [run_json(row) for row in runs],
        "kpis": {
            "rain_last_30_mm": round(sum(float(row["rainfall"] or 0) for row in recent), 1),
            "rain_ytd_mm": round(annual[latest_year], 1),
            "max_day_last_30_mm": round(max(float(row["rainfall"] or 0) for row in recent), 1),
            "avg_temp_last_30_c": round(statistics.mean(float(row["temperature"] or 0) for row in recent), 1),
        },
        "recent": [{"date": row["day"].isoformat(), "rainfall_mm": round(float(row["rainfall"] or 0), 2)} for row in recent],
        "annual": [{"year": year, "rainfall_mm": round(value, 1), "complete": year < latest_year} for year, value in sorted(annual.items())],
        "ranking": [{**row, "heavy_days": int(row["heavy_days"]), "rainfall_mm": float(row["rainfall_mm"])} for row in ranking],
        "forecast": forecast(daily_rows, last_date),
        "today_rain": today_rain_outlook(history_rain, today, province_id, last_date),
        "files": file_inventory(),
    }
    response = jsonify(result)
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/download/<key>")
def download(key: str):
    path = DOWNLOADS.get(key)
    if path is None or not path.is_file():
        abort(404)
    return send_file(path, as_attachment=True, download_name=path.name)


@app.get("/health")
def health():
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok"}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8090)
