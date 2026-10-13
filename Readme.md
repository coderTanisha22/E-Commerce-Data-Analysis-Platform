# E-Commerce Data Engineering Platform

Batch data-engineering pipeline on the Olist Brazilian E-Commerce dataset.

Pipeline: Olist CSVs → Python ingestion → local raw zone → Spark cleaning →
local processed zone → (dbt → BigQuery → graph/inventory → API → dashboard,
owned by B/C/D — not yet built).

This README currently documents the **ingestion and Spark cleaning stages**
(Person A's ownership). Sections for the rest of the pipeline will be added
by their owners as those stages land.

## Project layout

```
data/                    Raw Olist source CSVs, as downloaded (not modified by the pipeline)
data_ingestion/           Python ingestion: validates and copies source files into the raw zone
spark/                     Spark cleaning: validates and cleans raw data into the processed zone
storage/                   Generated at runtime - raw/, processed/, quarantine/, reports/ (git-ignored)
tests/                     pytest suite for ingestion and cleaning
docs/contracts.md          Data contracts between pipeline stages
```

## Setup

Requires Python 3.10+ and Java 17+ (Spark's runtime dependency).

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Running ingestion

Copies the nine Olist CSVs from `data/` into the raw zone, validating each
file's columns first and writing a manifest.

```bash
python -m data_ingestion.run_ingestion --run-date 2026-10-13
```

Omit `--run-date` to default to today. Exits non-zero if any file is
missing or fails validation.

## Running Spark cleaning

Reads a given run_date's raw zone, cleans and validates every table, and
writes the processed zone, quarantine files, and a data-quality report.
Must be run after ingestion for the same run_date.

```bash
python -m spark.clean_pipeline 2026-10-13
```

Report lands at `storage/reports/data_quality_report_2026-10-13.json`.

## Running tests

```bash
pytest tests/ -v
```

## Configuration

All storage paths are environment variables with local-filesystem defaults,
so a future move to MinIO is a config change rather than a rewrite:

| Variable | Default | Used by |
|---|---|---|
| `OLIST_SOURCE_DIR` | `data` | ingestion |
| `OLIST_RAW_ZONE_DIR` | `storage/raw/olist` | ingestion, Spark cleaning |
| `OLIST_PROCESSED_ZONE_DIR` | `storage/processed/olist` | Spark cleaning |
| `OLIST_QUARANTINE_ZONE_DIR` | `storage/quarantine/olist` | Spark cleaning |
| `OLIST_REPORTS_DIR` | `storage/reports` | Spark cleaning |

See `docs/contracts.md` for the full data contract this stage publishes.
