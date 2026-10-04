"""Load the published CSV snapshots into an empty PostgreSQL weather database.

This runs once in Docker Compose before the Airflow and dashboard services start.
An existing, populated warehouse is left untouched.
"""

from __future__ import annotations

import os

from sqlalchemy import func, select

from pipeline.core import ROOT, daily, hourly, make_engine


def main() -> None:
    if not os.environ.get("DATABASE_URL", "").startswith("postgresql"):
        raise RuntimeError("DATABASE_URL must point to the PostgreSQL weather database")
    hourly_files = sorted((ROOT / "database/export").glob("fact_weather_hourly_*.csv"))
    daily_file = ROOT / "powerbi/export/mart_weather_daily.csv"
    if not hourly_files or not daily_file.is_file():
        raise RuntimeError("Expected yearly hourly CSV files and the daily Power BI CSV")
    with daily_file.open("r", encoding="utf-8-sig", newline="") as source:
        expected_daily = sum(1 for _ in source) - 1
    engine = make_engine()
    with engine.connect() as conn:
        hourly_rows = conn.execute(select(func.count()).select_from(hourly)).scalar_one()
        daily_rows = conn.execute(select(func.count()).select_from(daily)).scalar_one()
    if hourly_rows and daily_rows:
        if hourly_rows < expected_daily * 24 or daily_rows < expected_daily:
            raise RuntimeError("Warehouse has fewer rows than the published CSV snapshot")
        print(f"Warehouse already populated: {hourly_rows:,} hourly; {daily_rows:,} daily. Skipping seed.", flush=True)
        return
    if hourly_rows or daily_rows:
        raise RuntimeError("Warehouse is partially populated; inspect it before seeding")

    connection = engine.raw_connection()
    total = 0
    try:
        cursor = connection.cursor()
        cursor.execute("""
            CREATE TEMP TABLE seed_hourly (
                province_id integer, province_name text, weather_time timestamp,
                precipitation_mm double precision, temperature_c double precision,
                relative_humidity_pct double precision, wind_speed_kmh double precision,
                source_model text
            ) ON COMMIT DROP
        """)
        for path in hourly_files:
            with path.open("r", encoding="utf-8-sig", newline="") as source:
                cursor.copy_expert("COPY seed_hourly FROM STDIN WITH (FORMAT CSV, HEADER TRUE)", source)
            cursor.execute("""
                INSERT INTO fact_weather_hourly
                    (province_id, weather_time, precipitation_mm, temperature_c,
                     relative_humidity_pct, wind_speed_kmh, source_model)
                SELECT province_id, weather_time, precipitation_mm, temperature_c,
                       relative_humidity_pct, wind_speed_kmh, source_model
                FROM seed_hourly
            """)
            total += cursor.rowcount
            cursor.execute("TRUNCATE seed_hourly")
            print(f"Seeded {path.name}; total {total:,} hourly rows", flush=True)
        with daily_file.open("r", encoding="utf-8-sig", newline="") as source:
            cursor.copy_expert("COPY mart_weather_daily FROM STDIN WITH (FORMAT CSV, HEADER TRUE)", source)
        cursor.execute("SELECT COUNT(*) FROM mart_weather_daily")
        daily_count = cursor.fetchone()[0]
        if daily_count != expected_daily or total != daily_count * 24:
            raise RuntimeError(f"Seed count mismatch: {total:,} hourly; {daily_count:,} daily")
        connection.commit()
        print(f"Warehouse seed complete: {total:,} hourly; {daily_count:,} daily", flush=True)
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
