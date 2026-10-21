# dbt Warehouse

Warehouse models for the Olist data engineering project. This folder is intended to live at the repository root as `dbt_warehouse/`.

## Contract and scope

- Inputs are the nine accepted cleaned Parquet tables produced by the Spark stage, loaded into BigQuery dataset `olist_cleaned` using their exact table names from `docs/contracts.md`.
- Source keys and rows are preserved during loading; provenance columns `_run_date`, `_source_hash`, `_loaded_at` are additive.
- `fct_order_items` grain is one source row per (`order_id`, `order_item_id`). Do not aggregate item rows into order-product-seller lines.
- All order statuses remain in the staging and fact layers. Co-occurrence and sales summary use `delivered` orders only.
- `int_order_products` has one row per delivered (`order_id`, `product_id`) membership.
- `product_sales_summary` counts delivered item lines and computes line-count rate over the global delivered-order observation window.

## Files

- `models/staging/`: type-safe, named staging models over the contracted source tables.
- `models/intermediate/`: delivered order/product membership for downstream graph work.
- `models/marts/`: dimensions, order-item fact, product sales summary and product co-occurrence.
- `tests/`: dbt schema tests and SQL assertions.
- `scripts/load_to_bigquery.py`: loads processed Parquet files to `olist_cleaned` and records a lineage JSON.
- `scripts/local_validate.py`: local DuckDB sanity check against the repo's original CSVs; not a substitute for a BigQuery run.

## Setup

From the repository root, activate the existing virtual environment and install:

```powershell
python -m pip install dbt-bigquery duckdb pandas pyarrow google-cloud-bigquery
```

Copy `profiles.yml.example` to `%USERPROFILE%\.dbt\profiles.yml`, replace `YOUR_GCP_PROJECT`, and authenticate with:

```powershell
gcloud auth application-default login
```

Set the BigQuery location to the region used by your project. The profile's `dataset` is the dbt output dataset (`olist_analytics_dev`); source tables are read from `olist_cleaned`.

## Local validation (no cloud credentials)

Run from this directory:

```powershell
python scripts/local_validate.py --data-dir ..\data
```

The local check verifies source-to-fact row preservation, price-sum reconciliation, uniqueness of the order-item key, and pair ordering. It uses the original CSVs as a local test fixture. Final acceptance still requires loading the accepted cleaned Parquet data and running dbt against BigQuery.

## BigQuery run

1. Run Person A's cleaning pipeline and confirm all nine expected Parquet table outputs exist.
2. From this directory, run `python scripts/load_to_bigquery.py --project YOUR_GCP_PROJECT --processed-dir ..\storage\processed\olist --dataset olist_cleaned`.
3. Run `dbt deps`, then `dbt debug`, then `dbt build`.
4. Run `python scripts/export_results.py YOUR_GCP_PROJECT --dataset olist_analytics_dev`.

Do not commit `profiles.yml`, service account keys, `.env`, local data outputs, or generated dbt target files. Do not claim a BigQuery run succeeded until `dbt build` has actually completed successfully.
