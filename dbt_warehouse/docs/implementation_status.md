# Implementation status

**Built and verified.** `dbt build` runs the whole warehouse on DuckDB (local,
no cloud account) and on BigQuery (free sandbox project): **15 models and
57 tests**.

```
Done. PASS=71 WARN=1 ERROR=0 SKIP=0 TOTAL=72
```

The one warning is `warn_orders_without_items`: 775 orders have no item rows, a
known Olist quirk reported as a warning rather than a failure.

## What is verified

| Check | Result |
|---|---|
| Source item rows preserved into `fct_order_items` | 112,650 -> 112,650, difference 0 |
| Price sum preserved | 13,591,643.70 -> 13,591,643.70, difference 0 |
| Orders: staging vs orders with items | 99,441 and 98,666; 775 without items |
| `fct_orders` reconciles to the item fact | orders, items and price total all equal |
| Order-item key unique | passes |
| Product pairs ordered, no self or reverse pairs | passes |
| Referential integrity to the dimensions, including `dim_dates` | passes |
| `int_order_products` membership unique | passes |
| Sales summary window | 2017-02-01 to 2018-08-31, 577 days, matches `src/ecom/config.py` |
| Sales summary units | sum of `total_units_sold` equals delivered lines in the window |
| Co-occurrence | 4,054 pairs over 4,881 products, weight sum 4,476 |

Three independent implementations agree on 4,054 pairs: the dbt models,
`scripts/local_validate.py` (pandas over the raw CSVs, no shared code), and
`src/ecom/analysis/profile.py` on the processed layer.

## BigQuery

Run in the sandbox project: the loader maps the six contract tables to
`olist_cleaned`, dbt builds and tests into `olist_analytics_dev`, and the same
reconciliation checks pass. The sandbox expires tables after 60 days: rebuild
with the commands in `README.md`. After any rebuild, confirm `fct_order_items`
has 112,650 rows: a table emptied by partition expiry passes the not-null and
relationship tests, and only the revenue test catches it.

## Known limits

- Full rebuild on every run; there is no incremental logic.
- The API, graph and inventory read the pipeline's processed Parquet. The
  warehouse is reconciled against that output rather than serving it directly.
- `product_sales_summary` is delivered-only, while the pipeline's inventory
  generator excludes only canceled and unavailable orders, so its unit counts
  can be slightly higher.
