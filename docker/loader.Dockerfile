# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------------------
# mci-loader -- landing, raw load, layer checks, DQ publish and period close
# Build from the repo root:  docker build -f docker/loader.Dockerfile -t mci-loader:0.1.0 .
# ---------------------------------------------------------------------------

# ---- builder: resolve and install dependencies into an isolated venv -------
FROM python:3.11.9-slim-bookworm AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

# Copy only requirement files first so the dependency layer is cached
# independently of source changes.
COPY requirements.txt /tmp/requirements.txt
RUN pip install --upgrade pip==24.2 && \
    pip install -r /tmp/requirements.txt

# ---- runtime: slim image, venv + only the packages this workload needs ------
FROM python:3.11.9-slim-bookworm AS runtime

LABEL org.opencontainers.image.title="mci-loader" \
      org.opencontainers.image.description="Manufacturing Cost Intelligence - landing, raw load, layer checks, DQ publish and period close" \
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
COPY --chown=mci:mci ingestion/ ./ingestion/
COPY --chown=mci:mci quality/ ./quality/
COPY --chown=mci:mci close/ ./close/
RUN mkdir -p /app/data && chown mci:mci /app/data

USER 10001:10001

# Generic module runner: the caller supplies the module and its arguments, e.g.
#   docker run mci-loader:0.1.0 ingestion.load --date 2025-01-15
#   docker run mci-loader:0.1.0 close.period_close --period 2025-01
ENTRYPOINT ["python", "-m"]
