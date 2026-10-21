.PHONY: help install check fmt lint test pipeline ingest clean inventory validate-inventory analyse bench bench-report warehouse warehouse-reconcile minio-up minio-down

VENV := ./.venv/bin
PY := $(VENV)/python

help:
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "};{printf "  %-14s %s\n",$$1,$$2}'

install:  ## create the venv and install the project with dev extras
	python3 -m venv .venv
	$(VENV)/pip install -q --upgrade pip
	$(VENV)/pip install -q -e '.[dev]'

fmt:  ## format with black and apply ruff autofixes
	$(VENV)/black src tests
	$(VENV)/ruff check --fix src tests

lint:  ## lint without modifying files
	$(VENV)/ruff check src tests
	$(VENV)/black --check src tests

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

warehouse:  ## processed -> dbt warehouse on DuckDB (14 models, 35 tests)
	cd dbt_warehouse && ../$(VENV)/dbt deps --profiles-dir .
	cd dbt_warehouse && ../$(VENV)/dbt build --profiles-dir .

warehouse-reconcile:  ## check warehouse totals against the pipeline that feeds it
	cd dbt_warehouse && ../$(VENV)/python scripts/local_validate.py --data-dir ../data

minio-up:  ## start MinIO, then set ECOM_STORAGE_BACKEND=minio
	docker compose up -d minio

minio-down:  ## stop MinIO
	docker compose down

loc:  ## report functions longer than 50 lines (tracker: Functions/Function length)
	@$(PY) -c "import ast,pathlib;\
v=[(str(f),n.name,(n.end_lineno or n.lineno)-n.lineno+1) for f in pathlib.Path('src').rglob('*.py') \
for n in ast.walk(ast.parse(f.read_text())) if isinstance(n,ast.FunctionDef) and (n.end_lineno or n.lineno)-n.lineno+1>50];\
print('functions over 50 lines:',len(v));[print(f'  {a}:{b}() = {c}') for a,b,c in v]"
