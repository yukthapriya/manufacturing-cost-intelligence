# Runtime interfaces (contract between code, orchestration and infra)

Every workload is a CLI entry point. Airflow (local or Kubernetes mode), Argo,
Docker Compose and the Makefile all call exactly these commands.

## Images (tag `0.1.0`)

| Image            | Dockerfile                    | Entry point / commands it runs                                   |
|------------------|-------------------------------|------------------------------------------------------------------|
| `mci-generator`  | docker/generator.Dockerfile   | `python -m data_generator.generate ...`                          |
| `mci-loader`     | docker/loader.Dockerfile      | `python -m ingestion.land`, `python -m ingestion.load`, `python -m quality.layer_checks`, `python -m quality.publish_dq`, `python -m close.period_close` |
| `mci-dbt`        | docker/dbt.Dockerfile         | `dbt build --project-dir /app/dbt --profiles-dir /app/dbt ...` then `python -m quality.publish_dq` |
| `mci-exporter`   | docker/exporter.Dockerfile    | `python -m exporter.tableau_export`, `python -m exporter.close_package` |
| `mci-airflow`    | docker/airflow.Dockerfile     | Airflow 2.10.5 (python 3.11) + project code + dbt in `/opt/dbt-venv` (local/compose mode) |

All images: base `python:3.11.9-slim-bookworm`, multi-stage (builder venv -> runtime),
non-root user `mci` (uid 10001), workdir `/app`, project copied to `/app`.

## Commands

```
python -m data_generator.generate --start 2025-01-01 --months 12 --scale 1.0 --seed 42 --out <SOURCE_URI>
python -m ingestion.load --init-db
python -m ingestion.land --date YYYY-MM-DD            # copy one day's partitions SOURCE_URI -> RAW_URI
python -m ingestion.load --date YYYY-MM-DD [--force]  # validate + load one day's raw files into Postgres
python -m ingestion.load --all                        # load every partition found under RAW_URI
dbt build --project-dir dbt --profiles-dir dbt [--select ...] [--vars '{...}']
python -m quality.layer_checks --date YYYY-MM-DD
python -m quality.publish_dq --run-results dbt/target/run_results.json
python -m close.period_close --period YYYY-MM [--sign-off]   # exit 2 = sign-off blocked
python -m exporter.tableau_export --out tableau/extracts
python -m exporter.close_package --period YYYY-MM --out exports/close
```

## Environment variables

| Variable                 | Example                         | Used by |
|--------------------------|---------------------------------|---------|
| `WAREHOUSE_HOST`         | `postgres`                      | all DB workloads, dbt profile |
| `WAREHOUSE_PORT`         | `5432`                          | " |
| `WAREHOUSE_DB`           | `mfg_cost`                      | " |
| `WAREHOUSE_USER`         | `mci`                           | " |
| `WAREHOUSE_PASSWORD`     | (secret)                        | " |
| `SOURCE_URI`             | `s3://mci-source` or `./data/source_drop` | generator output, land input |
| `RAW_URI`                | `s3://mci-raw` or `./data/raw`  | land output, load input |
| `S3_ENDPOINT_URL`        | `http://minio:9000` (unset on AWS) | storage layer |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_DEFAULT_REGION` | (secret) | storage layer |
| `SLACK_WEBHOOK_URL`      | (secret, optional)              | alerting |
| `LOG_LEVEL`              | `INFO`                          | all (JSON logs to stdout) |
| `MATERIALITY_USD`        | `1000`                          | close sign-off gate |
| `EXECUTION_MODE`         | `local` or `k8s`                | Airflow DAG factory |
| `MCI_IMAGE_TAG`          | `0.1.0`                         | Airflow k8s mode |
| `K8S_NAMESPACE`          | `mci`                           | Airflow k8s mode |

In Kubernetes: non-secret values live in ConfigMap `mci-config`, secrets in Secret
`mci-secrets` (keys `WAREHOUSE_PASSWORD`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`,
`SLACK_WEBHOOK_URL`). Pods use ServiceAccount `mci-runner`. Namespace `mci`.
Warehouse Postgres service name `postgres`, MinIO service `minio` (API port 9000).
