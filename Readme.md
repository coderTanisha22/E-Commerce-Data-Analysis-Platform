# E-Commerce Data Platform

Batch data platform turning the Olist Brazilian e-commerce dataset into a tested
analytical layer for two use cases: **product co-occurrence** (explainable
recommendations) and **inventory risk** (rule-based restocking).

Implemented so far: ingestion, cleaning, storage, quality gates, analysis and
visualisation. The dbt / BigQuery / NetworkX-serving / FastAPI / dashboard stages
come next.

## Quickstart

```bash
make install          # venv + dependencies
cp .env.example .env
make pipeline         # ingest -> clean -> analyse
make check            # ruff + black + pytest
```

Outputs land in `data/raw/`, `data/processed/` and `reports/`.

## Pipeline stages

| Stage | Command | Input | Output |
|---|---|---|---|
| Ingestion | `make ingest` | `data/*.csv` (read-only) | `raw/olist/*.csv` + `raw/_manifest.json` |
| Cleaning | `make clean` | raw layer | `processed/*.parquet` + `_quality_report.json` |
| Analysis | `make analyse` | processed layer | `reports/profile.json` + 5 PNG figures |

## Storage backends

The pipeline addresses storage by logical key, never by path, so the backend is a
config flag. Both are verified to produce an identical key layout.

```bash
# local filesystem (default, no services needed)
make pipeline

# MinIO object storage
make minio-up
ECOM_STORAGE_BACKEND=minio make pipeline
```

This is deliberately how the project resolves the MinIO-vs-local-filesystem
disagreement between the two architecture documents: it is a runtime choice, not
an architectural commitment.

## What the cleaning stage actually does

Each rule encodes a property measured on the real files, not an assumption.

| Rule | Why |
|---|---|
| `derive_order_lines` | Olist has **no quantity column** — each row is one unit. 112,650 unit rows become 102,425 lines, 7,088 with quantity > 1. Revenue is asserted unchanged (R$ 13,591,643.70). |
| `build_order_products` | The `DISTINCT(order_id, product_id)` step, kept separate so the fact table keeps quantities while the graph counts each product once per order. |
| `normalise_category` | 610 products have a NULL category. Since the catalogue has no product name, category is the only searchable attribute, so these get an explicit `unknown` bucket rather than vanishing. |
| `attach_english_category` | **LEFT** join: the translation file covers 71 of 73 categories. An inner join silently drops `pc_gamer` and `portateis_cozinha_e_preparadores_de_alimentos`. |
| `flag_order_status` | 2,963 orders are not delivered. They are flagged `is_delivered`, never deleted, so order counts still reconcile with the source. |

## Quality gates

18 checks run per pipeline execution; error-severity failures raise and abort.
The one standing warning is a documented Olist property, not a regression:

```
WARN foreign_key:orders_without_items: 775 orphan rows on order_id
```

## Key findings baked into the code

The observation window and thresholds in `config.py` exist because profiling
showed the naive defaults break both use cases:

- **3.28%** of orders contain 2+ distinct products — the entire basis of the graph.
- **94.9%** of the 4,058 product pairs were bought together exactly once.
- **14.8%** of the catalogue (4,885 of 32,951 products) can be served a recommendation at all.
- Median velocity is **0.0017 units/day**, so `days_of_inventory` alone cannot drive restocking; stock levels must be generated from observed velocity.
- The window is **2017-02-01 to 2018-08-31**: Nov 2016 has 0 orders, and 19 of the last 20 orders are cancelled.

## Layout

```
src/ecom/
  config.py         settings + named analytical constants
  contracts.py      declared schema, keys and known quirks per table
  storage/          StorageBackend ABC + local and MinIO backends
  ingestion/        source -> raw, with validation and a manifest
  cleaning/         pure transforms + raw -> processed orchestrator
  quality/          checks that gate the pipeline
  analysis/         profiling metrics + figure generation
  cli.py            the only module allowed argparse and print
tests/              24 tests, all transforms covered
docs/CODING_STANDARDS.md
```

## Conventions

See **[docs/CODING_STANDARDS.md](docs/CODING_STANDARDS.md)**. The load-bearing
rule is that a transform takes a DataFrame and returns a DataFrame and never does
I/O — which is what keeps the rules unit-testable on 5-row fixtures and makes a
future PySpark port a change of I/O calls rather than a rewrite.

## Next

1. Generate the synthetic inventory file from observed velocity (`fct_inventory`).
2. dbt Core models: dimensions, facts, `fct_product_cooccurrence`, plus tests.
3. Load to BigQuery.
4. Serve the graph and restock priorities through FastAPI.
5. Retailer dashboard.
