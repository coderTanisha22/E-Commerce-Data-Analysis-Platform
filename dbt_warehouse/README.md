# dbt Warehouse

Warehouse models for the Olist data engineering project. Two targets:

- **`duckdb`** (default) — builds against the pipeline's processed Parquet with
  no cloud account. This is how the models are tested.
- **`bigquery`** — the production target. Written, **not yet run**; see
  `docs/implementation_status.md`.

## Run it locally

From the repository root:

```bash
make pipeline        # produce data/processed/ if you have not already
make warehouse       # dbt deps + dbt build on DuckDB
```

Or from this directory:

```bash
../.venv/bin/dbt deps  --profiles-dir .
../.venv/bin/dbt build --profiles-dir .
```

Expected: `PASS=50 WARN=0 ERROR=0 SKIP=0 TOTAL=50` — 14 models and 36 tests.

The DuckDB file lands in `.duckdb/ecom_dw.duckdb` and is gitignored; it is a
build artefact, rebuilt from scratch by `dbt build`.

## Layout

| Path | What |
|---|---|
| `models/staging/` | Typed, renamed staging views over the contracted sources |
| `models/intermediate/` | `int_order_products` — delivered order/product membership |
| `models/marts/` | Dimensions, the order-item fact, sales summary, co-occurrence |
| `macros/portability.sql` | Everything that differs between BigQuery and DuckDB |
| `tests/` | 5 SQL assertions beyond the schema tests |
| `analyses/` | `warehouse_reconciliation.sql` — input vs fact totals |
| `scripts/load_to_bigquery.py` | Loads processed Parquet to `olist_cleaned` with lineage JSON |
| `scripts/local_validate.py` | Independent pandas check over the raw CSVs |

## Contract and scope

- `fct_order_items` grain is one source row per (`order_id`, `order_item_id`).
  **Do not aggregate item rows into order-product-seller lines** — the pipeline
  already publishes `order_lines` for that, and an item key cannot be recovered
  once collapsed.
- All order statuses remain in staging and in the fact. Co-occurrence and the
  sales summary use `delivered` orders only. This differs from the pipeline's
  own co-occurrence figure by 36 pairs; see `docs/contracts_alignment.md`.
- `int_order_products` has one row per delivered (`order_id`, `product_id`).
- Source keys and rows are preserved on load; `_run_date`, `_source_hash` and
  `_loaded_at` are additive.

## Running against BigQuery

```bash
pip install -e '.[bigquery]'                    # from the repo root
gcloud auth application-default login           # tick the Google Cloud data scope
gcloud auth application-default set-quota-project "$ECOM_GCP_PROJECT"
make warehouse-bq                               # load, dbt build, reconcile
```

`make warehouse-bq` reads `ECOM_GCP_PROJECT` and `ECOM_GCP_LOCATION` from the
repo's `.env`. It works in the free BigQuery sandbox. The sandbox forces a 60-day
expiry on time partitions, which is why `fct_order_items` is partitioned by an
integer range over `order_month_key` rather than by `order_date`: a DATE
partition on 2016-2018 orders expires on arrival and leaves the table empty.

`profiles.yml` is committed and carries no credentials — it reads the project
id and location from the environment.
