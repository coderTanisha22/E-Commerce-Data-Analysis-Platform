# Data Contracts

Single source of truth for interfaces between pipeline stages, per the
team's sequential implementation guide. Each contract below is filled in by
its owner before downstream work starts against it. This file currently
covers only the boundaries Person A owns (ingestion and Spark cleaning); B,
C and D add their own sections as their stages are built.

## Storage decision

Raw and processed data use the **local filesystem**, not MinIO, per the
team's current decision (2026-10-13). All paths are environment-variable
driven (`OLIST_RAW_ZONE_DIR`, `OLIST_PROCESSED_ZONE_DIR`, etc. — see
`data_ingestion/config.py` and `spark/config.py`) so moving to MinIO later
is a config change, not a rewrite.

## Contract 1 — Python → raw zone (owner: A)

| Field | Value |
|---|---|
| Location | `storage/raw/olist/<table_name>/run_date=YYYY-MM-DD/<original_filename>.csv` |
| Format | Original CSV, byte-for-byte unchanged from the Olist source |
| Manifest | `storage/raw/olist/_manifests/<run_date>_<run_id>.json` — one entry per source file: `file_name`, `checksum_sha256`, `row_count`, `run_id`, `status`, `missing_columns`, `ingestion_timestamp_utc` |
| Guarantees | Source files are never modified in place; a re-run writes a new `run_id` rather than overwriting a prior run's raw copy |
| Validation | Each file's header is checked against the required-column list in `data_ingestion/schema_registry.py` before it is copied; a file missing required columns is rejected (status `rejected_missing_columns`) and not copied |

## Contract 2 — Raw → Spark cleaned (owner: A)

| Field | Value |
|---|---|
| Location | `storage/processed/olist/<table_name>/run_date=YYYY-MM-DD/` |
| Format | **Parquet** — chosen over CSV for the processed zone because it enforces a schema on write, is columnar (cheaper for B's dbt/BigQuery loads to scan selectively), and compresses the larger tables (e.g. `olist_geolocation_dataset`, ~1M rows) significantly versus plain CSV. Raw data stays CSV because fidelity to the original Olist export matters more there than storage efficiency. |
| Schema / keys / grain | See `spark/schema_contracts.py` — the single source of truth for each table's business key, required columns, numeric minimums, range checks and date columns. **B should read this file, not infer types from memory, before building staging models.** |
| Invalid-row handling | Rows failing any field-level check (missing required field, numeric value below its minimum, out-of-range value, unparseable date) are quarantined, not dropped: written to `storage/quarantine/olist/<table_name>/run_date=YYYY-MM-DD/` as CSV with the same columns plus per-check `_is_valid` / `_cast_ok` flags, so the specific failure is visible. Duplicate business keys are **reported, not removed** — `duplicate_key_row_count` in the quality report flags them, but all rows stay in the clean output since choosing a dedup strategy (keep-first / keep-latest / merge) is B's call when building staging models, not something to decide silently in Spark |
| Evidence | `storage/reports/data_quality_report_<run_date>.json` — per-table input/output/quarantined row counts, null counts for required columns, and duplicate-key count |

### Current table contracts (from `spark/schema_contracts.py`)

| Table | Business key | Notable nullable fields |
|---|---|---|
| olist_customers_dataset | customer_id | — |
| olist_geolocation_dataset | *(none — many rows per zip by design)* | — |
| olist_order_items_dataset | order_id + order_item_id | — |
| olist_order_payments_dataset | order_id + payment_sequential | — |
| olist_order_reviews_dataset | review_id | review_comment_title, review_comment_message |
| olist_orders_dataset | order_id | order_approved_at, order_delivered_carrier_date, order_delivered_customer_date (null until that stage happens) |
| olist_products_dataset | product_id | product_category_name, all dimension/weight fields |
| olist_sellers_dataset | seller_id | — |
| product_category_name_translation | product_category_name | — |

## Contract 3 — Warehouse → Graph & Discovery (owner: C)

| Field | Value |
|---|---|
| Upstream Source | `dbt_warehouse.marts.fct_product_cooccurrence` or `data/processed/product_cooccurrence.parquet` |
| Format | Parquet / relational table |
| Grain | Unique unordered product pair: (`product_a`, `product_b`) |
| Guarantees | Canonical order `product_a < product_b`; no self-pairs (`product_a != product_b`); `order_count >= 1` |
| Order filter | Excludes `canceled` and `unavailable` orders (`ecom.config.EXCLUDED_STATUSES`). In-flight orders (`shipped`, `invoiced`, `processing`) are preserved. |
| Reconciled metrics | Exactly **4,054 pairs**, **4,881 unique products**, total weight sum **4,476**. |

## Contract 4 — Warehouse → Inventory (owner: D)

*(To be filled by Member D)*

## Contract 5 — Discovery API → UI (owner: C, consumer: D)

| Endpoint | Method | Params / Payload | Response Schema | Description |
|---|---|---|---|---|
| `/products/{product_id}/recommendations` | GET | `limit: int = 5` | `RecommendationResponse` | Ranked neighbors by weight DESC, tie-broken by `product_id ASC`. |
| `/products/search` | GET | `q: str, expand: bool = true, limit: int = 10` | `SearchResponse` | Direct category matches first, followed by 1-hop graph neighbors. |

## Open items for the team

- [ ] Confirm MinIO migration timeline (currently deferred, local filesystem only)

- [x] B to review this file and confirm schema/grain before building staging models (Completed)
- [x] C added graph and discovery contract (Completed)
- [ ] D to add inventory and dashboard contract sections below
