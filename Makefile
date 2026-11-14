.PHONY: help install check fmt lint test pipeline ingest clean inventory validate-inventory analyse bench bench-report warehouse warehouse-reconcile serve e2e up airflow-install airflow-test airflow-up bigquery-load warehouse-bq minio-up minio-down

# Optional local settings (ECOM_GCP_PROJECT and friends) for the BigQuery targets.
-include .env
export ECOM_GCP_PROJECT ECOM_GCP_LOCATION

VENV := ./.venv/bin
PY := $(VENV)/python

# Airflow lives in its own venv: its pinned dependencies would fight the
# pipeline's and dbt's. Tasks run the pipeline through .venv (dags/ecom_pipeline.py).
AIRFLOW_VERSION := 3.3.2
AIRFLOW_PYTHON ?= python3.11
AIRFLOW_PY_MINOR = $(shell $(AIRFLOW_PYTHON) -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')
AIRFLOW := ./.airflow/venv/bin/airflow
AIRFLOW_ENV := PATH=$(CURDIR)/.airflow/venv/bin:$$PATH AIRFLOW_HOME=$(CURDIR)/.airflow/home AIRFLOW__CORE__DAGS_FOLDER=$(CURDIR)/dags \
	AIRFLOW__CORE__LOAD_EXAMPLES=False

help:
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "};{printf "  %-14s %s\n",$$1,$$2}'

install:  ## create the venv; install the pipeline, API, warehouse (dbt) and study extras
	python3 -m venv .venv
	$(VENV)/pip install -q --upgrade pip
	$(VENV)/pip install -q -e '.[dev,api,warehouse,bench]'

fmt:  ## format with black and apply ruff autofixes
	$(VENV)/black src tests dags
	$(VENV)/ruff check --fix src tests dags

lint:  ## lint without modifying files
	$(VENV)/ruff check src tests dags
	$(VENV)/black --check src tests dags

test:  ## run unit tests
	$(VENV)/pytest

check: lint test  ## everything CI would run

ingest:  ## source -> raw
	$(PY) -m ecom.cli ingest

clean:  ## raw -> processed
	$(PY) -m ecom.cli clean

inventory:  ## processed -> synthetic inventory table + manifest
	$(PY) -m ecom.cli inventory

validate-inventory:  ## validate the synthetic inventory table + figures
	$(PY) -m ecom.cli validate-inventory

analyse:  ## processed -> profile.json + figures
	$(PY) -m ecom.cli analyse

pipeline:  ## ingest + clean + analyse
	$(PY) -m ecom.cli pipeline

bench:  ## run the optimisation study -> results.json + report + figures
	$(PY) -m ecom.cli bench

bench-report:  ## re-render the optimisation report from existing results.json
	$(PY) -m ecom.cli bench --report-only

warehouse:  ## processed -> dbt warehouse on DuckDB (14 models, 36 tests)
	@mkdir -p dbt_warehouse/.duckdb   # gitignored, so absent on a fresh clone
	cd dbt_warehouse && ../$(VENV)/dbt deps --profiles-dir .
	cd dbt_warehouse && ../$(VENV)/dbt build --profiles-dir .

warehouse-reconcile:  ## check warehouse totals against the pipeline that feeds it
	cd dbt_warehouse && ../$(VENV)/python scripts/local_validate.py --data-dir ../data

e2e:  ## source CSVs -> processed -> warehouse -> API, checking every hand-off
	$(PY) -m ecom.cli pipeline --no-figures
	$(MAKE) warehouse
	$(MAKE) warehouse-reconcile
	$(VENV)/pytest tests/test_api.py

up: e2e serve  ## rebuild everything, then serve the dashboard

serve:  ## start the API and dashboard on http://127.0.0.1:8000
	$(PY) -m ecom.cli serve

airflow-install:  ## create .airflow/ with Airflow in its own venv and initialise its database
	$(AIRFLOW_PYTHON) -m venv .airflow/venv
	./.airflow/venv/bin/pip install -q --upgrade pip
	./.airflow/venv/bin/pip install -q "apache-airflow==$(AIRFLOW_VERSION)" --constraint \
		https://raw.githubusercontent.com/apache/airflow/constraints-$(AIRFLOW_VERSION)/constraints-$(AIRFLOW_PY_MINOR).txt
	$(AIRFLOW_ENV) $(AIRFLOW) db migrate

airflow-test:  ## run the whole DAG once, in-process, without a scheduler
	$(AIRFLOW_ENV) $(AIRFLOW) dags test ecom_pipeline

airflow-up:  ## scheduler + web UI on http://localhost:8080 (login printed on start)
	$(AIRFLOW_ENV) $(AIRFLOW) standalone

bigquery-load:  ## processed layer -> BigQuery dataset olist_cleaned (needs ECOM_GCP_PROJECT)
	@test -n "$(ECOM_GCP_PROJECT)" || (echo "set ECOM_GCP_PROJECT in .env first" && exit 1)
	cd dbt_warehouse && ../$(PY) -W ignore::FutureWarning scripts/load_to_bigquery.py \
		--project "$(ECOM_GCP_PROJECT)" --location "$(or $(ECOM_GCP_LOCATION),US)"

warehouse-bq: bigquery-load  ## build and test every dbt model on BigQuery, then reconcile
	cd dbt_warehouse && ../$(VENV)/dbt deps --profiles-dir .
	cd dbt_warehouse && ../$(VENV)/dbt build --profiles-dir . --target bigquery
	$(PY) -W ignore::FutureWarning -m ecom.cli reconcile-warehouse --target bigquery

minio-up:  ## start MinIO, then set ECOM_STORAGE_BACKEND=minio
	docker compose up -d minio

minio-down:  ## stop MinIO
	docker compose down

loc:  ## report functions longer than 50 lines (tracker: Functions/Function length)
	@$(PY) -c "import ast,pathlib;\
v=[(str(f),n.name,(n.end_lineno or n.lineno)-n.lineno+1) for f in pathlib.Path('src').rglob('*.py') \
for n in ast.walk(ast.parse(f.read_text())) if isinstance(n,ast.FunctionDef) and (n.end_lineno or n.lineno)-n.lineno+1>50];\
print('functions over 50 lines:',len(v));[print(f'  {a}:{b}() = {c}') for a,b,c in v]"
