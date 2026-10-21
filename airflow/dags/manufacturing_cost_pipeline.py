"""Daily manufacturing cost pipeline.

land raw files -> validate + load -> dbt build (models + tests, publish DQ) -> layer checks -> Tableau extracts

* One run per business date ({{ ds }}); runs are sequential (max_active_runs=1) so
  incremental models see days in order.
* Backfill:   airflow dags backfill -s 2025-01-01 -e 2025-01-31 manufacturing_cost_pipeline
* Rebuild:    trigger with conf {"full_refresh": true} to rebuild every dbt model from scratch.
* Failures:   retries with exponential backoff, Slack alert on failure (quality.alerts),
              SLA alert if the extracts are not published within 3 hours of the run starting.
* dbt_build fails the run if any error-severity test fails (critical data quality),
  after publishing every test result to dq.dbt_test_results.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from mci_tasks import DEFAULT_ARGS, TABLEAU_OUT, dbt_build_and_publish, mci_task
from quality.alerts import send_alert


def _sla_miss(dag, task_list, blocking_task_list, slas, blocking_tis):
    send_alert(f"SLA missed: {dag.dag_id}", f"tasks: {task_list}", level="warning")


with DAG(
    dag_id="manufacturing_cost_pipeline",
    description="Ingest, reconcile and cost manufacturing transactions daily",
    # source extracts start in Dec-2024 (purchase orders placed before the first production month)
    start_date=datetime(2024, 12, 1),
    schedule="15 2 * * *",  # 02:15 daily; processes the previous day's partition ({{ ds }})
    catchup=True,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    sla_miss_callback=_sla_miss,
    params={"full_refresh": False},
    tags=["mci", "manufacturing-accounting"],
    doc_md=__doc__,
) as dag:
    land = mci_task("land_raw", "loader", ["ingestion.land", "--date", "{{ ds }}"])

    load = mci_task("validate_and_load", "loader", ["ingestion.load", "--date", "{{ ds }}"])

    dbt_build = mci_task(
        "dbt_build",
        "dbt",
        [dbt_build_and_publish(full_refresh="{{ params.full_refresh | lower }}")],
        shell=True,
        execution_timeout=timedelta(hours=2),
    )

    layer_checks = mci_task("layer_checks", "loader", ["quality.layer_checks", "--date", "{{ ds }}"])

    export = mci_task(
        "export_tableau_extracts",
        "exporter",
        ["exporter.tableau_export", "--out", TABLEAU_OUT],
        sla=timedelta(hours=3),
    )

    land >> load >> dbt_build >> layer_checks >> export
