"""Export all hourly PostgreSQL weather rows to one CSV per year."""

from __future__ import annotations

import csv
import os
from pathlib import Path

import psycopg2


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "export"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    password = os.getenv("PGPASSWORD") or os.getenv("POSTGRES_PASSWORD")
    if not password:
        raise RuntimeError("Set PGPASSWORD or POSTGRES_PASSWORD before exporting")
    connection = psycopg2.connect(
        host=os.getenv("PGHOST", "127.0.0.1"),
        port=int(os.getenv("PGPORT", "55432")),
        dbname=os.getenv("PGDATABASE", "weather"),
        user=os.getenv("PGUSER", "airflow"),
        password=password,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT EXTRACT(YEAR FROM weather_time)::int, COUNT(*) "
                "FROM fact_weather_hourly GROUP BY 1 ORDER BY 1"
            )
            expected = dict(cursor.fetchall())

            for year, row_count in expected.items():
                target = OUT / f"fact_weather_hourly_{year}.csv"
                temporary = target.with_suffix(".csv.tmp")
                query = f"""
                    COPY (
                        SELECT h.province_id, p.province_name, h.weather_time,
                               h.precipitation_mm, h.temperature_c,
                               h.relative_humidity_pct, h.wind_speed_kmh,
                               h.source_model
                        FROM fact_weather_hourly AS h
                        JOIN dim_province AS p USING (province_id)
                        WHERE h.weather_time >= DATE '{year}-01-01'
                          AND h.weather_time < DATE '{year + 1}-01-01'
                        ORDER BY h.province_id, h.weather_time
                    ) TO STDOUT WITH (FORMAT CSV, HEADER TRUE, ENCODING 'UTF8')
                """
                with temporary.open("w", encoding="utf-8-sig", newline="") as output:
                    cursor.copy_expert(query, output)

                with temporary.open("r", encoding="utf-8-sig", newline="") as exported:
                    actual = sum(1 for _ in csv.reader(exported)) - 1
                if actual != row_count:
                    temporary.unlink()
                    raise RuntimeError(f"{year}: expected {row_count}, exported {actual}")
                temporary.replace(target)
                print(f"{year}: {actual:,} rows -> {target.name}", flush=True)
    finally:
        connection.close()


if __name__ == "__main__":
    main()
