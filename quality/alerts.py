"""Failure alerts. Posts to Slack when SLACK_WEBHOOK_URL is set, otherwise logs (stub)."""

from __future__ import annotations

import json
import urllib.request

from common.config import slack_webhook
from common.logging_setup import get_logger

log = get_logger("alerts")


def send_alert(title: str, text: str, level: str = "error") -> bool:
    """Send a Slack message; returns True if it was delivered."""
    icon = {"error": ":rotating_light:", "warning": ":warning:", "info": ":white_check_mark:"}.get(level, "")
    payload = {"text": f"{icon} *{title}*\n{text}"}
    url = slack_webhook()
    if not url:
        log.warning(
            "alert (no SLACK_WEBHOOK_URL set, not sent)", extra={"title": title, "text": text, "alert_level": level}
        )
        return False
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 - URL comes from operator config
            return 200 <= resp.status < 300
    except Exception:  # alerting must never take the pipeline down
        log.exception("failed to deliver Slack alert", extra={"title": title})
        return False


def airflow_failure_callback(context) -> None:
    """Airflow on_failure_callback: one message per failed task with a log link."""
    ti = context.get("task_instance")
    send_alert(
        f"Airflow task failed: {ti.dag_id}.{ti.task_id}",
        f"run: {context.get('run_id')}\ntry: {ti.try_number}\nlog: {ti.log_url}",
    )
