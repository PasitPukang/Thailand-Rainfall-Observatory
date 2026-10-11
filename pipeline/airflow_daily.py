"""Small, repeatable stages used by the daily Airflow DAG."""

from __future__ import annotations

import gzip
import json
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from sqlalchemy import Integer, func, select

from .core import (
    MODEL, PROVISIONAL_MODEL, RAW_DIR, ROOT, _rows, _upsert, batch, daily, fetch,
    hourly, make_engine, provinces, refresh_daily, run_audit, save_raw,
)

CLEAN_DIR = ROOT / "data" / "cleaned"
# Provisional responses are replaced by ERA5 within about a week, so they are not kept in git.
PROVISIONAL_DIR = ROOT / "data" / "provisional"


def plan_missing_days(today: date) -> dict:
    """Plan every day after the saved data, plus saved days still waiting for ERA5.

    Stops at yesterday: today's later hours would still be forecasts.
    """
    target = today - timedelta(days=1)
    engine = make_engine()
    with engine.connect() as conn:
        latest = {province_id: last_day for province_id, last_day in conn.execute(
            select(daily.c.province_id, func.max(daily.c.weather_date))
            .group_by(daily.c.province_id)
        )}
        first = min(latest.values()) + timedelta(days=1) if len(latest) == 77 else target
        # Provisional rows only sit in the last few days, so a bounded scan uses the time index.
        provisional_from = conn.execute(select(func.min(hourly.c.weather_time)).where(
            hourly.c.weather_time >= datetime.combine(first - timedelta(days=60), time.min),
            hourly.c.source_model != MODEL,
        )).scalar_one()
    if isinstance(provisional_from, str):
        provisional_from = datetime.fromisoformat(provisional_from)
    if provisional_from is not None:
        first = min(first, provisional_from.date())
    return {
        "first": first.isoformat(),
        "target": target.isoformat(),
        "days": max(0, (target - first).days + 1),
    }


def _days(plan: dict):
    first, target = date.fromisoformat(plan["first"]), date.fromisoformat(plan["target"])
    for offset in range(plan["days"]):
        yield first + timedelta(days=offset)


def _raw_path(province_id: int, day: date) -> Path:
    return RAW_DIR / f"province_{province_id:02d}" / f"{day}_{day}.json.gz"


def _clean_path(province_id: int, day: date) -> Path:
    return CLEAN_DIR / f"province_{province_id:02d}" / f"{day}.json.gz"


def _provisional_path(province_id: int, day: date) -> Path:
    return PROVISIONAL_DIR / f"province_{province_id:02d}" / f"{day}.json.gz"


def _source(province_id: int, day: date) -> tuple[Path, str]:
    """ERA5 when its raw file exists, otherwise the provisional response."""
    era5 = _raw_path(province_id, day)
    return (era5, MODEL) if era5.exists() else (_provisional_path(province_id, day), PROVISIONAL_MODEL)


def _complete(payload: dict, province_id: int, day: date) -> bool:
    try:
        cleanse_payload(payload, province_id, day)
    except ValueError:
        return False
    return True


def _era5_available_through(prov: dict, first: date, target: date) -> date:
    """Last day of an unbroken run of complete ERA5 days from first (first - 1 if none)."""
    payload = fetch(prov, first, target)
    hours = payload.get("hourly", {})
    last = first - timedelta(days=1)
    for offset in range((target - first).days + 1):
        day = first + timedelta(days=offset)
        span = slice(offset * 24, offset * 24 + 24)
        day_payload = {**payload, "hourly": {name: values[span] for name, values in hours.items()}}
        if not _complete(day_payload, prov["province_id"], day):
            break
        last = day
    return last


def _write_gz(payload: dict, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    with gzip.open(temporary, "wt", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, separators=(",", ":"))
    temporary.replace(target)


def extract_raw(plan: dict) -> dict:
    """Save ERA5 where it is complete; otherwise refresh the provisional response."""
    fetched = reused = provisional = 0
    days = list(_days(plan))
    all_provinces = provinces()
    era5_through = _era5_available_through(all_provinces[0], days[0], days[-1]) if days else None
    if days:
        fetched += 1
    for day in days:
        for prov in all_provinces:
            province_id = prov["province_id"]
            stale = _provisional_path(province_id, day)
            if _raw_path(province_id, day).exists():
                reused += 1
                stale.unlink(missing_ok=True)
                continue
            if day <= era5_through:
                payload = fetch(prov, day, day)
                fetched += 1
                if _complete(payload, province_id, day):
                    save_raw(payload, province_id, day, day)
                    stale.unlink(missing_ok=True)
                    continue
            _write_gz(fetch(prov, day, day, PROVISIONAL_MODEL), stale)
            fetched += 1
            provisional += 1
    return {
        "api_requests": fetched,
        "reused_raw_files": reused,
        "provisional_files": provisional,
        "era5_through": era5_through.isoformat() if era5_through else None,
    }


def _normalise(value, name: str, minimum: float, maximum: float) -> float:
    if value is None or isinstance(value, bool):
        raise ValueError(f"Missing or invalid {name}")
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"Non-numeric {name}: {value!r}") from error
    if not minimum <= number <= maximum:
        raise ValueError(f"Out-of-range {name}: {number}")
    return number


def cleanse_payload(payload: dict, province_id: int, day: date, model: str = MODEL) -> list[dict]:
    rows = _rows(payload, province_id, day, day, model)
    for row in rows:
        row["precipitation_mm"] = _normalise(row["precipitation_mm"], "precipitation_mm", 0, 1000)
        row["temperature_c"] = _normalise(row["temperature_c"], "temperature_c", -100, 70)
        row["relative_humidity_pct"] = _normalise(row["relative_humidity_pct"], "relative_humidity_pct", 0, 100)
        row["wind_speed_kmh"] = _normalise(row["wind_speed_kmh"], "wind_speed_kmh", 0, 500)
    return rows


def cleanse_data(plan: dict) -> dict:
    cleaned_rows = provisional_rows = 0
    for day in _days(plan):
        for prov in provinces():
            province_id = prov["province_id"]
            path, model = _source(province_id, day)
            with gzip.open(path, "rt", encoding="utf-8") as source:
                payload = json.load(source)
            rows = cleanse_payload(payload, province_id, day, model)
            if model != MODEL:
                provisional_rows += len(rows)
            target = _clean_path(province_id, day)
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix(".tmp")
            with gzip.open(temporary, "wt", encoding="utf-8") as output:
                json.dump([{**row, "weather_time": row["weather_time"].isoformat()} for row in rows], output)
            temporary.replace(target)
            cleaned_rows += len(rows)
    expected = plan["days"] * 77 * 24
    if cleaned_rows != expected:
        raise ValueError(f"Cleansed {cleaned_rows:,} rows; expected {expected:,}")
    return {"cleaned_rows": cleaned_rows, "rejected_rows": 0, "provisional_rows": provisional_rows}


def load_postgres(plan: dict) -> dict:
    engine = make_engine()
    new_hourly = updated_hourly = new_daily = 0
    for day in _days(plan):
        for prov in provinces():
            province_id = prov["province_id"]
            with gzip.open(_clean_path(province_id, day), "rt", encoding="utf-8") as source:
                rows = json.load(source)
            rows = [{**row, "weather_time": datetime.fromisoformat(row["weather_time"])} for row in rows]
            if len(rows) != 24:
                raise ValueError(f"Cleaned file is incomplete for province {province_id}, {day}")
            beginning = datetime.combine(day, time.min)
            ending = beginning + timedelta(days=1)
            with engine.begin() as conn:
                existing_hourly = conn.execute(select(func.count()).select_from(hourly).where(
                    hourly.c.province_id == province_id,
                    hourly.c.weather_time >= beginning,
                    hourly.c.weather_time < ending,
                )).scalar_one()
                existing_daily = conn.execute(select(func.count()).select_from(daily).where(
                    daily.c.province_id == province_id, daily.c.weather_date == day,
                )).scalar_one()
                conn.execute(_upsert(conn, hourly, rows, ["province_id", "weather_time"]))
                refresh_daily(conn, province_id, day, day)
                conn.execute(_upsert(conn, batch, [{
                    "province_id": province_id,
                    "start_date": day,
                    "end_date": day,
                    "row_count": 24,
                    "loaded_at": datetime.now(timezone.utc).replace(tzinfo=None),
                    "raw_path": str(_source(province_id, day)[0]),
                }], ["province_id", "start_date", "end_date"]))
            new_hourly += 24 - existing_hourly
            updated_hourly += existing_hourly
            new_daily += 1 - existing_daily
    return {
        "new_hourly_rows": new_hourly,
        "updated_hourly_rows": updated_hourly,
        "new_daily_rows": new_daily,
    }


def validate_postgres(plan: dict) -> dict:
    expected = plan["days"] * 77 * 24
    if not expected:
        return {"validated_hourly_rows": 0, "validated_daily_rows": 0}
    first = date.fromisoformat(plan["first"])
    target = date.fromisoformat(plan["target"])
    with make_engine().connect() as conn:
        hourly_count = conn.execute(select(func.count()).select_from(hourly).where(
            hourly.c.weather_time >= datetime.combine(first, time.min),
            hourly.c.weather_time < datetime.combine(target + timedelta(days=1), time.min),
        )).scalar_one()
        daily_count, incomplete = conn.execute(select(
            func.count(),
            func.sum((daily.c.observed_hours != 24).cast(Integer)),
        ).where(daily.c.weather_date >= first, daily.c.weather_date <= target)).one()
    if hourly_count != expected or daily_count != plan["days"] * 77 or incomplete:
        raise ValueError(f"Database validation failed: hourly={hourly_count}, daily={daily_count}, incomplete={incomplete}")
    return {"validated_hourly_rows": hourly_count, "validated_daily_rows": daily_count}


def save_run_status(run_id: str, started_at: datetime, target_date: date, status: str,
                    metrics: dict, message: str) -> None:
    engine = make_engine()
    values = [{
        "run_id": run_id,
        "started_at": started_at.replace(tzinfo=None),
        "finished_at": datetime.now(timezone.utc).replace(tzinfo=None),
        "status": status,
        "target_date": target_date,
        "new_hourly_rows": metrics.get("new_hourly_rows", 0),
        "updated_hourly_rows": metrics.get("updated_hourly_rows", 0),
        "new_daily_rows": metrics.get("new_daily_rows", 0),
        "message": message[:1000],
    }]
    with engine.begin() as conn:
        conn.execute(_upsert(conn, run_audit, values, ["run_id"]))
