# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------------------
# mci-airflow -- Airflow 2.10.5 (Python 3.11) + project code + dbt.
#
# Used by docker-compose (EXECUTION_MODE=local: tasks run the CLIs in-process
# via BashOperator) and by the Helm chart on Kubernetes (EXECUTION_MODE=k8s:
# tasks launch the mci-* workload images with KubernetesPodOperator).
#
# Build from the repo root:  docker build -f docker/airflow.Dockerfile -t mci-airflow:0.1.0 .
# ---------------------------------------------------------------------------
FROM apache/airflow:2.10.5-python3.11

ARG AIRFLOW_VERSION=2.10.5
ARG PYTHON_VERSION=3.11
ARG CONSTRAINTS_URL="https://raw.githubusercontent.com/apache/airflow/constraints-${AIRFLOW_VERSION}/constraints-${PYTHON_VERSION}.txt"
# Provider version that matches the 2.10.5 constraints set.
ARG CNCF_K8S_PROVIDER_VERSION=10.1.0

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# ---- 1. runtime deps into the Airflow environment (as the airflow user) -----
# The official image expects `pip install` to run as the `airflow` user.
# Pinning against the official constraints file keeps Airflow's own transitive
# deps (pandas, numpy, boto3, psycopg2, ...) at versions Airflow was tested
# with; any requirement listed there is resolved to the constrained version.
USER airflow
COPY --chown=airflow:root requirements.txt /tmp/requirements.txt
RUN pip install \
        "apache-airflow==${AIRFLOW_VERSION}" \
        "apache-airflow-providers-cncf-kubernetes==${CNCF_K8S_PROVIDER_VERSION}" \
        -r /tmp/requirements.txt \
        --constraint "${CONSTRAINTS_URL}"

# ---- 2. dbt in an isolated venv ---------------------------------------------
# dbt-core pins (protobuf, jinja2, click, sqlparse, ...) conflict with Airflow's
# constraints, so dbt lives in its own venv and is exposed via a symlink.
USER root
COPY requirements-dbt.txt /tmp/requirements-dbt.txt
RUN python -m venv /opt/dbt-venv && \
    /opt/dbt-venv/bin/pip install --upgrade pip==24.2 && \
    /opt/dbt-venv/bin/pip install -r /tmp/requirements-dbt.txt && \
    ln -sf /opt/dbt-venv/bin/dbt /usr/local/bin/dbt && \
    chown -R airflow:root /opt/dbt-venv && \
    rm -f /tmp/requirements-dbt.txt

# ---- 3. project code --------------------------------------------------------
# Baked in so the Kubernetes deployment needs no git-sync / DAG volume.
# docker-compose bind-mounts dags/, dbt/, data/, tableau/, exports/ over these.
COPY --chown=airflow:root common/          /opt/mci/common/
COPY --chown=airflow:root data_generator/  /opt/mci/data_generator/
COPY --chown=airflow:root ingestion/       /opt/mci/ingestion/
COPY --chown=airflow:root quality/         /opt/mci/quality/
COPY --chown=airflow:root close/           /opt/mci/close/
COPY --chown=airflow:root exporter/        /opt/mci/exporter/
COPY --chown=airflow:root dbt/             /opt/mci/dbt/
COPY --chown=airflow:root airflow/dags/    /opt/mci/airflow/dags/
RUN mkdir -p /opt/mci/data /opt/mci/tableau/extracts /opt/mci/exports/close \
             /opt/mci/dbt/target /opt/mci/dbt/logs && \
    chown -R airflow:root /opt/mci && \
    chmod -R g+rwX /opt/mci

ENV PYTHONPATH=/opt/mci \
    MCI_HOME=/opt/mci \
    AIRFLOW__CORE__DAGS_FOLDER=/opt/mci/airflow/dags \
    AIRFLOW__CORE__LOAD_EXAMPLES=False \
    DBT_SEND_ANONYMOUS_USAGE_STATS=false

WORKDIR /opt/mci
USER airflow
