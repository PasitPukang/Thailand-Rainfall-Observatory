"""Daily weather ETL with visible cleansing, validation and run summaries."""

import logging
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from airflow.decorators import dag, task
from airflow.operators.python import get_current_context
from airflow.utils.trigger_rule import TriggerRule


@dag(
    dag_id="thailand_weather_daily",
    description="Clean, load and report ERA5 weather at 77 Thai provincial points",
    schedule="0 14 * * *",
    start_date=datetime(2026, 1, 1, tzinfo=ZoneInfo("Asia/Bangkok")),
    catchup=False,
    max_active_runs=1,
    default_args={"retries": 2, "retry_delay": timedelta(minutes=10)},
    tags=["Thailand", "weather", "ERA5"],
)
def thailand_weather_daily():
    @task
    def plan_missing_days():
        from pipeline.airflow_daily import plan_missing_days as plan

        result = plan(datetime.now(ZoneInfo("Asia/Bangkok")).date())
        logging.info("Weather load plan: %s", result)
        return result

    @task
    def extract_raw(plan: dict):
        from pipeline.airflow_daily import extract_raw as extract

        result = extract(plan)
        logging.info("Raw extraction: %s", result)
        return result

    @task
    def cleanse_data(plan: dict, extraction: dict):
        from pipeline.airflow_daily import cleanse_data as cleanse

        logging.info("Starting cleansing after extraction: %s", extraction)
        result = cleanse(plan)
        logging.info("Data cleansing: %s", result)
        return result

    @task
    def load_postgres(plan: dict, cleansing: dict):
        from pipeline.airflow_daily import load_postgres as load

        logging.info("Starting PostgreSQL load after cleansing: %s", cleansing)
        result = load(plan)
        logging.info("PostgreSQL save status: %s", result)
        return result

    @task
    def validate_postgres(plan: dict, loading: dict):
        from pipeline.airflow_daily import validate_postgres as validate

        logging.info("Checking saved rows: %s", loading)
        result = validate(plan)
        logging.info("PostgreSQL validation passed: %s", result)
        return result

    @task
    def refresh_powerbi_export(validation: dict):
        from pipeline.cli import export_powerbi

        logging.info("Exporting Power BI data after validation: %s", validation)
        return [str(path) for path in export_powerbi()]

    @task(trigger_rule=TriggerRule.ALL_DONE, retries=0)
    def notify_run_status():
        from pipeline.airflow_daily import save_run_status

        context = get_current_context()
        task_instance = context["ti"]
        dag_run = context["dag_run"]
        states = {
            instance.task_id: instance.state
            for instance in dag_run.get_task_instances()
            if instance.task_id != "notify_run_status"
        }
        status = "SUCCESS" if states and all(value == "success" for value in states.values()) else "FAILED"
        plan = task_instance.xcom_pull(task_ids="plan_missing_days") or {}
        extraction = task_instance.xcom_pull(task_ids="extract_raw") or {}
        cleansing = task_instance.xcom_pull(task_ids="cleanse_data") or {}
        loading = task_instance.xcom_pull(task_ids="load_postgres") or {}
        validation = task_instance.xcom_pull(task_ids="validate_postgres") or {}
        exported = task_instance.xcom_pull(task_ids="refresh_powerbi_export") or []
        failed = [name for name, value in states.items() if value != "success"]
        summary = {
            "status": status,
            "run_id": dag_run.run_id,
            "date_range": f"{plan.get('first', '-')} to {plan.get('target', '-')}",
            "days": plan.get("days", 0),
            "api_requests": extraction.get("api_requests", 0),
            "cleaned_rows": cleansing.get("cleaned_rows", 0),
            "new_hourly_rows": loading.get("new_hourly_rows", 0),
            "updated_hourly_rows": loading.get("updated_hourly_rows", 0),
            "new_daily_rows": loading.get("new_daily_rows", 0),
            "validated_hourly_rows": validation.get("validated_hourly_rows", 0),
            "powerbi_files": len(exported),
            "failed_tasks": failed,
        }
        message = (f"Status={status}; new hourly={summary['new_hourly_rows']:,}; "
                   f"updated hourly={summary['updated_hourly_rows']:,}; "
                   f"new daily={summary['new_daily_rows']:,}; "
                   f"failed tasks={','.join(failed) or '-'}")
        target = date.fromisoformat(plan["target"]) if plan else datetime.now(ZoneInfo("Asia/Bangkok")).date() - timedelta(days=7)
        log = logging.getLogger(__name__)
        (log.info if status == "SUCCESS" else log.error)("AIRFLOW WEATHER NOTIFICATION: %s | %s", message, summary)
        save_run_status(
            dag_run.run_id,
            dag_run.start_date or datetime.now(timezone.utc),
            target,
            status,
            loading,
            message,
        )
        return summary

    plan = plan_missing_days()
    extracted = extract_raw(plan)
    cleansed = cleanse_data(plan, extracted)
    loaded = load_postgres(plan, cleansed)
    validated = validate_postgres(plan, loaded)
    exported = refresh_powerbi_export(validated)
    exported >> notify_run_status()


thailand_weather_daily()
