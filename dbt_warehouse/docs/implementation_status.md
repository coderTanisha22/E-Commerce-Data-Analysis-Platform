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

The warehouse and the pipeline's own analysis now report the same
co-occurrence figures — 4,054 pairs over 101,953 memberships — because both
apply `ecom.config.EXCLUDED_STATUSES`. See `docs/contracts_alignment.md` for
how that rule was arrived at.

Three independent implementations agree on **4,054 pairs over 4,881 products**:
the dbt models on DuckDB, `scripts/local_validate.py` (pandas over the original
Olist CSVs, which shares no code with the models), and
`src/ecom/analysis/profile.py` on the processed layer.

## What is NOT verified

**No BigQuery run has been made.** The `bigquery` target, the partitioning and
clustering on `fct_order_items`, and `scripts/load_to_bigquery.py` are written
but unexecuted — there is no GCP project attached to this repository. Nothing
in the report should claim a cloud run until `dbt build --target bigquery`
has actually been run against a loaded `olist_cleaned` dataset.

The local DuckDB target is not a substitute for that. It proves the SQL is
correct and the grain and invariants hold; it does not prove the BigQuery
dialect, the partition specification or the loader work.
