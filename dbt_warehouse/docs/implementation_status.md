# Implementation status

**Built and verified locally.** `dbt build` runs the whole warehouse against
the pipeline's processed Parquet on DuckDB: **14 models (7 views, 7 tables) and
35 tests, all passing**, with no cloud account required.

```
Done. PASS=49 WARN=0 ERROR=0 SKIP=0 TOTAL=49
```

## What is verified

| Check | Result |
|---|---|
| Source item rows preserved into `fct_order_items` | 112,650 → 112,650, difference 0 |
| Price sum preserved | 13,591,643.70 → 13,591,643.70, difference 0 |
| Order-item key unique | passes |
| Product pairs ordered, no self or reverse pairs | passes |
| Referential integrity to `dim_products`, `dim_sellers`, `dim_customers` | passes |
| `int_order_products` membership unique | passes |

Three independent implementations agree on the delivered co-occurrence pair
count of **4,022**: the dbt models on DuckDB, `scripts/local_validate.py`
(pandas over the raw CSVs), and a direct recomputation from the processed
layer.

## What is NOT verified

**No BigQuery run has been made.** The `bigquery` target, the partitioning and
clustering on `fct_order_items`, and `scripts/load_to_bigquery.py` are written
but unexecuted — there is no GCP project attached to this repository. Nothing
in the report should claim a cloud run until `dbt build --target bigquery`
has actually been run against a loaded `olist_cleaned` dataset.

The local DuckDB target is not a substitute for that. It proves the SQL is
correct and the grain and invariants hold; it does not prove the BigQuery
dialect, the partition specification or the loader work.
