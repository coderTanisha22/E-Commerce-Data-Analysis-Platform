# E-Commerce Data Platform for Product Co-Occurrence and Inventory Analysis — Project Handbook

**Course:** CSL4030 Data Engineering, IIT Jodhpur, 2026–27 (Semester 5)
**Group:** 9 — Tanisha Ray (B24CM1061), Anika Sharma, Sanika Kole, Harshita Pareek
**Handbook state:** 6 November 2026. Every number below was measured from the code and data in this repository on or before that date.

---

## 0. How to use this file

This file is a complete, self-contained description of the project: what it does, how every part works, every number it produces, why each design choice was made, what was rejected and why, what goes wrong and how to fix it, and what is still weak.

It is written to serve as:

1. **The reference for the system.** Sections 1–5 describe it; sections 6–7 justify it and trace it to the requirements; section 10 lists results; section 12 gives references.
2. **A debugging manual.** Section 9 lists every failure we actually hit, its cause and its fix.

### Table of contents

1. The project at a glance
2. Team, ownership and timeline
3. The dataset (Olist) and what we measured about it
4. Architecture and data flow
5. Every component in depth
6. Design decisions and rejected alternatives
7. Requirements traceability and honest gaps
8. How to run everything
9. Debugging guide
10. Results and numbers cheat sheet
11. Limitations and future work
12. References, citations and AI-use note
13. Glossary
14. File-by-file map of the repository

---

## 1. The project at a glance

**What it is.** A batch data-engineering platform built on the public *Brazilian E-Commerce Public Dataset by Olist* (about 100,000 real orders, 2016–2018). It takes the raw CSV export of an online marketplace, lands it unchanged, cleans and validates it, models it into an analytical warehouse, and serves two business use cases through an API and a web dashboard, all orchestrated by Airflow.

**The two use cases.**

1. **Product co-occurrence ("frequently bought together").** Find which products appear in the same orders, store them as a weighted graph (products are nodes, an edge's weight is the number of distinct orders containing both), and serve deterministic, explainable recommendations and search.
2. **Inventory / restock analytics.** Combine each seller-product's **real** sales velocity with **synthetic** (generated) stock levels, compute days of inventory left, and flag every seller-product as *Urgent*, *Monitor*, *Healthy* or *Insufficient data*.

**A deliberate non-goal: no machine learning.** Recommendations are graph lookups ranked by order counts; restock status is a transparent rule. Every output can be explained line by line, which is a design requirement.

**The stack (all of it runs):**

| Layer | Tool | Role |
|---|---|---|
| Orchestration | Apache Airflow 3.3.2 | Schedules the 9-task daily DAG; never transforms data itself |
| Ingestion | Python | Validates sources against contracts, lands them byte-identical, writes a SHA-256 manifest |
| Storage | Local filesystem or MinIO (S3-compatible object store) | One `StorageBackend` interface, two interchangeable implementations |
| Processing | pandas (main path) + an optional PySpark path | Pure DataFrame transforms behind quality gates |
| File format | Parquet (processed), CSV (raw) | Columnar, typed, compressed |
| Transformation / warehouse | dbt Core | 14 models (staging → intermediate → marts), 36 tests |
| Warehouse engines | DuckDB (local) and Google BigQuery (cloud, sandbox) | Same SQL runs on both; both reconciled against the pipeline |
| Graph | NetworkX | In-memory co-occurrence graph |
| API | FastAPI + Pydantic | 12 endpoints, typed contracts |
| Dashboard | HTML/CSS/JavaScript + D3.js | Served by the API itself |
| Optimisation study | DuckDB, SciPy, PyArrow, custom harness | 18 strategies, 4 storage layouts, scaling sweeps |
| Quality | pytest, ruff, black, dbt tests, custom gates | 161 tests passing |

**Headline facts to remember.**

- The whole pipeline rebuilds from the CSVs, through the warehouse, to a verified API in about **30 seconds** (`make e2e`), and under Airflow's scheduler in about **30 seconds**.
- Only **3.29%** of orders contain two or more distinct products, so the product co-occurrence graph is sparse: **4,054** product pairs, of which **94.9%** were bought together exactly once, reaching **4,881 of 32,951 products (14.8%)**.
- The median seller-product sells **0.0080 units/day** over its active days (about one unit every 125 days).
- The synthetic inventory holds **33,787** seller-products: **206 Urgent, 382 Monitor, 8,363 Healthy, 24,836 Insufficient data**; Urgent rows sell **5.7×** faster than Healthy ones.
- The warehouse (DuckDB **and** BigQuery) matches the pipeline exactly: 112,650 item rows, R$ 13,591,643.70 of item prices, and all 4,054 pairs identical.

---

## 2. Team, ownership and timeline

### 2.1 Roles

The team split the platform into four owned stages, recorded as data contracts in `docs/contracts.md`:

| Role | Member | Owns |
|---|---|---|
| Person A | Sanika Kole | Spark ingestion and cleaning path (`src/ecom/spark/`, `ingestion/run_ingestion.py`, `source_reader.py`, `raw_writer.py`, `source_registry.py`), contracts 1–2 |
| Person B | Harshita Pareek | dbt warehouse (`dbt_warehouse/`): staging, marts, singular tests, original BigQuery loader |
| Person C | Anika Sharma | Graph and discovery service (`src/ecom/discovery/`): NetworkX graph, ranked recommendations, search, Pydantic schemas, D3 graph export, contracts 3 and 5 |
| Person D | Tanisha Ray | API, dashboard and end-to-end run (`src/ecom/api/`), contract 4; also the main pandas pipeline, synthetic inventory, the optimisation study, integration/merges, Airflow DAG, BigQuery run |

### 2.2 Timeline (from git history)

| Date (2026) | Event |
|---|---|
| 14 Aug | Project start date in the Lab 1 tracker (problem statement, dataset selection) |
| 16 Aug | Lab 1 submitted (team, requirements FR_1–FR_6, tracker template) |
| 20 Aug | Initial repository commit |
| 12 Sep | Data audit: sparsity findings (see §3.3) that reshaped both use cases |
| 1 Oct | Optimisation study scoped: pipeline metrics, a baseline, bottlenecks, and strategy comparisons including sharding and vertical/horizontal fragmentation |
| 9 Oct | Lab 4–5 submission commit (ingestion, synthetic data, analysis) |
| 13 Oct | Person A's Spark ingestion/cleaning files added |
| 20 Oct | Person B's dbt warehouse added; branches unified into one modular package |
| 21–22 Oct | Optimisation study; warehouse reconciled with the pipeline; "one evidence rule" fix (§6.2) |
| 22–28 Oct | Person C's graph/discovery service (merged as PR #1 on 2 Nov) |
| 2 Nov | API, dashboard, end-to-end run, reorder-point fix, Airflow DAG, BigQuery sandbox run |
| 3 Nov | Fresh-clone verification; explorer UX fixes; this handbook |

---

## 3. The dataset (Olist) and what we measured about it

### 3.1 Source

*Brazilian E-Commerce Public Dataset by Olist*, published on Kaggle under **CC BY-NC-SA 4.0** (non-commercial use with attribution and share-alike). It is a real, anonymised export of the Olist marketplace, where many independent sellers list products and a customer's order can contain items from several sellers. The nine CSVs are committed under `data/` (about 126 MB in total) and are **never modified by code** (the source directory is read-only by rule).

| File | Size | Rows | Used? | Why / why not |
|---|---|---|---|---|
| `olist_orders_dataset.csv` | 17.7 MB | 99,441 | Yes | Order header: customer, status, five timestamps |
| `olist_order_items_dataset.csv` | 15.4 MB | 112,650 | Yes | One row per **unit** sold; product, seller, price, freight |
| `olist_products_dataset.csv` | 2.4 MB | 32,951 | Yes | Catalogue: category and physical attributes |
| `olist_customers_dataset.csv` | 9.0 MB | 99,441 | Yes | Customer per order (96,096 unique persons) |
| `olist_sellers_dataset.csv` | 0.2 MB | 3,095 | Yes | Seller location (city, state) |
| `product_category_name_translation.csv` | <0.1 MB | 71 | Yes | Portuguese → English category names |
| `olist_order_payments_dataset.csv` | 5.8 MB | 103,886 | No | Payment instalments; not needed by either use case |
| `olist_order_reviews_dataset.csv` | 14.5 MB | 99,224 records (104,719 physical lines) | No (used in the benchmark only) | Not needed; its review text contains newlines inside quoted fields, which made it the test case that caught a wrong fast row-counter |
| `olist_geolocation_dataset.csv` | 61.3 MB | 1,000,163 | No | Zip-code coordinates; no use case needs geography at that resolution |

The Spark path (Person A) declares contracts for all nine files (`src/ecom/source_registry.py`, `src/ecom/spark/schema_contracts.py`); the main pandas path ingests the six it needs (`src/ecom/contracts.py`, `OLIST_CONTRACTS`).

### 3.2 Logical schema and keys

```
customers (customer_id PK, customer_unique_id, zip_code_prefix, city, state)
orders    (order_id PK, customer_id FK→customers, order_status,
           order_purchase_timestamp, order_approved_at, order_delivered_carrier_date,
           order_delivered_customer_date, order_estimated_delivery_date)
order_items (order_id FK→orders, order_item_id, product_id FK→products,
             seller_id FK→sellers, shipping_limit_date, price, freight_value)
             PK = (order_id, order_item_id)      -- composite key
products  (product_id PK, product_category_name, name/description LENGTHS, photos_qty,
           weight_g, length/height/width_cm)
sellers   (seller_id PK, zip_code_prefix, city, state)
category_translation (product_category_name PK, product_category_name_english)
```

All IDs are 32-character hexadecimal strings — **natural keys** already anonymised by Olist (they behave like hashes). No surrogate keys are introduced in the main pipeline. `customer_id` is per order; `customer_unique_id` identifies the person (99,441 vs 96,096).

### 3.3 Measured properties that drove the design (the "data audit")

These were measured, not assumed. They are the single most important context for every design choice.

**Data quality is good, structure is hostile.**
- Referentially clean: 0 orphan foreign keys, 0 duplicate rows, all primary keys unique.
- `order_items` has **no quantity column**: each row is one unit. 10,225 rows repeat an (order_id, product_id) pair; they must be **aggregated** into a quantity, not deduplicated (deduplicating would silently delete revenue). After aggregation: 102,425 order lines; 7,088 lines have quantity > 1; maximum quantity 20.
- `products` has **no product name or description text**, only their character *lengths* (`product_name_lenght`, sic). Keyword search is impossible; category is the only searchable attribute. Display names in the API are therefore *synthesised* deterministically (`discovery/names.py`), e.g. "Urban Bed Bath Table Edition · #EE4A".
- The translation table covers **71 of 73** categories (`pc_gamer` and `portateis_cozinha_e_preparadores_de_alimentos` are missing), so every join to it must be a LEFT join with a fallback.
- 610 products have a NULL category → explicit `unknown` bucket. 775 orders have no item rows (a documented Olist quirk, declared as a *warning*, not an error).
- Order status counts: delivered 96,478; shipped 1,107; canceled 625; unavailable 609; invoiced 314; processing 301; created 5; approved 2.
- Purchase timestamps run from 2016-09-04 to 2018-10-17, but the **usable window is 2017-02-01 to 2018-08-31** (577 days): November 2016 has 0 orders, December 2016 has 1, and 19 of the last 20 orders (September–October 2018) are cancelled.

**Co-occurrence is extremely sparse.**
- Only **3.29%** of countable orders (3,231 of 98,199) contain ≥2 distinct products. Basket sizes: 1 product 94,968; 2 → 2,841; 3 → 298; 4 → 70; 5 → 8; 6 → 10; 7 → 3; 8 → 1.
- **4,054** distinct product pairs; **3,848 (94.92%)** have weight 1; only **206** pairs were bought together in ≥2 orders; maximum weight 34; total weight 4,476.
- The graph reaches **4,881 of 32,951 products (14.8%)**; 1,652 connected components; the largest has 398 products; 67.1% of nodes have exactly one neighbour.
- **Consequence:** product-level recommendation cannot cover the catalogue. The design is two-tier: product-level edges where they exist, and a **category-level fallback** (categories co-purchased together; 98.2% coverage) for the ~85% of products with no co-purchase.

**Sales velocity is very low.**
- 33,262 seller-products sold at least once in the window; the median sells **0.0080 units/day** (~1 unit per 125 days) measured over its *active days* (days since its first sale, minimum 30 — the definition the inventory uses). Over the whole 577-day window the median is 0.0017 units/day (`profile.json`). 56% sold exactly one unit in 577 days.
- **Consequence:** a restock rule with random stock levels flags nothing (0.0% Urgent). Stock has to be generated *from each seller-product's own velocity* for the rule to say anything.

**Skew.**
- Sellers are concentrated: 23 states, but São Paulo (SP) holds **59.7%** of sellers and **68.8%** of inventory rows (next: PR 11.3% of sellers, MG 7.9%). Fragmenting by geography would be badly unbalanced; hashing on `seller_id` is balanced by construction.
- Delivered item rows per month range from 1,711 to 7,616 inside the window, so range fragmentation on month is uneven (hash fragmentation is even by construction).

**It is not "big data".** About 126 MB on disk (≈120 MiB) for all nine files, ~350k rows across the six used tables. The whole pipeline runs in seconds on a laptop. The project's honest claim is the opposite of a big-data claim: the data is small enough to *measure precisely* (full factorial of layouts and volumes, crossover points rather than anecdotes), and the patterns built here (contracts, idempotency, partitioning, columnar storage, verified optimisation, orchestration) are the ones that transfer to a volume that would need a cluster. The scaling study (§5.13) extrapolates to 8× volume.

## 4. Architecture and data flow

### 4.1 The big picture

```
                              Airflow DAG "ecom_pipeline" (@daily, Airflow 3.3.2)
  ┌──────────────────────────────────────────────────────────────────────────────────────┐
  │ extract_olist → store_raw → spark_clean ─┬─ dbt_build ─────────────┐                  │
  │                                          ├─ build_cooccurrence ────┼─ validate_models ─┐
  │                                          │        └─ build_graph ──────────────────────┤
  │                                          └─ refresh_inventory_metrics ─────────────────┴─ dashboard_ready
  └──────────────────────────────────────────────────────────────────────────────────────┘

 data/*.csv (source, read-only)
     │  ingestion: contract check, byte-identical copy, SHA-256 manifest
     ▼
 raw zone   raw/olist/<table>.csv  +  raw/_manifest.json          (local disk or MinIO bucket)
     │  cleaning: pure transforms + quality gates + revenue invariant
     ▼
 processed  processed/<table>.parquet  +  _quality_report.json
     │                │                        │                         │
     │                │ analysis               │ synthetic inventory     │ dbt (DuckDB local /
     │                ▼                        ▼                         ▼  BigQuery cloud)
     │   product_cooccurrence.parquet   synthetic_inventory.parquet   staging → intermediate → marts
     │   profile.json + figures         + manifest (seed, SHA-256)    fct_order_items, dims,
     │                │                        │                      fct_product_cooccurrence ...
     │                ▼                        │                         │
     │      NetworkX graph (discovery)         │                         │ reconciled against the
     │                └──────────┬─────────────┘                         │ processed layer
     ▼                           ▼                                       ▼
                       FastAPI (12 endpoints, data held in memory) ──► Dashboard (/)
```

### 4.2 Layers and zones

| Zone | Format | Mutability | Purpose |
|---|---|---|---|
| Source (`data/*.csv`) | CSV as downloaded | Read-only, never written by code | Evidence |
| Raw (`raw/olist/<table>.csv`) | Byte-identical copy + manifest | Overwritten per run, with a new manifest | Reproducibility, provenance |
| Processed (`processed/<table>.parquet`) | Typed Parquet, renamed columns | Overwritten per run | Analysis input |
| Warehouse (DuckDB file / BigQuery datasets) | Relational tables/views | Rebuilt per run | Modelled, tested, queryable |
| Serving (API memory) | Python objects (DataFrames, NetworkX graph) | Loaded at API start-up | Low-latency reads |

This is the same idea as the *medallion* (bronze/silver/gold) pattern: raw = bronze, processed = silver, marts = gold.

### 4.3 Engineering rules that shape the whole codebase (`docs/CODING_STANDARDS.md`)

1. **The purity rule (most important).** A transform takes a DataFrame and returns a DataFrame and never does I/O. Reading and writing happen only in `storage/`, `ingestion/` and the `run_*` orchestrator modules. Consequences: every rule is unit-testable on a 5-row fixture in milliseconds, and a port to PySpark changes only the I/O calls.
2. **Every threshold is a named constant** in `config.py` (or the module that owns it) with a comment explaining *why* that value (e.g. `MIN_COOCCURRENCE_COUNT = 2` "edges seen in a single order are noise: 94.9% of raw pairs have weight 1").
3. **Fail loudly.** Quality checks *raise* (`DataQualityError`); a warning must be explicitly declared (`severity="warn"`) and is reserved for documented Olist quirks.
4. **No `print()` outside `cli.py`.** Everything else logs through `logging_setup`.
5. **Contracts.** Every table has a declared contract (columns, key, dtypes, expected rows, foreign keys) in `contracts.py`.
6. **Naming.** `snake_case`; boolean columns `is_`/`has_`; timestamps `_at`; dates `_date`; counts `_count`. Airflow task IDs and API paths are lowercase and resource-oriented (no verbs in URLs).
7. **SQL style.** Uppercase keywords, named CTEs, no `SELECT *`, explicit joins, and every fact model has a uniqueness test on its declared grain.
8. **Functions ≤ 50 lines** (checked by `make loc`); five known exceptions are listed in the standards.
9. **Commits** follow `<type>: <summary>` and never include `data/raw`, `data/processed` or `.env`.

---

## 5. Every component in depth

### 5.1 Configuration (`src/ecom/config.py`)

`Settings` is a frozen pydantic-settings object read from environment variables with prefix `ECOM_` or from `.env`:

| Variable | Default | Meaning |
|---|---|---|
| `ECOM_STORAGE_BACKEND` | `local` | `local` or `minio` |
| `ECOM_SOURCE_DIR` | `data` | Untouched Olist download |
| `ECOM_RAW_ROOT` / `ECOM_PROCESSED_ROOT` | `data/raw` / `data/processed` | Local zone roots |
| `ECOM_MINIO_ENDPOINT/ACCESS_KEY/SECRET_KEY/BUCKET/SECURE` | `localhost:9000`, `minioadmin`, `minioadmin`, `ecom-platform`, false | MinIO backend |
| `ECOM_WINDOW_START` / `ECOM_WINDOW_END` | 2017-02-01 / 2018-08-31 | Analysis window (577 days) |
| `ECOM_FAST_READER` | false | Parse raw CSVs with Arrow (the one landed optimisation) |
| `ECOM_DBT_DUCKDB_PATH` | `.duckdb/ecom_dw.duckdb` (relative to `dbt_warehouse/`) | Local warehouse file |
| `ECOM_GCP_PROJECT`, `ECOM_GCP_LOCATION`, `ECOM_BIGQUERY_DATASET` | none, `US`, `olist_analytics_dev` | BigQuery target |
| `ECOM_API_HOST` / `ECOM_API_PORT` | `127.0.0.1` / 8000 | API binds to loopback by default because it has no authentication |
| `ECOM_LOG_LEVEL`, `ECOM_REPORTS_DIR` | `INFO`, `reports` | |

Domain constants in the same file: `DELIVERED_STATUS = "delivered"`; `EXCLUDED_STATUSES = ("canceled", "unavailable")` — the project's single rule for which orders count as evidence (§6.2); `UNKNOWN_CATEGORY = "unknown"`; `MIN_COOCCURRENCE_COUNT = 2`; window dates.

### 5.2 Storage layer (`src/ecom/storage/`)

- `StorageBackend` (abstract base class) addresses data by **logical key** (`raw/olist/orders.csv`, `processed/orders.parquet`), never by path or bucket. Methods: `put_bytes`, `get_bytes`, `exists`, `list_keys`, `describe`, plus conveniences `put_parquet`, `get_parquet`, `get_csv`, `get_csv_arrow`.
- `LocalStorage` maps keys to directories; `MinioStorage` maps keys to objects in an S3-compatible bucket (`docker compose up -d minio`, console on :9001).
- `get_storage(settings)` is the only factory the pipeline calls, so switching backends is a one-variable change (`ECOM_STORAGE_BACKEND=minio`). The key layout is identical in both (verified).
- **Why both exist:** two of the team's spec documents said "MinIO is excluded, use the local filesystem", two others mandated MinIO. The adapter resolves the contradiction in code: both are supported, local is the default.
- The interface is a **key–value store**: conceptually a key-value store.

### 5.3 Ingestion (`src/ecom/ingestion/ingest.py`) — source → raw

For each contracted table (`OLIST_CONTRACTS`: orders, order_items, products, customers, sellers, category_translation):

1. Read the source file bytes. Missing file → `IngestionError`.
2. `validate_against_contract`: every declared column must be in the header (missing → error; extra columns are logged, not fatal, because a widened source should not halt a batch while a missing column silently breaks joins). Count data rows.
3. Write the bytes **unchanged** to `raw/olist/<table>.csv`.
4. Record a `TableManifest`: table, source file, raw key, rows, columns, bytes, **SHA-256**, expected rows, row drift vs the reference count.
5. After all tables, write `raw/_manifest.json` (`ingested_at`, source dir, storage, table count, total rows = 347,649).

Properties: **idempotent** (unchanged input → identical manifest, provable by hash), **fail-fast** (first bad table aborts the run, so a partial raw layer is never reported as success), **auditable** (hashes prove what was landed).

A second, more elaborate ingestion path by Person A (`run_ingestion.py`, `source_reader.py`, `raw_writer.py`) writes date-partitioned raw zones (`storage/raw/olist/<table>/run_date=YYYY-MM-DD/`) with run IDs and per-file manifests for the Spark path.

### 5.4 Cleaning (`src/ecom/cleaning/`) — raw → processed

`run_clean.clean_all()` orchestrates; `transforms.py` holds the pure rules, applied in dependency order:

| Transform | What it does | Why |
|---|---|---|
| `trim_whitespace` | Strip leading/trailing spaces in string columns | Defensive; measured: no Olist column actually has padding |
| `coerce_types` | Cast declared timestamp and numeric columns to real dtypes | CSV has no types; Parquet keeps them |
| `normalise_category` | NULL category → `unknown` | 610 products; never silently drop them |
| `attach_english_category` | LEFT join translation, fall back to the Portuguese slug | 71 of 73 categories translated |
| `flag_order_status` | Add `is_delivered` instead of deleting rows | Different consumers need different filters (§6.2) |
| `derive_order_lines` | Aggregate unit rows into lines with a real `quantity`, `unit_price`, `line_revenue`, `line_freight` | No quantity column; aggregate, never deduplicate |
| `build_order_products` | Distinct (order_id, product_id) pairs | Co-occurrence input |

**Quality gates** (`quality/checks.py`; each check returns a `CheckResult`, `run_gate` raises on any error-severity failure):

- *Raw gate (before any transform):* primary-key uniqueness for all six tables; no nulls in key columns of `order_items` and `orders`; foreign keys `order_items→orders`, `order_items→products`, `order_items→sellers`, `orders→customers`; `order_items` row count ≥ 100,000; and `orders_without_items` declared as a **warning** (775 known).
- *Processed gate (before anything is written):* uniqueness of `orders.order_id`, `order_items(order_id, order_item_id)`, `order_products(order_id, product_id)`; no nulls in `products.product_category_english`, `order_lines.quantity`, `order_lines.line_revenue`.
- *Revenue invariant:* the sum of `line_revenue` after aggregation must equal the sum of `price` before it (R$ 13,591,643.70). This proves the line collapse *aggregated* rather than *deduplicated*.

Only if every gate passes are the seven processed tables written (`orders` 99,441; `order_items` 112,650; `order_lines` 102,425; `order_products` 102,425; `products` 32,951; `customers` 99,441; `sellers` 3,095) plus `_quality_report.json` with every check result. A failed gate leaves the previous processed layer untouched.

The optional **fast reader** (`ECOM_FAST_READER=1`) parses CSVs with Arrow (`StorageBackend.get_csv_arrow`, with `strings_can_be_null=True`); it produces a value-identical processed layer and reproduces the same downstream SHA-256.

### 5.5 Analysis and co-occurrence (`src/ecom/analysis/profile.py`)

- `select_countable_orders(order_products, orders)` drops memberships whose order status is in `EXCLUDED_STATUSES` (a **semi-join** filter: keep rows of A whose key appears in the countable set of B).
- `build_cooccurrence(order_products)`: for every order with ≥2 distinct products, emit every unordered pair `(a, b)` with `a < b` (canonical order removes self-pairs and double counting), then count distinct orders per pair → `product_cooccurrence.parquet` (`product_a`, `product_b`, `order_count`; 4,054 rows).
- `profile_sales` (delivered orders in the window: 95,461 orders, revenue R$ 13,069,228.77, AOV R$ 136.91, units 108,967, orders per month), `profile_cooccurrence` (basket distribution, pair weights, graph components, degrees), `profile_velocity` (per seller-product units/day) → `reports/profile.json`; `visualize.py` renders 8 figures.

### 5.6 Synthetic inventory (`src/ecom/synthetic/`)

**Why synthetic:** Olist records sales but no stock. Without stock, "days of inventory" cannot be computed and the restock use case has no input. The design keeps every sales-derived number real and generates only what is missing, and flags every row `is_synthetic = True`.

**Columns (14):**

| Group | Columns | How produced |
|---|---|---|
| Real (7) | `seller_id`, `product_id`, `units_sold`, `first_sale_date`, `active_days`, `daily_sales_rate`, `evidence` | From real orders only, no randomness |
| Synthetic (3) | `lead_time_days`, `current_quantity`, `last_restock_date` | Seeded random generator (seed 42) |
| Derived (3) | `reorder_point`, `days_of_inventory`, `status` | Deterministic formulas of the above |
| Flag | `is_synthetic` | Always true |

**Formulas (constants in `synthetic/inventory.py`):**

- Eligible demand: order lines whose order status is not `canceled`/`unavailable`, purchased inside the window.
- `units_sold` = Σ quantity per (seller, product); `first_sale_date` = earliest purchase date.
- `active_days` = max(`MIN_ACTIVE_DAYS` = 30, `AS_OF` (2018-09-01) − `first_sale_date`) — the floor stops a product first sold three days ago from showing an absurd rate.
- `daily_sales_rate` = `units_sold` / `active_days`.
- `evidence` = `sufficient` if `units_sold` ≥ `EVIDENCE_MIN_UNITS` = 3, else `insufficient` (a rate from one or two sales is noise; such rows are labelled, never dropped).
- `lead_time_days` ~ Uniform{5..20}, drawn **once per seller** (lead time is a property of a supplier relationship, so every product of a seller shares it).
- `reorder_point` = round(`daily_sales_rate` × (`lead_time_days` + `SAFETY_DAYS` = 3), 2) — **fractional units**.
- `current_quantity` = max(`MIN_STOCK_UNITS` = 1, round(`daily_sales_rate` × (`lead_time_days` + 3) × Uniform(0.2, 3.0))).
- `last_restock_date` = `AS_OF` − Uniform{1..60} days.
- `days_of_inventory` = `current_quantity` / `daily_sales_rate`.
- `status`: `Insufficient data` if evidence is insufficient; else `Urgent` if days_of_inventory < lead_time; else `Monitor` if < lead_time + `MONITOR_EXTRA_DAYS` (7); else `Healthy`.

**Result:** 33,787 rows (34,448 seller-product pairs exist in all data; 661 sold only in cancelled orders or outside the window and get no stock). Urgent 206 (0.61%), Monitor 382 (1.13%), Healthy 8,363 (24.75%), Insufficient data 24,836 (73.51%). SHA-256 of the table `8afabc716a0ea56be42555a942ec21c2071a03ef31b67ab935ef7c189a326a35`, reproducible from seed 42; `processed/_synthetic_inventory_manifest.json` records parameters, seed, hash and status counts.

**Validation (`synthetic/validate.py`, `make validate-inventory`, report in `reports/synthetic_inventory_validation.md`):** formula exactness on every row; one lead time per seller; every pair exists in real order lines; real input tables hashed before and after generation (unchanged); same seed → same hash, different seed → different hash, and only synthetic columns change across seeds; 30-seed stability (Urgent 0.579% ± 0.040); sensitivity sweeps over safety days, stock factor and lead time (all move in the expected direction: longer lead times → more Urgent, 0.15% at (3,10) to 1.19% at (10,30)).

**The reorder-point fix (2 Nov) — a real bug found and fixed.** The first version computed stock as round(ceil(reorder point) × factor). Because 96.4% of reorder points were rounded *up* to 1, any factor below 0.5 rounded stock to **zero**, which reads as a stock-out, so 85.3% of the 966 Urgent rows were urgent purely by rounding and Urgent rows sold no faster than Healthy ones (1.1×). 2,776 of 8,951 scored rows sat at or below their reorder point while labelled Healthy. The obvious fix (a non-integer reorder point alone) was **measured and found worse** (96.6% of Urgent rows at zero stock; Urgent rows sold 0.4× as fast as Healthy). The fix needed both parts: fractional reorder point, and stock drawn from exact demand with a one-unit floor. After the fix: 0 zero-stock rows, Urgent rows sell **5.7×** faster than Healthy (median 10.8 days of cover vs 14.5-day lead time), no Healthy row at or below its reorder point, Spearman ρ(reorder point, rate) 0.93.

### 5.7 Graph and discovery service (`src/ecom/discovery/`, Person C)

- `ProductGraphService(pairs, products)` builds an undirected `networkx.Graph`: node = product, edge weight = `order_count`. Canonical ordering enforced, self-pairs skipped.
- `get_recommendations(product_id, limit)`: neighbours sorted by weight descending, ties broken by `product_id` ascending (deterministic). Unknown product → empty list, not an error.
- `search_products(query, expand_graph, limit)`: direct matches on English category (query treated as **literal text**, spaces matched to slugs — "bed bath" finds `bed_bath_table`), **ranked by graph degree** so connected products come first, then 1-hop neighbours of the matches ("expanded") by weight. Each result carries `degree` (0 = no co-purchases).
- `to_node_link_data(...)`: ego network around a product, or the strongest edges globally (default `min_weight` 2, up to 150 nodes) — JSON for D3.
- `category_relations(category)`: the **category-tier fallback** — categories whose products were bought with this category's products (summed cross-category edge weights) and this category's most-connected products. Example: computers_accessories → garden_tools (11 orders), electronics (7), telephony (6), auto (5).
- `names.py`: deterministic display names seeded from the product ID's hex prefix ("Deluxe Watches Gifts Series · #4244"), so the same ID always gets the same title.
- `visualize.py`: standalone interactive D3 HTML export (`ecom visualize-graph`).

### 5.8 dbt warehouse (`dbt_warehouse/`, Person B; reconciled by Person D)

**Layering:** staging (6 models: clean types, rename, add provenance columns) → intermediate (1: `int_order_products`) → marts (7). On BigQuery, staging/intermediate are **views** and marts are **tables**; on DuckDB everything is a table (sources are read with relative paths, so views would break outside the build directory).

| Model | Grain | Notes |
|---|---|---|
| `stg_orders`, `stg_order_items`, `stg_products`, `stg_customers`, `stg_sellers`, `stg_category_translation` | 1 row per source row | `safe_cast` types; fixes the source's misspelt `*_lenght` columns; provenance columns `_run_date`, `_source_hash`, `_loaded_at` |
| `int_order_products` | (order_id, product_id), countable orders only | `WHERE LOWER(order_status) NOT IN ('canceled','unavailable')` — same rule as the pipeline |
| `fct_order_items` | (order_id, order_item_id) — finest grain the source has | Joins orders for customer, `order_date`, status; `item_total_amount`; `order_month_key` (YYYYMM). BigQuery: integer-range partition on `order_month_key` (201601–203001), cluster by `product_id, seller_id` |
| `fct_product_cooccurrence` | unordered pair (product_a < product_b) | Self-join of `int_order_products` on `order_id` with `a < b`, `COUNT(*)`; clustered by `(product_a, product_b)` |
| `dim_products` | product | LEFT join translation; `COALESCE(english, slug, 'unknown')` |
| `dim_customers`, `dim_sellers` | customer / seller | |
| `dim_dates` | calendar day 2016-01-01..2018-12-31 | Date spine with year, month, day of week, `year_month` |
| `product_sales_summary` | product | Delivered-only sales, item lines per day over the observed window |

**Tests (36):** generic `not_null`/`unique`/`relationships` tests in `schema.yml` (including the new `not_null` on `order_month_key`), plus five singular tests: `assert_no_self_or_reverse_pairs`, `assert_order_item_revenue_matches_source` (price total preserved), `assert_pair_orders_le_product_orders` (a pair cannot appear in more orders than either product — catches join fan-out), `unique_order_item_key`, `unique_order_product_membership`. `dbt build`: **50/50 pass** (14 models + 36 tests) on DuckDB and on BigQuery.

**Portability macros (`macros/portability.sql`):** `provenance_columns`, `date_spine_days`, `year_month`, `day_of_week`, `safe_divide` hide dialect differences between DuckDB and BigQuery so models read as plain SQL.

**This is a star schema** (Kimball): fact `fct_order_items` at a declared grain, surrounded by dimensions (products, customers, sellers, dates). `fct_product_cooccurrence` is a second fact sharing the product dimension (a small *galaxy*/fact constellation).

### 5.9 BigQuery (cloud warehouse)

- **Project:** `de-group-9` in the free **BigQuery sandbox** (no billing account; 10 GB storage, 1 TB queries per month; tables expire after 60 days). Created under the college Google organisation (`iitj.ac.in`).
- **Load:** `dbt_warehouse/scripts/load_to_bigquery.py` maps the six source tables (contract names, e.g. `olist_orders_dataset`) to the pipeline's processed Parquet files (translation from the raw CSV), adds provenance columns (`_run_date`, `_source_hash` = SHA-256 of the file, `_loaded_at`), loads each with a **load job** (`WRITE_TRUNCATE`, not DML, so it works in the sandbox), checks the loaded row count equals the sent row count, and writes `docs/load_lineage_<date>.json`.
- **Datasets:** `olist_cleaned` (sources), `olist_analytics_dev` (models), location `US`.
- **Run:** `make warehouse-bq` = load → `dbt build --target bigquery` (50/50) → `ecom reconcile-warehouse --target bigquery` (5/5). About 2 minutes.
- **The sandbox bug we found:** the sandbox forces a 60-day expiry on *time-unit* partitions. `fct_order_items` was DATE-partitioned on `order_date`; every Olist order is from 2016–2018, so every partition expired on arrival and the table had **0 rows** — while every `not_null` and `relationships` test still passed (an empty table violates nothing). Only the revenue-invariant test caught it. Fix: **integer-range partitioning** on `order_month_key`, which expiry does not touch. Pruning verified with free dry runs: reading 2 of 24 monthly partitions scans **79% fewer bytes** than a full scan.
- **Authentication:** `gcloud auth application-default login` (the Google Cloud data scope must be ticked on the consent page) and `gcloud auth application-default set-quota-project de-group-9`.

### 5.10 Reconciliation (`src/ecom/quality/reconcile.py`, `src/ecom/orchestration/steps.py`)

Two independent implementations must agree — that is evidence, not tautology:

| Check | Local DuckDB | BigQuery |
|---|---|---|
| `fct_order_items` rows = processed `order_items` | 112,650 = 112,650 | 112,650 = 112,650 |
| `dim_products` rows | 32,951 | 32,951 |
| `dim_sellers` rows | 3,095 | 3,095 |
| `SUM(price)` = processed price sum (tolerance R$ 0.011) | 13,591,643.70 | 13,591,643.70 |
| `fct_product_cooccurrence` (SQL) vs `product_cooccurrence.parquet` (pandas), row for row | 0 differences of 4,054 | 0 differences of 4,054 |

`ecom reconcile-warehouse [--target duckdb|bigquery]` runs the same checks through two small adapters. A separate script, `dbt_warehouse/scripts/local_validate.py` (`make warehouse-reconcile`), recomputes the invariants independently from the original CSVs.

### 5.11 API (`src/ecom/api/`, FastAPI)

- `loader.load_platform()` reads the processed layer **once** at start-up (~1 s), builds the `ProductGraphService` and the `InventoryService`, and precomputes the overview using the *same* analysis functions as `profile.json` (so the API cannot report a different revenue). A missing table fails start-up with a message naming `make pipeline`.
- `InventoryService` is pure (built from DataFrames): joins category and seller location, synthesises names, sorts deterministically (Urgent → Monitor → Healthy → Insufficient data, then days of inventory ascending, then seller_id, product_id) so pagination is stable.
- Routes only query in-memory services; tests inject a fixture-built `PlatformData`, so every endpoint is tested without data on disk.

| Endpoint | Purpose |
|---|---|
| `GET /health` | Liveness, storage backend, ingestion and inventory build timestamps, graph and inventory sizes |
| `GET /overview` | KPIs: delivered revenue and orders, AOV, multi-product share, pairs, graph products, orders per month, inventory summary |
| `GET /products/search?q=&expand=&limit=` | Category search ranked by connectedness, plus 1-hop expansion |
| `GET /products/graph?min_weight=&max_nodes=` | Strongest co-purchase edges (node-link JSON) |
| `GET /products/{id}` | Name, category, graph degree, per-seller inventory (404 if unknown) |
| `GET /products/{id}/recommendations?limit=` | Neighbours by weight (empty list, not 404, for no co-purchases) |
| `GET /products/{id}/graph` | Ego network |
| `GET /categories/{category}/related` | Category-tier fallback (404 if unknown) |
| `GET /inventory?status=&seller_id=&category=&limit=&offset=` | Filtered, paginated restock list; `status` restricted to the four real values (422 otherwise); page size ≤ 500 |
| `GET /inventory/summary` | Count and share per status (zero rows included), top 10 urgent categories, category list |
| `GET /sellers/{id}/inventory` | One seller's rows (404 if none) |
| `GET /` | The dashboard; `/static/*` its assets; `/docs` interactive OpenAPI docs |

Input validation: query lengths and ranges via FastAPI `Query` constraints; search input is literal text (a regex metacharacter like `(` used to crash the service; fixed). Responses to `/` and `/static/*` carry `Cache-Control: no-cache` so browsers revalidate after updates.

### 5.12 Dashboard (`src/ecom/api/static/`)

A single page served by the API (no separate front-end server, no Node toolchain): five KPI tiles; orders-per-month line chart with hover crosshair; restock status as a segmented bar with icon + label legend; "most urgent categories" bar chart (click to filter); the restock list with status/category/seller filters and pagination; a product explorer (search, ranked results labelled "bought with N" or "no co-purchases", product detail, recommendations, a force-directed D3 ego graph fitted to the panel, and the category fallback for products with no co-purchases); a "strongest pairs" global graph. Light and dark themes; all text inserted with `textContent` (no HTML injection). D3 7.9.0 is loaded from cdnjs; without internet the tables and tiles still work but charts do not draw. Deep links: `/#product=<id>`.

### 5.13 Optimisation study (`src/ecom/bench/`, `make bench`)

Built in response to the 1 October feedback. Seven modules (~3,100 lines), 27 tests. Every timing is the median of 5 runs after a discarded warm-up; every strategy's **output is compared with the baseline's**, and a faster strategy that returns a different answer is reported as rejected, never as a win. Report: `reports/benchmarks/optimisation_report.md`, generated from `results.json` (no hand-typed numbers); five figures.

**Baseline (whole pipeline, earlier measurement):** 5.17 s, peak 499 MB; clean 2.31 s (44.8%), inventory 1.36 s (26.3%), ingest 0.82 s (15.8%), analyse 0.68 s (13.1%).

**Strategy comparison (5 operations, 18 implementations):**

| Operation | Strategies (speedup vs baseline) | Winner |
|---|---|---|
| Co-occurrence self-join | nested loop (J1, baseline 1.00), hash join pandas (J4, 1.40), sort-merge numpy (J3, 0.60 — rejected, slower), sparse matrix BᵀB scipy (2.00), SQL on DuckDB (1.46) | sparse matrix at 1×; **DuckDB at 8×** |
| CSV row count | csv module (1.00), Arrow (7.81), newline bytes (12.45 — **wrong answer**: overcounts reviews by 5,495 rows because of newlines inside quoted text) | Arrow |
| CSV read + trim | string dtype (1.00), object (1.02), Arrow strings (1.25), Arrow + skip (1.33), **Arrow parser (11.91)** | Arrow parser |
| Timestamp parsing | inferred (1.00), explicit format (1.05), Arrow strptime (0.81 — slower) | effectively none |
| Parquet projection | read all 12 columns (1.00), projection pushdown 2 of 12 (5.34) | projection |

**Landed:** the Arrow CSV reader behind `ECOM_FAST_READER`: 11.9× on the component, **1.27×** on the whole cleaning stage (1.74 s → 1.37 s; 1.3–1.8× across runs). The gap is **Amdahl's law** measured: the read is only part of the stage. Output identical value by value and the inventory SHA-256 reproduces exactly. Default left off so published figures come from the long-standing path.

**Fragmentation (at 4× volume, 396,520 rows):**

| Layout | Files | Storage vs monolithic | Full scan | 2 of 19 months | One seller |
|---|---|---|---|---|---|
| Monolithic Parquet | 1 | 0% | 1.00 | 1.00 | 1.00 |
| Horizontal by month | 19 | **−20%** | 0.19× | **3.64×** (96.5% fewer bytes) | 0.85× |
| Vertical hot/cold | 2 | +3.8% | 0.83× | **0.025×** (40-fold penalty) | 0.98× |
| Hash-sharded by seller (16) | 16 | +1.6% | 0.22× | 0.44× | **10.27×** (92.2% fewer bytes) |

- **No layout wins everything**: each wins the access pattern it was designed for and loses the others.
- **Selectivity crossover ≈ 53%** (five runs: 49–57%): below it partition pruning wins (up to 5.29× at one month, 98.6% fewer bytes); above it the partitioned layout is slower (0.47× on a full scan) because of per-file overhead.
- Partitioning *reduced* storage 20% (a constant column dictionary-encodes away, time clustering helps compression), yet was slower on a full scan: **bytes on disk are not the binding constraint, per-file overhead is.**
- **Vertical fragmentation rejected**: its saving (read only hot columns) is what Parquet's column pruning gives the monolithic file for free; a query spanning the split pays a 40× rejoin.
- **Shard count sweep:** speedup 5.03× (4), 12.14× (16), **18.67× (64, +5.0% storage)**, 21.07× (256, +9.8%), 22.48× (1,024, +25.6%), 23.43× (4,096, +79.7%). Recommendation = smallest count on the plateau within a 10% storage budget → **64** (64 vs 256 not reliably distinguishable). Shard function `blake2b(seller_id) % n` (stable across processes, unlike Python's salted `hash()`).

**Materialisation vs pipelining:** writing Parquet between stages costs **~625%** over in-memory pipelining on a cheap three-stage sequence, and is kept deliberately: it buys restartability and lets quality gates inspect each stage.

**Scaling (co-occurrence at 1×/2×/4×/8×):** fitted exponents k in time ∝ rows^k: nested loop 1.14, hash join 1.05, sort-merge 1.17, sparse 1.14, **DuckDB 0.74** (sub-linear: parallelism grows with work). Spread between strategies grows from 3.0× at 1× to 6.6× at 8×, and the winner changes (sparse → DuckDB). The naive nested loop is not catastrophic here because only 3.3% of baskets have ≥2 products, so the quadratic term rarely fires: an optimisation's value depends on the data's shape, not only the algorithm's complexity class.

**Defects the correctness check caught:** the wrong newline row counter; Arrow's default CSV options reading 2,965 empty delivery dates as `""` instead of null (fixed with `strings_can_be_null=True` before adoption). Both would have produced faster, plausible, wrong pipelines.

**Three earlier claims corrected by re-measurement:** the 16.9× `trim_whitespace` speedup did not reproduce (the effect belongs to the read path); the first fragmentation figures were confounded (the partitioned writer dropped the partition column); "16 shards, 5.6×; 64 worse" did not reproduce (speedup rises monotonically).

### 5.14 Orchestration: the Airflow DAG (`dags/ecom_pipeline.py`, `src/ecom/orchestration/`)

- **Plan as data:** `orchestration/plan.py` lists the nine tasks (IDs fixed by the coding standards), their shell commands and dependencies; the DAG file only converts them to `BashOperator`s. Tests check the plan without Airflow installed (IDs equal the tracker set, acyclic, every command is a real CLI subcommand, `dashboard_ready` waits for everything).
- **Airflow only schedules, never transforms:** every task runs the pipeline's own interpreter (`.venv/bin/python -m ecom.cli …` or `.venv/bin/dbt …`). Airflow lives in a separate environment (`.airflow/venv`, Python 3.11) because its pinned dependencies and dbt's conflict.

| Task | Command | Upstream |
|---|---|---|
| `extract_olist` | `ecom extract` — check sources against contracts, write nothing | — |
| `store_raw` | `ecom ingest` | extract_olist |
| `spark_clean` | `ecom clean` (pandas; ID kept from the tracker) | store_raw |
| `dbt_build` | `dbt deps && dbt run` | spark_clean |
| `build_cooccurrence` | `ecom analyse` | spark_clean |
| `validate_models` | `dbt test` then `ecom reconcile-warehouse` | dbt_build, build_cooccurrence |
| `build_graph` | `ecom visualize-graph` | build_cooccurrence |
| `refresh_inventory_metrics` | `ecom inventory` | spark_clean |
| `dashboard_ready` | `ecom ready` — load data exactly as the API does and check it against the run's manifests | validate_models, build_graph, refresh_inventory_metrics |

- Settings: `schedule="@daily"`, `catchup=False` (a missed day needs one run, not one per day, since each run rebuilds everything), `max_active_runs=1` (runs share one processed layer and one DuckDB file), `retries=1` with a 2-minute delay (a failed quality gate fails identically on retry), `execution_timeout=20 min`.
- Verified: `airflow dags test` (all 9 tasks green, ~40 s); a scheduler-triggered run (~30 s, the three middle branches in parallel); **crash recovery** — a run whose scheduler died mid-flight was recovered on restart (orphaned tasks failed, retried once, run green); a missing source makes `extract_olist` fail and holds back everything downstream.
- Commands: `make airflow-install`, `make airflow-test`, `make airflow-up` (UI on :8080; the DAG starts paused).

### 5.15 The Spark path (Person A)

`src/ecom/spark/` (548 lines): `clean_pipeline.py` (`python -m ecom.spark.clean_pipeline <run-date>`), `cleaning_utils.py`, `validators.py` (quarantine instead of drop: invalid rows go to `storage/quarantine/...` with per-check flags), `quality_report.py`, `schema_contracts.py`, `zones.py`. PySpark is an optional dependency (`pip install -e '.[spark]'`, Java 17+); it is not installed in the main environment, so its 2 test modules are skipped. The pandas path is the one every downstream stage is verified against. See §6.1.

### 5.16 Command-line interface (`src/ecom/cli.py`)

`ecom <command>`: `ingest`, `clean`, `inventory`, `validate-inventory`, `analyse`, `pipeline` (ingest + clean + inventory + analyse), `bench` (`--report-only`), `visualize-graph`, `storage`, `extract`, `reconcile-warehouse` (`--target`), `ready`, `serve` (`--host`, `--port`). The CLI is the only module allowed `argparse` and `print`; every subcommand is a thin wrapper over a library function.

### 5.17 Testing

161 tests pass (2 skipped: PySpark absent). By file: API 22, bench 27, graph/discovery 17, orchestration 15, synthetic inventory 25, transforms 12, quality 7, storage 7, profile 5, source reader 6, raw writer 4, plus Spark modules (skipped). Style: `ruff` (pycodestyle, pyflakes, isort, naming, bugbear, pathlib, pandas-vet, …) and `black` (line length 100). `make check` = lint + tests. dbt adds 36 data tests; reconciliation adds 5 cross-system checks; the DAG adds `ready`'s 4 consistency checks.

## 6. Design decisions and rejected alternatives

Each entry: **the decision**, **why**, **what was rejected and why**, and **the evidence**. When asked "why not X?", the strongest answer always names the measurement.

### 6.1 Technology choices

| Decision | Why | Rejected alternatives and why |
|---|---|---|
| **Batch, not streaming** | Olist is a historical export (2016–2018); nothing arrives continuously. Both use cases are daily decisions (what to recommend, what to restock). | **Kafka / Flink / Spark Streaming:** no stream to consume; consumer lag (the example metric in the feedback) has no meaning for a batch job. Latency, throughput and peak memory are measured instead. Extension path: a micro-batch ingest of new orders into the same raw zone. |
| **pandas as the main engine, PySpark as an optional second path** | ~350k rows / 37 MB processed fit in memory many times over; the whole pipeline runs in ~5 s. Spark's JVM and session start-up alone take seconds. Transforms are pure DataFrame functions, so a Spark port changes only I/O. | **Spark-only:** costs more than it saves below a volume that does not fit one machine (scale up, not out, at this volume). **Hadoop MapReduce:** disk-based between map and reduce, far slower for an iterative small job. The Spark path exists (Person A) and is the documented scale-out route. |
| **Parquet for processed data** | Columnar, typed, compressed. Enables projection pushdown (measured 5.34× reading 2 of 12 columns) and makes vertical fragmentation unnecessary. | **CSV:** loses dtypes; re-inferring types is how silent bugs start. **JSON/XML:** row-oriented, verbose, no column pruning. |
| **Raw CSV kept byte-identical** | Raw is *evidence*: hashes prove what was landed; the pipeline can always be replayed from raw. | Cleaning on ingest (would destroy the evidence and make re-processing impossible). |
| **Local filesystem default, MinIO optional** | Spec documents disagreed; an adapter satisfies both. Local is zero-setup; MinIO demonstrates an S3-compatible object store with the same key layout. | **HDFS:** a cluster file system for a 126 MB dataset. **AWS S3:** account and cost; MinIO is API-compatible and local. |
| **dbt Core for the warehouse** | SQL models with declared grains, tests, documentation and lineage; one project runs on two engines. | Hand-written SQL scripts (no tests, no dependency graph), stored procedures (vendor-locked). |
| **DuckDB locally, BigQuery in the cloud** | DuckDB is an in-process columnar OLAP engine: every model and test runs with no account. BigQuery proves the cloud dialect, partitioning and clustering. | **PostgreSQL:** a row-store OLTP database and a server to run; wrong shape for analytics here. **Snowflake/Redshift:** paid. |
| **Star schema (Kimball), not a normalised (Inmon) EDW** | Analytical queries (revenue by month and category, pairs by product) want few joins; the four-step Kimball process (process → grain → dimensions → facts) was followed. | **Snowflake schema:** more joins for little saving at this size. **3NF warehouse:** right for an enterprise integration layer, wrong for a single-subject mart. |
| **NetworkX in memory for the graph** | 4,881 nodes / 4,054 edges fit trivially in memory; lookups are dictionary (hash) accesses; deterministic and testable. | **Neo4j (graph DB):** a server, a query language and persistence for a graph that is rebuilt from scratch each run and fits in a few MB. Would make sense if the graph were large, persistent and updated incrementally. |
| **No NoSQL document store** | The data is tabular and relational with clean keys; the use cases join and aggregate. | **MongoDB:** schema-less documents lose the referential integrity our gates check, and aggregations across documents are awkward; CAP trade-offs are irrelevant on one node. The storage interface itself is key–value (MinIO is an object/KV store). |
| **No ML recommender** | Explainability and determinism; only 206 pairs have weight ≥ 2, too sparse to train on. | Collaborative filtering / embeddings: would hallucinate structure from one-order coincidences and could not be explained. |
| **FastAPI** | Typed request/response models (Pydantic), automatic validation and OpenAPI docs, fast to test with an in-process client. | **Flask:** no built-in typing/validation. **Streamlit:** a dashboard tool, not an API other clients can use. |
| **Dashboard served by the API (HTML + D3), not Metabase** | One process, no JVM, no second server; the dashboard can only show what the API serves, so there is one source of truth. | **Metabase:** heavy (JVM), connects to the database directly (bypassing the API's rules), poor DuckDB support. **React app:** a Node toolchain for one page. |
| **Airflow** | The tracker's fixed task IDs; DAG of dependencies, retries, scheduling, a UI, backfill control. | **cron:** no dependencies, retries or visibility. **Dagster/Prefect:** fine tools, but Airflow is the industry default and named in the design. |
| **Airflow in a separate venv, tasks as shell commands** | Airflow pins its own versions of SQLAlchemy, pydantic, etc.; dbt also pins; keeping them apart keeps each supported. Enforces "Airflow schedules, never transforms." | PythonOperator importing `ecom` (would force one environment for Airflow, dbt and the pipeline). |

### 6.2 Data and modelling decisions

| Decision | Why | Evidence / rejected alternative |
|---|---|---|
| **One evidence rule: exclude only `canceled` and `unavailable` orders from co-occurrence and velocity** | A basket is a customer's choice the moment it is placed; delivery is logistics. | Measured on the 36 pairs where rules disagreed: 32 came from in-flight orders (21 shipped, 8 invoiced, 5 processing), only 4 from failed ones. "All statuses": 4,058 pairs (keeps 4 failed). "Delivered only": 4,022 (drops 32 real ones). **Adopted rule: 4,054.** Before this fix three parts of the project used three different rules and the warehouse disagreed with the analysis by 36 pairs. |
| **Revenue keeps the stricter delivered-only filter** | An in-flight order is not money yet. Different question, different filter, both documented. | 95,461 delivered orders in the window, R$ 13,069,228.77. |
| **Analysis window 2017-02-01 to 2018-08-31** | Nov 2016 has 0 orders and Dec 2016 has 1 (would inflate the denominator of every rate); 19 of the last 20 orders are cancelled. | Named constants `WINDOW_START`/`WINDOW_END`, mirrored as dbt vars. |
| **Aggregate unit rows into quantity, never deduplicate** | `order_items` is one row per unit. Deduplicating would delete revenue. | Revenue invariant gate: sum before = sum after = R$ 13,591,643.70. |
| **Canonical pair order (a < b)** | Stores each unordered pair once; removes self-pairs. | dbt test `assert_no_self_or_reverse_pairs`. |
| **Raw edge weight = distinct orders; no Jaccard/lift ranking** | Graph parameter study: ranking by raw count vs Jaccard/cosine/lift/NPMI shared 0 of the top 50 edges; normalisation alone was *worse* (a product sold once with another sold once scores Jaccard 1.0). Ties were common (95.9% of products with ≥2 neighbours); ordering by (order_count, lift, product_id) cuts ambiguity to 2%. | The service ranks by weight then product_id for full determinism. |
| **`MIN_COOCCURRENCE_COUNT = 2` for the global "strongest pairs" view** | 94.9% of pairs have weight 1, which is coincidence-level evidence. | Per-product views still show weight-1 neighbours, labelled with their order counts. |
| **Two-tier recommendation (product, then category)** | Product tier reaches only 14.8% of the catalogue. | Category fallback endpoint `/categories/{c}/related`. |
| **Synthetic stock derived from real velocity** | Random stock → 0.0% Urgent (the rule says nothing). Velocity-derived → a meaningful minority. | §5.6; 30-seed stability; sensitivity sweeps. |
| **One lead time per seller** | A supplier relationship property; drawing per row would give one seller twenty lead times. | Test `test_one_lead_time_per_seller`. |
| **Insufficient-evidence rows labelled, not dropped** | A status from one or two sales would look like a finding while being noise; dropping would hide 73.5% of seller-products. | `EVIDENCE_MIN_UNITS = 3`. |
| **Fractional reorder point + one-unit stock floor** | Integer rounding made status a coin flip for slow sellers (§5.6). | Before/after table in the validation report. |
| **Deterministic display names** | Olist has no product names; a seeded name from the ID gives readable, stable labels without inventing data. | Names say "· #XXXX" so the real ID prefix stays visible. |
| **Warehouse fact at item grain (order_id, order_item_id)** | Finest grain the source provides; an aggregated table cannot recover the item key. | `unique_order_item_key` test. |
| **SCD Type 1 dimensions (overwrite)** | Olist is a static historical snapshot; there are no attribute changes to track. | Type 2 (history rows) would be the choice if sellers moved city over time. |
| **Integer-range partition on `order_month_key`** | Monthly pruning without the sandbox's 60-day expiry on time partitions. | DATE partition → 0 rows; integer range → 112,650 rows, 79% fewer bytes for 2 of 24 months. |
| **Cluster (not partition) `fct_order_items` by product_id, seller_id** | A seller predicate cannot be pruned by a month partition; clustering sorts within partitions so block metadata can skip. | Sharding study: the seller access pattern is worth 18.7× when the layout matches it. |
| **Keep the processed layer monolithic per table** | Analytical queries scan most of the table; below the ~53% crossover there is little to prune, above it partitioning is slower. | Selectivity sweep. |
| **Do not vertically fragment** | Parquet already prunes columns; spanning the split costs 40×. | Fragmentation matrix. |
| **Hash-shard on seller_id, not fragment by seller state** | SP holds 68.8% of inventory rows → a geographic fragment would be hugely unbalanced. Hashing is even by construction. | Seller state distribution (§3.3). |
| **64 shards** | Smallest count on the speedup plateau within a 10% storage budget; the argmax would always pick the most expensive layout. | Shard sweep (§5.13). |
| **Materialise every stage to Parquet** | Restartability, inspectable gates, provenance. Costs ~625% on a cheap sequence; amortises as stages grow. | Materialisation study. |
| **Fast reader shipped behind a flag, default off** | Verified identical output; published numbers stay on the long-standing path. | Inventory SHA-256 reproduces through both paths. |

### 6.3 Operational decisions

| Decision | Why |
|---|---|
| Quality gates run *before* writing | A failed run leaves the previous good layer in place. |
| SHA-256 manifests for raw and synthetic tables | Idempotency and auditability: a hash proves an unchanged rebuild. |
| `blake2b` for shard assignment | Python's built-in `hash()` is salted per process; a layout written by one process would be unreadable by the next. |
| API loads data once, at start-up | Requests are pure in-memory lookups; the API sees a consistent snapshot even while a pipeline run rewrites files. The cost: it must be restarted to see new data. |
| API binds to 127.0.0.1 by default | No authentication; exposing it is an explicit choice (`ECOM_API_HOST=0.0.0.0`). |
| Read-only API | No write endpoints means no concurrency control, no injection surface for data changes. |
| `max_active_runs=1`, single writer | Two runs would race on the same files (a lost-update anomaly); one writer avoids it without locking. |
| Reconcile two independent implementations | SQL vs pandas agreeing pair-for-pair is evidence both are right; one implementation checked against itself proves nothing. |
| Test empty-table blind spots with invariants | The BigQuery 0-row bug passed every not_null/relationship test; only an invariant (revenue preserved) caught it. |

## 7. Requirements traceability and honest gaps

Lab 1 (16 Aug) listed these requirements.

| Requirement (Lab 1) | Status | Evidence / honest answer |
|---|---|---|
| FR_1: ingest e-commerce data from different sources (CSV, JSON, XML, etc.) | **Partly met** | Ingestion is contract-driven and byte-level, but the chosen dataset is CSV only; no JSON/XML source was ingested. JSON is produced (manifests, reports, API). Answer: the dataset dictated the format; adding a JSON/XML reader is a new contract plus a parser, the zones and gates do not change. |
| FR_2: maintain raw and cleaned datasets separately | **Met** | Raw zone (byte-identical, hashed) and processed zone (Parquet) are separate; source is read-only. |
| FR_3: store processed data using relational, NoSQL and distributed storage models | **Partly met** | Relational: DuckDB and BigQuery (BigQuery is distributed storage). Object/key–value: MinIO backend. Graph: in-memory NetworkX. No NoSQL *database* (document/wide-column) — rejected for relational, keyed data (§6.1). |
| FR_4: efficient retrieval using indexing and optimised SQL/NoSQL queries | **Met in the analytical sense** | Partitioning, clustering, projection pushdown, partition pruning, measured (§5.13, §5.9). No hand-built B+-tree (not used by columnar engines). |
| FR_5: process large datasets | **Met with caveat** | ~350k rows; the scaling study runs to 8× (~800k membership rows) and the fragmentation study to 4× (396,520 fact rows). Not big data, and the project says so. |
| FR_6: generate analytical results and reports | **Met** | profile.json + 8 figures, optimisation report + 5 figures, inventory validation report, warehouse marts, API and dashboard. |
| NFR: reproducibility | **Met** | Seeded generation, SHA-256 manifests, identical rebuilds, fresh-clone run verified (3 Nov). |
| NFR: data quality | **Met** | Gates, invariants, 36 dbt tests, reconciliation on two engines. |
| NFR: performance | **Met** | Baseline, bottlenecks, 18 strategies, one landed optimisation, measured trade-offs. |
| Spec item: Spark processing (named in an NFR on lineage) | **Partly met** | Spark path implemented but not the default and not benchmarked here. |
| Spec item: Metabase/React dashboard | **Changed** | FastAPI-served HTML/D3 dashboard instead (§6.1). |

The team's original design documents also disagreed with each other (two said "MinIO excluded", two mandated it). The code resolves this with the dual storage backend; the documents themselves were not revised.

---

## 8. How to run everything

### 8.1 Requirements

Python 3.10+ and `make`; internet on the first run (pip, `dbt deps`, D3 from cdnjs). Optional: Python 3.11 for Airflow, Java 17+ for Spark, Docker for MinIO, a Google account and `gcloud` for BigQuery. The Olist CSVs are committed, nothing else to download.

### 8.2 From a fresh clone (verified on a clean copy on 3 Nov)

```bash
make install            # .venv with pipeline, API, dbt (DuckDB) and study tools  (~30 s)
cp .env.example .env
make up                 # rebuild everything from the CSVs, check every hand-off, serve
# open http://127.0.0.1:8000   (API docs at /docs)
```

### 8.3 All make targets

| Target | What it does |
|---|---|
| `make install` | Create `.venv`, install `.[dev,api,warehouse,bench]` |
| `make check` | ruff + black + pytest (161 tests) |
| `make fmt` / `make lint` / `make test` | Format / lint only / tests only |
| `make pipeline` | ingest → clean → inventory → analyse (+ figures) |
| `make ingest`, `make clean`, `make inventory`, `make analyse` | One stage each |
| `make validate-inventory` | Inventory validation suite + figures |
| `make bench` / `make bench-report` | Run the optimisation study / re-render its report |
| `make warehouse` | dbt deps + build on DuckDB (50/50) |
| `make warehouse-reconcile` | Independent CSV-based check of warehouse invariants |
| `make e2e` | pipeline → warehouse → reconcile → API tests (~30 s) |
| `make serve` / `make up` | Serve API + dashboard / e2e then serve |
| `make airflow-install` / `airflow-test` / `airflow-up` | Airflow 3.3.2 in `.airflow/` / run the DAG once / scheduler + UI on :8080 |
| `make bigquery-load` / `make warehouse-bq` | Load to BigQuery / load + dbt build on BigQuery + reconcile |
| `make minio-up` / `minio-down` | Start/stop MinIO (then `ECOM_STORAGE_BACKEND=minio`) |
| `make loc` | Report functions over 50 lines |

### 8.4 BigQuery one-time setup

1. Create a project in the Google Cloud console (sandbox; do not start the paid trial or add billing). Our project: `de-group-9`.
2. Install the gcloud CLI (`sudo snap install google-cloud-cli --classic`).
3. `gcloud auth application-default login` — on the consent page tick **Select all** (the Google Cloud data scope is required).
4. `gcloud auth application-default set-quota-project de-group-9`.
5. Set `ECOM_GCP_PROJECT=de-group-9` in `.env`; `pip install -e '.[bigquery]'`; `make warehouse-bq`.

### 8.5 Airflow

`make airflow-install` (once), `make airflow-up`, open http://localhost:8080 (login printed in the terminal), unpause `ecom_pipeline`, trigger a run. `Ctrl+C` stops all Airflow components. `make airflow-test` runs the DAG once without a scheduler.

---

## 9. Debugging guide

Every entry below is a failure that actually happened during the project (or a direct variant), with its cause and fix.

| Symptom | Cause | Fix |
|---|---|---|
| `make check` fails on a fresh clone: `ModuleNotFoundError: duckdb` | `make install` used to install only `[dev,api]` | Fixed: install now includes `warehouse,bench`. Re-run `make install`. |
| `make e2e`: `.venv/bin/dbt: not found` | Same as above | Same fix. |
| `make check` fails with "would reformat" | black formatting differs | `make fmt`, then re-run. |
| API start-up error: `processed/<table>.parquet is missing; run 'make pipeline'` | Processed layer not built (fresh clone) | `make pipeline` or `make up`. |
| `address already in use` on :8000 | Another server running | `ss -ltnp \| grep 8000`; stop it, or `ecom serve --port 8001`. |
| Dashboard charts empty, tables fine | D3 could not load from cdnjs (offline) | Connect to the internet; the page says so. |
| Dashboard shows old behaviour after a code change | Browser cached old JS | Now sent with `Cache-Control: no-cache`; a normal reload suffices (older sessions: Ctrl+Shift+R). |
| Dashboard shows old numbers after a pipeline run | API loads data once at start-up | Restart `make serve`. |
| Product explorer: "No co-purchases to draw" | Expected for ~85% of products (3.29% multi-product orders) | Search now ranks connected products first; the category fallback appears automatically. |
| Search for `(` returned 500 | Query was used as a regex | Fixed: literal matching (`regex=False`). |
| Restock list topped by stock 0 / 0.0 days rows | Integer rounding in the old generator | Fixed 2 Nov (§5.6); regenerate with `make inventory`. |
| Inventory SHA-256 differs from a document | Generator or input changed (expected after the 2 Nov fix: `f0881d74…` → `8afabc71…`) | Compare `_synthetic_inventory_manifest.json` parameters; same inputs + seed must reproduce the same hash. |
| Pipeline stops with `DataQualityError` | A gate failed | Read `data/processed/_quality_report.json`; the failing check's name and offending row count identify the problem; the previous processed layer is untouched. |
| `reconcile-warehouse` fails | Warehouse is stale relative to the processed layer (pipeline re-run without rebuilding dbt), or a model regression | `make warehouse`, then reconcile again; if it still fails, the failing check names the table. |
| DuckDB "Could not set lock on file" | Another process has the warehouse file open | Close the other session (notebook, DB browser); DuckDB allows one writer. |
| `airflow standalone`: `FileNotFoundError: 'airflow'` | Airflow spawns its components by name from `PATH`; the venv was not on it | `make airflow-up` puts `.airflow/venv/bin` on `PATH`. |
| Airflow processes keep running after the parent is killed | Scheduler, triggerer, API server and 32 LocalExecutor workers are separate processes | Stop with Ctrl+C in the terminal; otherwise kill the scheduler and its children. |
| DAG never runs | New DAGs start paused | Unpause in the UI (or `airflow dags unpause ecom_pipeline`). |
| A DAG run stuck "running" after a crash | Scheduler died mid-run | Restart Airflow; orphaned tasks are failed and retried (verified). |
| First scheduled task unusually slow (e.g. 102 s for a 2 s task) | All Airflow components starting at once | Transient; next run normal. |
| Airflow install: constraints file not found | Python minor version without a constraints file | `AIRFLOW_PYTHON=python3.11 make airflow-install`. |
| gcloud login: "cloud-platform scope is required but not consented" | The Google Cloud checkbox was not ticked on the consent page (browser still shows "success") | Re-run login, tick **Select all**, check the terminal prints "Credentials saved to file". |
| `set-quota-project`: "Application default credentials have not been set up" | Login did not save credentials | Fix the login first. |
| BigQuery `fct_order_items` has 0 rows, tests pass | Sandbox 60-day expiry on DATE partitions | Fixed with integer-range partitioning on `order_month_key`. |
| Google libraries print a Python 3.10 FutureWarning | Google is dropping 3.10 | Harmless now; plan a move to Python 3.11. |
| Process killed with exit 137 | Out of memory (machine at ~3 GB free) | Close other applications; rerun. |
| MinIO connection refused | MinIO not started | `make minio-up` (Docker), then `ECOM_STORAGE_BACKEND=minio`. |
| Spark tests "skipped" | PySpark not installed | `pip install -e '.[spark]'` (needs Java 17+). |

General method: (1) read the exact error and which stage/task raised it; (2) every stage writes evidence (manifests, quality report, dbt `target/run_results.json`, Airflow task logs under `.airflow/home/logs/`); (3) rerun one stage with its own `make` target; (4) check row counts against §10.

---

## 10. Results and numbers cheat sheet

| Area | Result |
|---|---|
| Data audit | 3.29% multi-product orders; 4,054 pairs (94.9% weight 1); graph covers 14.8% of products; median velocity 0.0080 units/day over active days |
| Cleaning | 7 processed tables, all gates green, revenue preserved (R$ 13,591,643.70) |
| Sales (delivered, in window) | 95,461 orders, R$ 13,069,228.77, AOV R$ 136.91, 108,967 units |
| Inventory | 33,787 rows; 206 Urgent / 382 Monitor / 8,363 Healthy / 24,836 Insufficient; Urgent 5.7× faster sellers; 30-seed Urgent 0.579% ± 0.040 |
| Warehouse | 14 models + 36 tests = 50/50 on DuckDB and BigQuery; 5/5 reconciliation checks on both |
| BigQuery | 79% fewer bytes scanned for 2 of 24 months (integer-range partition pruning) |
| Optimisation | baseline 5.17 s; Arrow reader 11.9× component, 1.27× stage; projection 5.34×; pruning up to 5.29×, crossover ≈53%; 64 shards 18.7× at +5% storage; materialisation +625%; DuckDB k = 0.74 |
| Orchestration | 9-task DAG green under scheduler (~30 s); crash recovery verified |
| End to end | `make e2e` ~30 s; fresh clone verified |
| Tests | 161 passing (2 Spark skipped); ruff + black clean |

Figures available: `reports/figures/*.png` (analysis and inventory), `reports/benchmarks/figures/f1–f5` (crossover curve, volume scaling, layout matrix, shard sweep, strategy speedups). Best single chart for the presentation: **f1, the selectivity crossover curve**.

---

## 11. Limitations and future work

**Limitations (know these before someone else points them out):**

1. **Not big data**; claims are about patterns and measured trade-offs, not scale.
2. **Stock is synthetic.** Restock flags show the logic works; they say nothing about real warehouses. Stock-outs are not modelled (stock ≥ 1 by construction). Lead times are uniform, not calibrated. No seasonality: the rate is a flat average.
3. **73.5% of seller-products have insufficient evidence** (fewer than 3 units sold).
4. **Product-level recommendations cover 14.8% of products**; the category fallback covers the rest with weaker evidence.
5. **Spark path not the default and not benchmarked**; PySpark not installed in the main environment.
6. **Processed-layer writes are not atomic across tables**: a crash mid-write could leave a mix of old and new tables.
7. **API needs a restart to see new data**; no authentication (loopback only by default).
8. **BigQuery is not in the daily DAG** (local DuckDB is; BigQuery runs with `make warehouse-bq`); sandbox tables expire after 60 days.
9. **The co-occurrence pipeline still uses the original nested loop**; the faster sparse-matrix and DuckDB strategies are measured but not landed.
10. **Cold-cache behaviour unmeasured** (dropping the page cache needs root); timings are warm-cache relative costs.
11. **No JSON/XML ingestion and no NoSQL database** (FR_1, FR_3 partly met).
12. **Python 3.10** is losing support in Google's libraries.

**Future work (in priority order):** atomic processed-layer publication (versioned directory + pointer switch, or a lakehouse table format such as Delta Lake/Iceberg, which adds snapshots and time travel); run and benchmark the Spark path and report its break-even volume; land the sparse-matrix or DuckDB co-occurrence join with a size-based switch (an adaptive rule: choose the strategy by input size); API hot reload when the inventory manifest changes; add BigQuery as an optional DAG branch; seasonal demand model; SCD Type 2 sellers if data were live; streaming micro-batch ingest; Python 3.11.

---

## 12. References, citations and AI-use note

Cite in **IEEE** format with in-text numbers [n],; link to papers or documentation, not company home pages.

[1] Olist, "Brazilian E-Commerce Public Dataset by Olist," Kaggle, 2018. License CC BY-NC-SA 4.0.
[2] M. Kleppmann, *Designing Data-Intensive Applications*. Sebastopol, CA, USA: O'Reilly Media, 2017.
[3] A. Silberschatz, H. F. Korth, and S. Sudarshan, *Database System Concepts*, 6th ed. New York, NY, USA: McGraw-Hill, 2011.
[4] H. Garcia-Molina, J. D. Ullman, and J. Widom, *Database Systems: The Complete Book*, 2nd ed. Pearson, 2014.
[5] M. T. Özsu and P. Valduriez, *Principles of Distributed Database Systems*, 4th ed. Cham, Switzerland: Springer, 2020.
[6] R. Kimball and M. Ross, *The Data Warehouse Toolkit*, 3rd ed. Indianapolis, IN, USA: Wiley, 2013.
[7] W. H. Inmon, *Building the Data Warehouse*, 4th ed. Wiley, 2005.
[8] S. Chaudhuri and U. Dayal, "An overview of data warehousing and OLAP technology," *ACM SIGMOD Record*, vol. 26, no. 1, pp. 65–74, 1997.
[9] J. Dean and S. Ghemawat, "MapReduce: Simplified data processing on large clusters," in *Proc. OSDI*, 2004.
[10] M. Zaharia *et al.*, "Apache Spark: A unified engine for big data processing," *Commun. ACM*, vol. 59, no. 11, pp. 56–65, 2016.
[11] S. Melnik *et al.*, "Dremel: Interactive analysis of web-scale datasets," *Proc. VLDB Endow.*, vol. 3, no. 1, pp. 330–339, 2010.
[12] M. Raasveldt and H. Mühleisen, "DuckDB: An embeddable analytical database," in *Proc. ACM SIGMOD*, 2019, pp. 1981–1984.
[13] G. M. Amdahl, "Validity of the single processor approach to achieving large scale computing capabilities," in *Proc. AFIPS Spring Joint Computer Conf.*, 1967, pp. 483–485.
[14] A. A. Hagberg, D. A. Schult, and P. J. Swart, "Exploring network structure, dynamics, and function using NetworkX," in *Proc. 7th Python in Science Conf. (SciPy)*, 2008, pp. 11–15.
[15] Apache Software Foundation, "Apache Parquet documentation," and "Apache Arrow documentation."
[16] dbt Labs, "dbt Core documentation"; Apache Software Foundation, "Apache Airflow 3 documentation"; Google Cloud, "BigQuery documentation: partitioned tables, clustered tables, sandbox limits."
[17] S. Gilbert and N. Lynch, "Brewer's conjecture and the feasibility of consistent, available, partition-tolerant web services," *ACM SIGACT News*, vol. 33, no. 2, pp. 51–59, 2002.
[18] I. Jacobson *et al.*, *The Essentials of Modern Software Engineering*. ACM Books, 2019.
[19] B. H. Bloom, "Space/time trade-offs in hash coding with allowable errors," *Commun. ACM*, vol. 13, no. 7, pp. 422–426, 1970.
[20] P. Flajolet, É. Fusy, O. Gandouet, and F. Meunier, "HyperLogLog: The analysis of a near-optimal cardinality estimation algorithm," in *Proc. AofA*, 2007.
[21] G. Cormode and S. Muthukrishnan, "An improved data stream summary: The count-min sketch and its applications," *J. Algorithms*, vol. 55, no. 1, pp. 58–75, 2005.
[22] M. Armbrust *et al.*, "Delta Lake: High-performance ACID table storage over cloud object stores," *Proc. VLDB Endow.*, vol. 13, no. 12, pp. 3411–3424, 2020.
[23] M. Budiu *et al.*, "DBSP: Automatic incremental view maintenance for rich query languages," *Proc. VLDB Endow.*, vol. 16, no. 7, 2023.

**AI-use note.** Parts of this project's code, analysis and documentation (including this handbook) were produced with assistance from an AI coding assistant (Anthropic's Claude). Every number in this handbook was produced by running the project's own code, and every output was verified.

---

## 13. Glossary

| Term | Meaning in this project |
|---|---|
| Co-occurrence / pair weight | Number of distinct countable orders containing both products |
| Countable order | Any order whose status is not `canceled` or `unavailable` |
| Ego network | A product and its direct neighbours in the graph |
| Degree | Number of distinct products ever bought with a product |
| Velocity / daily_sales_rate | Real units sold ÷ active days |
| Days of inventory | Synthetic stock ÷ daily sales rate |
| Reorder point | Demand over (lead time + 3 safety days), fractional units |
| Evidence | `sufficient` if ≥ 3 units sold, else `insufficient` |
| Raw / processed zone | Byte-identical landed source / typed, cleaned Parquet |
| Manifest | JSON record of what a stage produced, with SHA-256 hashes |
| Quality gate | A batch of checks that raises before anything is written |
| Revenue invariant | Item price total must be identical across stages |
| Grain | What one row of a table represents |
| Star schema | Fact table with surrounding dimension tables |
| Partition pruning | Skipping partitions whose key range cannot match a filter |
| Projection pushdown | Reading only the needed columns from a columnar file |
| Selectivity | Fraction of rows a query matches |
| Crossover | Selectivity above which partitioning stops paying (~53%) |
| Sharding | Hash-based horizontal fragmentation into n files |
| Materialisation | Writing each stage's output to storage before the next stage |
| Amdahl's law | Whole-job speedup is limited by the fraction of time the optimised part takes |
| Fitted exponent k | Slope of log(time) vs log(rows); k < 1 is sub-linear |
| Reconciliation | Proving two independent implementations produce identical results |
| Idempotent | Re-running with the same input produces the same output (same hashes) |
| Sandbox | BigQuery's no-billing tier (10 GB, 1 TB/month, 60-day expiry) |
| DAG | Directed acyclic graph of tasks in Airflow |

---

## 14. File-by-file map of the repository

```
Makefile                      every command (see §8.3)
pyproject.toml                package, extras ([dev] [api] [warehouse] [bench] [bigquery] [spark] [minio]), ruff/black/pytest config
.env.example                  all settings with defaults (copy to .env)
docker-compose.yml            MinIO service
Readme.md                     quick start
data/*.csv                    the nine Olist CSVs (read-only); data/raw, data/processed are generated and git-ignored
dags/ecom_pipeline.py         Airflow DAG built from orchestration/plan.py
docs/
  PROJECT_HANDBOOK.md         this file
  PROJECT_STATUS.md           running status note and measured findings
  CODING_STANDARDS.md         the engineering rules (§4.3)
  contracts.md                inter-team data contracts 1–5
  OPTIMISATION_CONCEPTS.md    course concept → file that measures it
src/ecom/
  config.py                   Settings + named constants (§5.1)
  contracts.py                table contracts for the six used tables
  source_registry.py          contracts for all nine CSVs (Spark path)
  logging_setup.py            single logging configuration
  cli.py                      `ecom` command (§5.16)
  storage/                    base.py (StorageBackend), local.py, minio_backend.py, __init__.py (get_storage)
  ingestion/                  ingest.py (main path); run_ingestion.py, source_reader.py, raw_writer.py (Person A)
  cleaning/                   transforms.py (pure rules), run_clean.py (gates + writes)
  quality/                    checks.py (CheckResult, run_gate), reconcile.py (warehouse vs pipeline)
  analysis/                   profile.py (metrics + co-occurrence), visualize.py (figures)
  synthetic/                  inventory.py (generator), run_generate.py (manifest), validate.py (validation suite)
  discovery/                  graph.py (service), schemas.py, names.py, visualize.py (Person C)
  api/                        app.py (routes), loader.py, inventory.py, schemas.py, static/ (index.html, app.js, styles.css)
  orchestration/              plan.py (task graph), steps.py (extract / reconcile / ready gates)
  bench/                      harness.py, workloads.py, fragmentation.py, studies.py, run_bench.py, report.py
  spark/                      Spark cleaning path (Person A)
dbt_warehouse/
  dbt_project.yml, profiles.yml   project and targets (duckdb, bigquery)
  models/staging|intermediate|marts, models/schema.yml, models/sources.yml
  macros/portability.sql      DuckDB/BigQuery dialect helpers
  tests/*.sql                 five singular tests
  scripts/load_to_bigquery.py BigQuery loader; local_validate.py independent check; export_results.py
tests/                        161 tests (one file per module)
reports/
  profile.json, figures/      analysis outputs (generated)
  benchmarks/                 optimisation_report.md, results.json, figures/f1–f5
  synthetic_inventory_validation.md
  Lab45_9.pdf/.tex            Lab 4–5 submission; sprint_plan.*; slides/
```
