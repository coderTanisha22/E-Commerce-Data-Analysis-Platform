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

All statuses remain in staging and in `fct_order_items`. Only delivered orders
feed `int_order_products`, `product_sales_summary` and
`fct_product_cooccurrence`.

### Known divergence from the pipeline's own analysis

| Measure | Warehouse | `src/ecom/analysis/profile.py` |
|---|---|---|
| Co-occurrence pairs | **4,022** | **4,058** |
| Pair weight sum | 4,437 | 4,481 |
| Order/product memberships | 100,196 (delivered) | 102,425 (all statuses) |

The 36-pair gap is **not** a defect in the SQL. The warehouse counts
co-occurrence over delivered orders only; the pipeline's analysis counts every
order status. Those 36 pairs are evidenced solely by orders that were never
delivered.

The warehouse is the internally consistent one. The pipeline applies a
delivered filter to its sales and velocity metrics but not to co-occurrence, so
it currently mixes the two conventions. **This is an open decision for the
team**, recorded in `docs/PROJECT_STATUS.md` §6, because aligning the pipeline
to delivered-only would change figures already published in the Lab 4&5 report
and the slide deck. It has deliberately not been changed unilaterally.

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
