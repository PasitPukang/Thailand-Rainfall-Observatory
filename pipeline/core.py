from __future__ import annotations

import csv
import gzip
import json
import os
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests
from sqlalchemy import (
    Column, Date, DateTime, Float, ForeignKey, Index, Integer, MetaData, String,
    Table, create_engine, delete, func, select,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert


ROOT = Path(__file__).resolve().parents[1]
PROVINCES_FILE = ROOT / "data" / "provinces.csv"
RAW_DIR = Path(os.getenv("RAW_DIR", str(ROOT / "data" / "raw")))
DB_URL = os.getenv("DATABASE_URL", f"sqlite:///{(ROOT / 'data' / 'weather.sqlite').as_posix()}")
API_URL = "https://archive-api.open-meteo.com/v1/archive"
VARIABLES = ("precipitation", "temperature_2m", "relative_humidity_2m", "wind_speed_10m")
MODEL = "era5"

metadata = MetaData()
province = Table(
    "dim_province", metadata,
    Column("province_id", Integer, primary_key=True),
    Column("province_name", String(100), nullable=False, unique=True),
    Column("latitude", Float, nullable=False),
    Column("longitude", Float, nullable=False),
)
hourly = Table(
    "fact_weather_hourly", metadata,
    Column("province_id", Integer, ForeignKey("dim_province.province_id"), primary_key=True),
    Column("weather_time", DateTime, primary_key=True),
    Column("precipitation_mm", Float),
    Column("temperature_c", Float),
    Column("relative_humidity_pct", Float),
    Column("wind_speed_kmh", Float),
    Column("source_model", String(30), nullable=False),
)
daily = Table(
    "mart_weather_daily", metadata,
    Column("province_id", Integer, ForeignKey("dim_province.province_id"), primary_key=True),
    Column("weather_date", Date, primary_key=True),
    Column("rainfall_mm", Float),
    Column("average_temperature_c", Float),
    Column("maximum_temperature_c", Float),
    Column("average_humidity_pct", Float),
    Column("maximum_wind_kmh", Float),
    Column("observed_hours", Integer, nullable=False),
    Column("rain_class", String(20), nullable=False),
)
batch = Table(
    "etl_batch", metadata,
    Column("province_id", Integer, primary_key=True),
    Column("start_date", Date, primary_key=True),
    Column("end_date", Date, primary_key=True),
    Column("row_count", Integer, nullable=False),
    Column("loaded_at", DateTime, nullable=False),
    Column("raw_path", String(400), nullable=False),
)
run_audit = Table(
    "pipeline_run_audit", metadata,
    Column("run_id", String(250), primary_key=True),
    Column("started_at", DateTime, nullable=False),
    Column("finished_at", DateTime),
    Column("status", String(20), nullable=False),
    Column("target_date", Date),
    Column("new_hourly_rows", Integer, nullable=False, default=0),
    Column("updated_hourly_rows", Integer, nullable=False, default=0),
    Column("new_daily_rows", Integer, nullable=False, default=0),
    Column("message", String(1000)),
)
Index("ix_hourly_weather_time", hourly.c.weather_time)
Index("ix_daily_weather_date", daily.c.weather_date)


def provinces() -> list[dict]:
    with PROVINCES_FILE.open(encoding="utf-8-sig", newline="") as file:
        values = list(csv.DictReader(file))
    if len(values) != 77 or len({int(item["province_id"]) for item in values}) != 77:
        raise ValueError("Expected exactly 77 distinct provinces")
    return [
        {"province_id": int(item["province_id"]), "province_name": item["province_name"],
         "latitude": float(item["latitude"]), "longitude": float(item["longitude"])}
        for item in values
    ]


def make_engine():
    engine = create_engine(DB_URL, future=True)
    metadata.create_all(engine)
    values = provinces()
    with engine.begin() as conn:
        statement = _upsert(conn, province, values, ["province_id"])
        conn.execute(statement)
    return engine


def _upsert(conn, table, values: list[dict], keys: list[str]):
    dialect = conn.dialect.name
    if dialect == "postgresql":
        insert = pg_insert(table).values(values)
    elif dialect == "sqlite":
        insert = sqlite_insert(table).values(values)
    else:
        raise ValueError(f"Unsupported database: {dialect}")
    updates = {c.name: getattr(insert.excluded, c.name) for c in table.columns if c.name not in keys}
    return insert.on_conflict_do_update(index_elements=keys, set_=updates)


def date_windows(start: date, end: date):
    """Inclusive date range split by calendar year for manageable API responses."""
    if start > end:
        raise ValueError("start must be on or before end")
    current = start
    while current <= end:
        last = min(end, date(current.year, 12, 31))
        yield current, last
        current = last + timedelta(days=1)


def fetch(prov: dict, start: date, end: date) -> dict:
    params = {
        "latitude": prov["latitude"], "longitude": prov["longitude"],
        "start_date": start.isoformat(), "end_date": end.isoformat(),
        "hourly": ",".join(VARIABLES), "models": MODEL,
        "timezone": "Asia/Bangkok",
    }
    transient_failures = 0
    rate_limit_waits = 0
    while True:
        try:
            response = requests.get(API_URL, params=params, timeout=120)
            if response.status_code == 429:
                if rate_limit_waits >= 5:
                    response.raise_for_status()
                now = datetime.now(timezone.utc)
                next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1, minutes=2)
                delay = max(60, (next_hour - now).total_seconds())
                print(f"Open-Meteo rate limit; waiting {delay / 60:.0f} minutes", flush=True)
                rate_limit_waits += 1
                time.sleep(delay)
                continue
            response.raise_for_status()
            payload = response.json()
            if payload.get("error"):
                raise ValueError(payload.get("reason", "API error"))
            return payload
        except (requests.Timeout, requests.ConnectionError, requests.HTTPError):
            if transient_failures >= 4:
                raise
            time.sleep(min(60, 2 ** transient_failures * 3))
            transient_failures += 1


def save_raw(payload: dict, province_id: int, start: date, end: date) -> Path:
    target = RAW_DIR / f"province_{province_id:02d}" / f"{start}_{end}.json.gz"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    with gzip.open(temporary, "wt", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, separators=(",", ":"))
    temporary.replace(target)
    return target


def _rows(payload: dict, province_id: int, start: date, end: date) -> list[dict]:
    data = payload.get("hourly", {})
    times = data.get("time", [])
    if not times:
        raise ValueError("API response has no hourly timestamps")
    for name in VARIABLES:
        if len(data.get(name, [])) != len(times):
            raise ValueError(f"Missing or incomplete hourly variable: {name}")
    expected = (end - start).days * 24 + 24
    if len(times) != expected:
        raise ValueError(f"Expected {expected} hourly rows, received {len(times)}")
    if payload.get("timezone") != "Asia/Bangkok":
        raise ValueError("Unexpected API timezone")
    result = []
    for i, timestamp in enumerate(times):
        dt = datetime.fromisoformat(timestamp)
        if not (start <= dt.date() <= end):
            raise ValueError("Timestamp outside requested range")
        rain = data["precipitation"][i]
        if rain is not None and (rain < 0 or rain > 1000):
            raise ValueError("Implausible hourly precipitation value")
        result.append({
            "province_id": province_id, "weather_time": dt,
            "precipitation_mm": rain,
            "temperature_c": data["temperature_2m"][i],
            "relative_humidity_pct": data["relative_humidity_2m"][i],
            "wind_speed_kmh": data["wind_speed_10m"][i],
            "source_model": MODEL,
        })
    if len({r["weather_time"] for r in result}) != expected:
        raise ValueError("Duplicate hourly timestamps")
    return result


def _rain_class(rainfall: float | None, hours: int) -> str:
    if hours != 24 or rainfall is None:
        return "incomplete"
    if rainfall >= 90.1:
        return "very_heavy"
    if rainfall >= 35.1:
        return "heavy"
    return "other"


def refresh_daily(conn, province_id: int, start: date, end: date):
    # Daily sums follow calendar days in Asia/Bangkok, using Open-Meteo's hour labels.
    date_expr = func.date(hourly.c.weather_time)
    query = (
        select(
            date_expr.label("weather_date"),
            func.sum(hourly.c.precipitation_mm).label("rainfall_mm"),
            func.avg(hourly.c.temperature_c).label("average_temperature_c"),
            func.max(hourly.c.temperature_c).label("maximum_temperature_c"),
            func.avg(hourly.c.relative_humidity_pct).label("average_humidity_pct"),
            func.max(hourly.c.wind_speed_kmh).label("maximum_wind_kmh"),
            func.count(hourly.c.precipitation_mm).label("observed_hours"),
        )
        .where(hourly.c.province_id == province_id)
        .where(hourly.c.weather_time >= datetime.combine(start, datetime.min.time()))
        .where(hourly.c.weather_time < datetime.combine(end + timedelta(days=1), datetime.min.time()))
        .group_by(date_expr)
    )
    rows = []
    for item in conn.execute(query).mappings():
        d = item["weather_date"]
        if isinstance(d, str):
            d = date.fromisoformat(d)
        rows.append({
            "province_id": province_id, "weather_date": d,
            "rainfall_mm": item["rainfall_mm"],
            "average_temperature_c": item["average_temperature_c"],
            "maximum_temperature_c": item["maximum_temperature_c"],
            "average_humidity_pct": item["average_humidity_pct"],
            "maximum_wind_kmh": item["maximum_wind_kmh"],
            "observed_hours": item["observed_hours"],
            "rain_class": _rain_class(item["rainfall_mm"], item["observed_hours"]),
        })
    if rows:
        conn.execute(_upsert(conn, daily, rows, ["province_id", "weather_date"]))


def ingest_one(engine, prov: dict, start: date, end: date, force: bool = False) -> int:
    with engine.connect() as conn:
        existing = conn.execute(
            select(batch.c.row_count).where(
                batch.c.province_id == prov["province_id"],
                batch.c.start_date == start, batch.c.end_date == end,
            )
        ).scalar_one_or_none()
    if existing is not None and not force:
        return existing
    payload = fetch(prov, start, end)
    rows = _rows(payload, prov["province_id"], start, end)
    raw_path = save_raw(payload, prov["province_id"], start, end)
    with engine.begin() as conn:
        # Smaller statements keep SQLite's parameter count and PostgreSQL packet size manageable.
        for offset in range(0, len(rows), 250):
            conn.execute(_upsert(conn, hourly, rows[offset:offset + 250], ["province_id", "weather_time"]))
        refresh_daily(conn, prov["province_id"], start, end)
        conn.execute(_upsert(conn, batch, [{
            "province_id": prov["province_id"], "start_date": start, "end_date": end,
            "row_count": len(rows), "loaded_at": datetime.now(), "raw_path": str(raw_path),
        }], ["province_id", "start_date", "end_date"]))
    return len(rows)


def run(start: date, end: date, ids: set[int] | None = None, force: bool = False) -> int:
    engine = make_engine()
    selected = [p for p in provinces() if ids is None or p["province_id"] in ids]
    if not selected:
        raise ValueError("No provinces selected")
    total = 0
    for first, last in date_windows(start, end):
        for prov in selected:
            count = ingest_one(engine, prov, first, last, force)
            total += count
            print(f"province {prov['province_id']:02d} {first} to {last}: {count:,} rows", flush=True)
    return total
