# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------------------
# mci-dbt -- dbt transformations (plus quality.publish_dq)
# Build from the repo root:  docker build -f docker/dbt.Dockerfile -t mci-dbt:0.1.0 .
# ---------------------------------------------------------------------------

# ---- builder: resolve and install dependencies into an isolated venv -------
FROM python:3.11.9-slim-bookworm AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

# Copy only requirement files first so the dependency layer is cached
# independently of source changes.
COPY requirements.txt requirements-dbt.txt /tmp/
RUN pip install --upgrade pip==24.2 && \
    pip install -r /tmp/requirements.txt -r /tmp/requirements-dbt.txt

# ---- runtime: slim image, venv + only the packages this workload needs ------
FROM python:3.11.9-slim-bookworm AS runtime

LABEL org.opencontainers.image.title="mci-dbt" \
      org.opencontainers.image.description="Manufacturing Cost Intelligence - dbt transformations (plus quality.publish_dq)" \
      org.opencontainers.image.version="0.1.0"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:${PATH}" \
    PYTHONPATH=/app

# Fixed uid/gid so Kubernetes securityContext (runAsUser: 10001) and volume
# ownership stay predictable across images.
RUN groupadd --system --gid 10001 mci && \
    useradd --system --uid 10001 --gid mci --home-dir /app --shell /usr/sbin/nologin mci

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=mci:mci common/ ./common/
COPY --chown=mci:mci quality/ ./quality/
COPY --chown=mci:mci dbt/ ./dbt/

# dbt writes target/ and logs/ inside the project dir, so it must be writable
# by the non-root user. There is no packages.yml, so `dbt deps` is skipped.
ENV DBT_PROFILES_DIR=/app/dbt \
    DBT_PROJECT_DIR=/app/dbt \
    DBT_SEND_ANONYMOUS_USAGE_STATS=false
RUN mkdir -p /app/dbt/target /app/dbt/logs && chown -R mci:mci /app/dbt

USER 10001:10001

# The image also carries quality/ so a follow-up step can run
#   docker run --entrypoint python mci-dbt:0.1.0 -m quality.publish_dq --run-results dbt/target/run_results.json
ENTRYPOINT ["dbt"]
CMD ["build", "--project-dir", "/app/dbt", "--profiles-dir", "/app/dbt"]
