# Manufacturing Cost Intelligence Platform
#
#   make up && make seed && make run      everything in Docker Compose (Postgres, MinIO, Airflow)
#   make run LOCAL=1                      same pipeline on your host Python against WAREHOUSE_*
#   make k8s-up                           kind cluster + images + manifests + Airflow (Helm)
#
# Knobs: START=2025-01-01 MONTHS=12 SCALE=1.0 SEED=42

SHELL := /bin/bash
START  ?= 2025-01-01
MONTHS ?= 12
SCALE  ?= 1.0
SEED   ?= 42
TAG    ?= 0.1.0
LOCAL  ?=

COMPOSE := docker compose
ifeq ($(LOCAL),)
  RUN := $(COMPOSE) exec -T -w /opt/mci airflow-scheduler
else
  RUN :=
endif

IMAGES := generator loader dbt exporter airflow

.PHONY: help up down logs seed init-db run close dq report extracts corrections test test-integration lint fmt \
        bench clean k8s-up k8s-down images

help:
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-18s %s\n", $$1, $$2}'

.env:
	cp .env.example .env

up: .env ## start Postgres, MinIO and Airflow (http://localhost:8080, admin/admin)
	AIRFLOW_UID=$$(id -u) $(COMPOSE) up -d --build
	@echo "Airflow UI: http://localhost:8080  MinIO console: http://localhost:9001"

down: ## stop the stack (keeps volumes; add -v manually to wipe)
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f --tail=100

seed: ## generate the synthetic source extracts into SOURCE_URI
	$(RUN) python -m data_generator.generate --start $(START) --months $(MONTHS) --scale $(SCALE) --seed $(SEED)

init-db: ## create warehouse schemas and raw tables
	$(RUN) python -m ingestion.load --init-db

run: ## end-to-end batch: land, load, dbt build + tests, checks, close, extracts
	$(RUN) bash scripts/run_pipeline.sh

dq: ## rebuild dbt and publish test results only
	$(RUN) bash -c "dbt build --project-dir dbt --profiles-dir dbt; python -m quality.publish_dq"

close: ## close one period: make close PERIOD=2025-03
	$(RUN) python -m close.period_close --period $(PERIOD) --sign-off; \
	$(RUN) python -m exporter.close_package --period $(PERIOD) --out exports/close

corrections: ## propose + post correcting entries for a period's GL breaks: make corrections PERIOD=2025-03
	$(RUN) python -m close.propose_corrections --period $(PERIOD) --post

report: ## plain-English HTML cost review -> docs/index.html (publish with GitHub Pages)
	$(RUN) python -m exporter.static_report --out docs/index.html

extracts: ## write Tableau extracts (CSV + .hyper when tableauhyperapi is installed)
	$(RUN) python -m exporter.tableau_export --out tableau/extracts --hyper

test: ## unit tests (no database needed)
	pytest -m "not integration"

test-integration: ## tests against a warehouse the pipeline has run on
	pytest -m integration

lint: ## ruff lint + format check
	ruff check . && ruff format --check .

fmt:
	ruff check --fix . && ruff format .

bench: ## scale benchmark on the host: make bench SCALE=50 (see benchmarks/README.md)
	bash benchmarks/run_benchmark.sh $(SCALE)

clean:
	rm -rf data exports tableau/extracts dbt/target dbt/logs

# ---------------------------------------------------------------- kubernetes (kind)
images: ## build all images tagged $(TAG)
	for i in $(IMAGES); do docker build -f docker/$$i.Dockerfile -t mci-$$i:$(TAG) . || exit 1; done

k8s-up: images ## kind cluster + images + manifests + Airflow via Helm
	kind get clusters | grep -q '^mci$$' || kind create cluster --name mci --config k8s/kind-config.yaml
	for i in $(IMAGES); do kind load docker-image mci-$$i:$(TAG) --name mci; done
	test -f k8s/base/secrets.env || cp k8s/base/secrets.env.example k8s/base/secrets.env
	kubectl apply -k k8s/overlays/dev
	kubectl -n mci rollout status statefulset/postgres --timeout=180s
	helm repo add apache-airflow https://airflow.apache.org >/dev/null 2>&1 || true
	helm upgrade --install airflow apache-airflow/airflow --version 1.15.0 -n mci -f k8s/airflow/values.yaml --timeout 15m
	@echo "Airflow UI: http://localhost:30080 (admin/admin)"
	@echo "Seed the source bucket:  kubectl -n mci apply -f k8s/jobs/seed-job.yaml"

k8s-down:
	kind delete cluster --name mci
