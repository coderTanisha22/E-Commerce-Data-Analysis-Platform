# Contract alignment decisions

How the warehouse relates to the pipeline that feeds it.

## Source naming: two cleaned layers, one set of models

`docs/contracts.md` names each cleaned table after its original Olist export
(`olist_orders_dataset`, …) under the Spark zone `storage/processed/olist/`.
These models follow that contract, and the source names in `models/sources.yml`
are unchanged.

The pandas cleaning path in `src/ecom/cleaning` publishes the same rows under
logical names (`orders`, `order_items`, …) in `data/processed/`. That is the
path that actually runs in this repository — the Spark zone has never been
produced here.

Rather than renaming the contract, each source table carries a
`meta.external_location` pointing at the equivalent Parquet file. dbt-duckdb
reads it; dbt-bigquery ignores it. One `sources.yml` therefore serves both
targets, and the BigQuery contract is untouched.

## Grain

The item fact grain is (`order_id`, `order_item_id`) and retains every source
item row. It does not invent a `quantity` column or group away the item key.

This was the one real conflict with the pipeline, and it is now resolved at the
source rather than in the models. `src/ecom/cleaning` previously published only
the **aggregated** `order_lines` (one row per order/product/seller, with a
derived `quantity`), which has no item key and so cannot support this fact. It
now publishes **both**: `order_items` at source grain for the warehouse, and
`order_lines` for the analysis, with a pipeline-level invariant asserting the
two carry the same revenue total.

Neither consumer has to undo the other's transform, and
`tests/assert_order_item_revenue_matches_source.sql` re-checks the invariant at
the warehouse boundary.

## Order status

All statuses remain in staging and in `fct_order_items`. `int_order_products`
and `fct_product_cooccurrence` exclude `canceled` and `unavailable` only;
`product_sales_summary` keeps the stricter delivered-only filter.

That split is deliberate and the two models say so. Co-occurrence asks whether
a customer chose two products together, which is settled as soon as the basket
is placed. Sales asks what revenue was realised, and an order still in flight
is not money yet.

### Reconciled with the pipeline

| Measure | Warehouse | `src/ecom/analysis/profile.py` |
|---|---|---|
| Co-occurrence pairs | 4,054 | 4,054 |
| Pair weight sum | 4,476 | 4,476 |
| Order/product memberships | 101,953 | 101,953 |

These agreed only after the rule was fixed on both sides. The warehouse
originally filtered to delivered orders and reported 4,022 while the analysis
counted every status and reported 4,058. Measuring the 36-pair gap showed that
**32 of them came from orders merely in flight** (21 `shipped`, 8 `invoiced`,
5 `processing`) and only 4 from orders that genuinely failed, so neither
original rule was right. Both now use `ecom.config.EXCLUDED_STATUSES`.

## Other decisions

- Category translation is a LEFT join: it covers 71 of the 73 categories
  present, so an inner join would silently drop every product in `pc_gamer` and
  `portateis_cozinha_e_preparadores_de_alimentos`.
- The loader does not deduplicate source rows, and records source file names,
  hashes, row counts and the BigQuery schema in its lineage output.
- Provenance columns (`_run_date`, `_source_hash`, `_loaded_at`) are real
  columns on BigQuery, stamped by the loader. The processed Parquet layer
  deliberately does not carry them — it must stay byte-reproducible, and a load
  timestamp would change on every run — so `macros/portability.sql` synthesises
  them for the DuckDB target.
