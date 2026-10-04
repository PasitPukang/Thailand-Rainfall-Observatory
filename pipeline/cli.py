import argparse
import csv
import json
from datetime import date
from pathlib import Path

from sqlalchemy import create_engine, func, select

from .core import ROOT, _upsert, batch, daily, hourly, make_engine, province, run


def export_powerbi(out: Path = ROOT / "powerbi" / "export") -> list[Path]:
    """Refresh the small, report-ready CSV snapshots from the warehouse."""
    engine = make_engine()
    out.mkdir(parents=True, exist_ok=True)
    exported = []
    for table in (province, daily):
        target = out / f"{table.name}.csv"
        temporary = target.with_suffix(".csv.tmp")
        with engine.connect() as conn, temporary.open("w", encoding="utf-8-sig", newline="") as output:
            writer = csv.writer(output)
            writer.writerow([column.name for column in table.columns])
            result = conn.execute(select(table))
            for row in result:
                writer.writerow(row)
        temporary.replace(target)
        exported.append(target)
        print(f"Exported {target}", flush=True)
    return exported


def main():
    parser = argparse.ArgumentParser(description="Thailand provincial ERA5 weather pipeline")
    sub = parser.add_subparsers(dest="command", required=True)
    backfill = sub.add_parser("backfill")
    backfill.add_argument("--start", type=date.fromisoformat, default=date(2018, 1, 1))
    backfill.add_argument("--end", type=date.fromisoformat, default=date(2025, 12, 31))
    backfill.add_argument("--provinces", help="Comma-separated province IDs; default is all 77")
    backfill.add_argument("--force", action="store_true")
    sub.add_parser("status")
    export = sub.add_parser("export-powerbi")
    export.add_argument("--out", type=Path, default=ROOT / "powerbi" / "export")
    validate = sub.add_parser("validate")
    validate.add_argument("--start", type=date.fromisoformat, default=date(2018, 1, 1))
    validate.add_argument("--end", type=date.fromisoformat, default=date(2025, 12, 31))
    sub.add_parser("migrate-sqlite", help="Copy locally loaded SQLite data into DATABASE_URL")
    args = parser.parse_args()
    if args.command == "backfill":
        ids = {int(v) for v in args.provinces.split(",")} if args.provinces else None
        count = run(args.start, args.end, ids, args.force)
        print(f"Processed {count:,} hourly rows")
    elif args.command == "status":
        engine = make_engine()
        with engine.connect() as conn:
            facts = conn.execute(select(func.count()).select_from(hourly)).scalar_one()
            days = conn.execute(select(func.count()).select_from(daily)).scalar_one()
        print(f"Hourly fact rows: {facts:,}; daily mart rows: {days:,}")
    elif args.command == "export-powerbi":
        export_powerbi(args.out)
    elif args.command == "migrate-sqlite":
        source_path = ROOT / "data" / "weather.sqlite"
        if not source_path.exists():
            raise FileNotFoundError(source_path)
        source_engine = create_engine(f"sqlite:///{source_path.as_posix()}")
        target_engine = make_engine()
        if target_engine.dialect.name != "postgresql":
            raise ValueError("Set DATABASE_URL to the PostgreSQL warehouse before migrating")
        for table in (province, hourly, daily, batch):
            copied = 0
            with source_engine.connect() as source:
                result = source.execute(select(table))
                while rows := result.mappings().fetchmany(500):
                    payload = [dict(row) for row in rows]
                    with target_engine.begin() as target:
                        target.execute(_upsert(target, table, payload,
                            [column.name for column in table.primary_key.columns]))
                    copied += len(payload)
                    if copied % 50000 == 0:
                        print(f"{table.name}: {copied:,} rows", flush=True)
            print(f"{table.name}: {copied:,} rows copied", flush=True)
    else:
        from datetime import datetime, timedelta
        from sqlalchemy import distinct

        engine = make_engine()
        start_time = datetime.combine(args.start, datetime.min.time())
        end_time = datetime.combine(args.end + timedelta(days=1), datetime.min.time())
        with engine.connect() as conn:
            actual = conn.execute(select(func.count()).select_from(hourly).where(
                hourly.c.weather_time >= start_time,
                hourly.c.weather_time < end_time,
            )).scalar_one()
            covered_provinces = conn.execute(select(func.count(distinct(hourly.c.province_id))).where(
                hourly.c.weather_time >= start_time,
                hourly.c.weather_time < end_time,
            )).scalar_one()
            incomplete_days = conn.execute(select(func.count()).select_from(daily).where(
                daily.c.weather_date >= args.start,
                daily.c.weather_date <= args.end,
                daily.c.observed_hours != 24,
            )).scalar_one()
        expected = (args.end - args.start).days * 77 * 24 + 77 * 24
        report = {
            "start": args.start.isoformat(), "end": args.end.isoformat(),
            "expected_hourly_rows": expected, "actual_hourly_rows": actual,
            "covered_provinces": covered_provinces,
            "incomplete_daily_rows": incomplete_days,
            "complete": actual == expected and covered_provinces == 77 and incomplete_days == 0,
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
