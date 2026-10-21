"""Task factory shared by the MCI DAGs.

One definition, two runtimes, selected by EXECUTION_MODE:
  local  BashOperator inside the Airflow container (docker-compose); code at /opt/mci
  k8s    KubernetesPodOperator: every step is an isolated pod running its own image
         (mci-<image>:<MCI_IMAGE_TAG>) with resource requests/limits, the mci-config
         ConfigMap and mci-secrets Secret, as service account mci-runner.
"""

from __future__ import annotations

import os
import shlex
from datetime import timedelta

from airflow.models.baseoperator import BaseOperator
from airflow.operators.bash import BashOperator

from quality.alerts import airflow_failure_callback

EXECUTION_MODE = os.environ.get("EXECUTION_MODE", "local")
IMAGE_TAG = os.environ.get("MCI_IMAGE_TAG", "0.1.0")
NAMESPACE = os.environ.get("K8S_NAMESPACE", "mci")
CODE_DIR = os.environ.get("MCI_CODE_DIR", "/opt/mci")

# Output locations differ: the Airflow container mounts ./tableau and ./exports into
# /opt/mci; pods mount the mci-exports PVC at /app/out.
TABLEAU_OUT = "tableau/extracts" if EXECUTION_MODE == "local" else "/app/out/tableau/extracts"
CLOSE_OUT = "exports/close" if EXECUTION_MODE == "local" else "/app/out/exports/close"

RESOURCES = {
    # image: (cpu request, memory request, cpu limit, memory limit)
    "generator": ("500m", "1Gi", "2", "6Gi"),
    "loader": ("250m", "512Mi", "1", "2Gi"),
    "dbt": ("500m", "512Mi", "2", "2Gi"),
    "exporter": ("250m", "512Mi", "1", "2Gi"),
}

DEFAULT_ARGS = {
    "owner": "manufacturing-accounting",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "retry_exponential_backoff": True,
    "max_retry_delay": timedelta(minutes=30),
    "on_failure_callback": airflow_failure_callback,
}


def mci_task(task_id: str, image: str, argv: list[str], *, shell: bool = False, **kwargs) -> BaseOperator:
    """Create a step that runs `argv` in `image` (k8s) or in the Airflow container (local).

    shell=True runs argv[0] as a /bin/sh -c script (used for dbt build + publish in one step,
    because the two need the same run_results.json and pods don't share a filesystem).
    """
    if EXECUTION_MODE == "k8s":
        from airflow.providers.cncf.kubernetes.operators.pod import KubernetesPodOperator
        from kubernetes.client import models as k8s

        cpu_req, mem_req, cpu_lim, mem_lim = RESOURCES[image]
        cmds, arguments = (["/bin/sh", "-c"], [argv[0]]) if shell else (None, argv)
        volumes, mounts = [], []
        if image == "exporter":
            volumes = [
                k8s.V1Volume(
                    name="exports",
                    persistent_volume_claim=k8s.V1PersistentVolumeClaimVolumeSource(claim_name="mci-exports"),
                )
            ]
            mounts = [k8s.V1VolumeMount(name="exports", mount_path="/app/out")]
        return KubernetesPodOperator(
            task_id=task_id,
            name=f"mci-{task_id.replace('_', '-')}",
            namespace=NAMESPACE,
            image=f"mci-{image}:{IMAGE_TAG}",
            image_pull_policy="IfNotPresent",
            cmds=cmds,
            arguments=arguments,
            env_from=[
                k8s.V1EnvFromSource(config_map_ref=k8s.V1ConfigMapEnvSource(name="mci-config")),
                k8s.V1EnvFromSource(secret_ref=k8s.V1SecretEnvSource(name="mci-secrets")),
            ],
            container_resources=k8s.V1ResourceRequirements(
                requests={"cpu": cpu_req, "memory": mem_req}, limits={"cpu": cpu_lim, "memory": mem_lim}
            ),
            volumes=volumes,
            volume_mounts=mounts,
            service_account_name="mci-runner",
            get_logs=True,
            on_finish_action="delete_succeeded_pod",
            startup_timeout_seconds=300,
            **kwargs,
        )

    # local: the generator/loader/exporter entry points are python modules, dbt is a CLI
    if shell:
        cmd = argv[0]
    elif image == "dbt":
        cmd = "dbt " + " ".join(shlex.quote(a) for a in argv)
    elif image == "generator":
        cmd = "python -m data_generator.generate " + " ".join(shlex.quote(a) for a in argv)
    else:
        cmd = "python -m " + " ".join(shlex.quote(a) for a in argv)
    return BashOperator(task_id=task_id, bash_command=f"cd {CODE_DIR} && {cmd}", append_env=True, **kwargs)


def dbt_build_and_publish(select: str | None = None, full_refresh: str = "false") -> str:
    """Shell script: dbt build, always publish test results, exit with dbt's status."""
    project = "dbt" if EXECUTION_MODE == "local" else "/app/dbt"
    sel = f"--select {select} " if select else ""
    return (
        f"FR=''; [ \"{full_refresh}\" = \"true\" ] && FR='--full-refresh'; "
        f"dbt build --project-dir {project} --profiles-dir {project} {sel}$FR; rc=$?; "
        f"python -m quality.publish_dq --run-results {project}/target/run_results.json || true; "
        "exit $rc"
    )
