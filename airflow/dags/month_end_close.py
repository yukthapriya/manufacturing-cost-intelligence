"""Month-end close.

Runs every morning; does real work only on business day 1 of a month (company holiday
calendar in common.fiscal_calendar), closing the previous period:

  wait for the daily load of the posting cutoff day -> refresh reconciliations (dbt, tag:reconciliation)
  -> period_close --sign-off -> close package -> notify

* period_close exits 2 when sign-off is blocked (material GL breaks, WIP roll-forward
  not tying, failing dbt tests). The task then fails visibly and alerts; it is not
  retried, because blocked is a business outcome, not a transient error.
* The close package is still produced when blocked (trigger_rule=all_done), so the
  team gets the exception list to work from.
* Manual close of any period: trigger with conf {"period": "2025-03"}.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from airflow.operators.python import PythonOperator, ShortCircuitOperator
from airflow.sensors.external_task import ExternalTaskSensor
from airflow.utils.trigger_rule import TriggerRule

from airflow import DAG
from common.fiscal_calendar import Period, nth_business_day
from mci_tasks import CLOSE_OUT, DEFAULT_ARGS, dbt_build_and_publish, mci_task
from quality.alerts import send_alert


def _period_to_close(ds: str, dag_run=None, **_) -> str | bool:
    """Return the period to close (pushed to XCom) or False to skip the run."""
    if dag_run and dag_run.conf and dag_run.conf.get("period"):
        return dag_run.conf["period"]
    today = date.fromisoformat(ds)
    if today != nth_business_day(today.year, today.month, 1):
        return False
    prev = today.replace(day=1) - timedelta(days=1)
    return f"{prev:%Y-%m}"


def _cutoff_run(logical_date, **context):
    """Logical date of the daily pipeline run that loaded the period's last posting day."""
    period = context["ti"].xcom_pull(task_ids="business_day_1_gate")
    cutoff = Period.of(date.fromisoformat(f"{period}-01")).close_date
    return datetime(cutoff.year, cutoff.month, cutoff.day, 2, 15, tzinfo=logical_date.tzinfo)


def _notify(**context) -> None:
    period = context["ti"].xcom_pull(task_ids="business_day_1_gate")
    states = {t.task_id: t.state for t in context["dag_run"].get_task_instances()}
    blocked = states.get("period_close_sign_off") != "success"
    send_alert(
        f"Close {period}: {'BLOCKED' if blocked else 'signed off'}",
        f"close package: {CLOSE_OUT}/close_package_{period}.xlsx\ntask states: {states}",
        level="error" if blocked else "info",
    )


PERIOD = "{{ ti.xcom_pull(task_ids='business_day_1_gate') }}"

with DAG(
    dag_id="month_end_close",
    description="Business-day-1 close: reconciliations, sign-off gate, close package",
    start_date=datetime(2025, 1, 1),
    schedule="0 6 * * *",
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["mci", "close"],
    doc_md=__doc__,
) as dag:
    gate = ShortCircuitOperator(task_id="business_day_1_gate", python_callable=_period_to_close)

    # the period is complete once the daily run for its posting cutoff (day before BD1) succeeded
    wait_for_data = ExternalTaskSensor(
        task_id="wait_for_cutoff_day_load",
        external_dag_id="manufacturing_cost_pipeline",
        external_task_id="layer_checks",
        execution_date_fn=_cutoff_run,
        mode="reschedule",
        poke_interval=600,
        timeout=6 * 3600,
    )

    recon = mci_task("refresh_reconciliations", "dbt", [dbt_build_and_publish(select="tag:reconciliation")], shell=True)

    sign_off = mci_task(
        "period_close_sign_off", "loader", ["close.period_close", "--period", PERIOD, "--sign-off"], retries=0
    )

    package = mci_task(
        "close_package",
        "exporter",
        ["exporter.close_package", "--period", PERIOD, "--out", CLOSE_OUT],
        trigger_rule=TriggerRule.ALL_DONE,
    )

    notify = PythonOperator(task_id="notify", python_callable=_notify, trigger_rule=TriggerRule.ALL_DONE)

    gate >> wait_for_data >> recon >> sign_off >> package >> notify
