# Project Status — handoff note

**Last updated: 11 October 2026.** Read this first when picking the project up in a
new session. It records what exists, what the measured numbers are, what is
decided, and what is still open.

---

## 1. What the project is

An **E-Commerce Data Platform for Product Co-Occurrence and Inventory Analysis**
— a batch data engineering pipeline over the Brazilian E-Commerce Public Dataset
by Olist, supporting two use cases:

1. **Product co-occurrence** — find products bought together, serve them as
   explainable recommendations from a weighted graph.
2. **Inventory analytics** — combine real sales velocity with synthetic stock to
   flag seller-products needing restock.

Semester 5 Data Engineering course project, Group 9. Graded through lab
assignments. **No AI/ML by deliberate choice** — recommendations are
deterministic and explainable.

**Designed stack:** Airflow (orchestration) · Python (ingestion) · local
filesystem or MinIO (storage) · Spark *or* pandas (processing) · dbt Core
(transformation) · BigQuery (warehouse) · NetworkX (graph) · FastAPI (API) ·
Metabase/React (dashboard) · Docker.

---

## 2. Current state

### Built and working

| Stage | Status | Evidence |
|---|---|---|
| Ingestion | Done | contracts, validation, SHA-256 manifest, idempotent |
| Storage | Done | local + MinIO backends, identical key layout verified |
| Cleaning | Done | pure transforms, 18 quality gates, revenue invariant |
| Synthetic inventory | Done | 33,787 rows, seeded, validated |
| Analysis | Done | profile.json, co-occurrence graph, 8 figures |
| Coding standards | Done | 19/19 tracker rules, enforced by `make check` |

**46 tests passing** · ruff and black clean · 23 source modules · ~3,250 LoC.

### Not started

dbt models · BigQuery load · FastAPI · Metabase dashboard · Airflow DAG ·
**the optimisation workstream (see §7 — this is the current priority).**

---

## 3. Measured findings that drive design decisions

These were measured from the real data. Do not re-derive them; do not contradict
them without re-measuring.

### Co-occurrence is extremely sparse
- Only **3.28%** of orders contain 2+ distinct products (3,236 of 98,666)
- **4,058** product pairs; **94.9%** were bought together exactly once
- Graph reaches **4,885 of 32,951 products = 14.8% of the catalogue**
- 1,652 disconnected components; largest has 398 products; 67.1% of nodes have
  exactly one neighbour
- **Conclusion: Olist cannot support product-level recommendation at catalogue
  scale.** Use a two-tier design — product tier for precision, category tier
  (98.2% coverage) as the fallback.

### Graph parameter study (3 assumptions overturned)
- Ranking by raw count vs by Jaccard/cosine/lift/NPMI share **0 of 50** top edges
- Normalisation alone is *worse* than raw counts — a product sold once, bought
  once with another sold once, scores Jaccard 1.0. Needs a support floor.
- **95.9%** of products with 2+ neighbours had tied weights; ordering by
  `(order_count, lift, product_id)` cuts ambiguity to **2%**
- Confidence is asymmetric: mean **2.84×**, max **24.6×**
- Temporal holdout hit rate **4.6%** — limited by new products, not by ranking

### Inventory velocity is very low
- Median seller-product sells **0.0080 units/day** (~1 unit per 125 days)
- 56% sold exactly one unit in the 577-day window
- **Random stock → 0.0% urgent.** Velocity-derived stock → **10.8% urgent**.
  This is the single most important design result in the project.

### Data quirks that bit us
- `order_items` has **no quantity column** — each row is one unit; 10,225 rows
  repeat a (order_id, product_id) pair and must be aggregated, not deduplicated
- `products` has **no name or description text** — only character counts, so
  keyword search is impossible; category is the only searchable attribute
- Category translation covers **71 of 73** categories → must be a LEFT join
- 610 products have a NULL category; 775 orders have no item rows
- Usable window is **2017-02-01 to 2018-08-31**: Nov 2016 has 0 orders, and 19
  of the last 20 orders are cancelled

---

## 4. Synthetic inventory — the detail

`data/processed/synthetic_inventory.parquet` · **33,787 rows × 14 columns** ·
seed 42 · SHA-256 `f0881d74ef39da3d8cff47272ffcf1cc83577066d3e06347bf1f2d830248cfa2`

**7 columns real** (units_sold, first_sale_date, active_days, daily_sales_rate,
evidence + the two keys) · **3 synthetic** (lead_time_days, current_quantity,
last_restock_date) · **3 derived** (reorder_point, days_of_inventory, status) ·
`is_synthetic = True` on every row.

Status split: Insufficient data 24,836 (73.5%) · Healthy 7,736 (22.9%) ·
Urgent 966 (2.9%) · Monitor 249 (0.7%).

**Known limitation, already written up:** 96.4% of reorder points equal 1 because
of the integer ceiling, and **85.3% of Urgent rows are urgent because stock
rounded to zero**, not because a fast seller is running low. The 142 rows that do
have stock sell **6.1× faster** than Healthy ones, so the logic is right. Fix
would be a non-integer reorder point or a units-per-month rate.

Validation: 30-seed stability (Urgent 2.944% ± 0.095), sensitivity sweeps over
safety days / stock factor / lead time, reproducible SHA-256, real inputs hashed
before and after to prove they were never written to.

---

## 5. How to run it

```bash
make install            # venv + dependencies
cp .env.example .env
make pipeline           # ingest -> clean -> inventory -> analyse
make check              # ruff + black + 46 tests
make inventory          # regenerate synthetic inventory only
make minio-up           # optional: start MinIO, then ECOM_STORAGE_BACKEND=minio
```

### Layout

```
src/ecom/
  config.py        settings + named analytical constants
  contracts.py     declared schema, keys, quirks per table
  storage/         StorageBackend ABC + local and MinIO
  ingestion/       source -> raw, validation + manifest
  cleaning/        pure transforms + raw -> processed orchestrator
  quality/         checks that gate the pipeline
  synthetic/       inventory generator + validation
  analysis/        profiling metrics + figures
  cli.py           the only module allowed argparse and print
tests/             46 tests
docs/CODING_STANDARDS.md
reports/           generated reports, figures, slide charts
```

### Conventions that matter

- **The purity rule:** a transform takes a DataFrame and returns a DataFrame and
  never does I/O. This is what makes rules testable on 5-row fixtures and a
  PySpark port cheap. Do not break it.
- Every threshold is a named constant in `config.py` with a comment saying why.
- Quality checks **raise**; warnings must be explicitly declared.
- No `print()` outside `cli.py`.
- `docs/CODING_STANDARDS.md` implements the project tracker's rules. If the two
  disagree, **the tracker wins**.

---

## 6. Open decisions and known issues

| Issue | Detail |
|---|---|
| **Five spec PDFs disagree** | Two say MinIO is excluded, two mandate it. Resolved in code by the dual backend, but the documents still contradict. Reword `FR-rawpr` to be implementation-neutral. |
| **Spark is specced but not implemented** | Cleaning is pandas, written to be Spark-portable. `NFR-lineage` names Spark. Either reword or install pyspark. |
| **Requirements alpha stuck at Bounded** | Fixing the two items above advances it to Coherent — cheapest state gain available. |
| Lab 2 has no in-text citations | IEEE list drafted; 9 anchor positions mapped. Two references still need author names. |
| Kafka claim in Lab 2 §I | Unsupported by the cited source. Drop it or source it. |
| Canva deck wording | Slide 6 needs: "cancelled **and unavailable**", `ceil(...)` + min 1 on the reorder point, and "(min 30)" on the rate. |

---

## 7. Current priority — the optimisation workstream

**Both instructors gave the same feedback (1 Oct 2026):** this is a Data
Engineering course, so show **pipeline optimisation**, not model selection. They
want performance testing with measurable metrics, a baseline, bottleneck
analysis, and optimised-vs-baseline comparison across multiple strategies. One
specifically named **sharding and vertical/horizontal fragmentation**.

Note: Kafka consumer lag was given as an example but **does not apply** — this
pipeline is batch. Use latency, throughput and peak memory instead.

### Baseline already measured — 5.17 s total, peak 499 MB

| Stage | Time | Share |
|---|---|---|
| Clean | 2.31 s | 44.8% |
| Inventory | 1.36 s | 26.3% |
| Ingest | 0.82 s | 15.8% |
| Analyse | 0.68 s | 13.1% |

### Bottlenecks found, fixes validated

| Bottleneck | Fix | Speedup |
|---|---|---|
| `trim_whitespace` — 2.38M Python `str.strip()` calls | pyarrow-backed string dtype | **16.9×** |
| `_count_rows` parses every row to count it | `pyarrow.csv` | **10.8×** |
| Co-occurrence Python `itertools` loop | vectorised pandas self-join | **1.5×** |

Note: **0 of 7 columns actually have padding**, so `trim_whitespace` is pure
overhead on this dataset — a textbook "measure before you optimise" result.

### Fragmentation study, measured

| Strategy | Result |
|---|---|
| Horizontal partition by month, partition-key query | **3.3× faster**, 91% less data read |
| Same, query not touching the partition key | **0.35× — 2.9× SLOWER** |
| Storage cost of partitioning | **+37%** (7,395 → 10,108 KB, 24 files) |
| Sharding by seller hash, 16 shards | **5.6× faster** single-seller lookup |
| Sharding at 64 shards | *worse* — there is an optimum |
| Vertical fragmentation | **0.90× — rejected on evidence** (Parquet is already columnar) |

### Still to build

1. `ecom bench` — repeatable harness writing JSON (latency, throughput, memory)
2. Optimisations behind a flag so baseline and optimised run from one codebase
3. Scaling test at 1×/2×/4×/8× volume — 5.17 s invites "why bother?", and the
   answer is how the curves diverge
4. Strategy comparison incl. DuckDB for the co-occurrence self-join
5. Report + charts. **Best single chart: the selectivity crossover curve** —
   speedup vs % of table scanned, crossing 1.0.

Carry forward: partition `fct_orders` by order month and cluster by `seller_id`
when it reaches BigQuery.

---

## 8. Deliverables produced so far

| File | What |
|---|---|
| `reports/Lab45_9.pdf` | Lab 4&5 submission, 13 pages, 1,999 words, report + tracker |
| `reports/Lab45_9.tex` | LaTeX source in the Lab 3 format |
| `reports/synthetic_inventory_validation.md` | Full validation write-up |
| `reports/sprint_plan.pdf` / `.csv` | 9 sprints, 43 tasks, paste-ready for the tracker |
| `reports/slides/s1–s7*.png` | Slide charts + `make_slide_charts.py` |
| `reports/figures/*.png` | 8 analysis figures |
| `reports/synthetic_inventory.csv` | CSV export for inspection (Parquet stays source of truth) |

**Artifacts** (published pages, not in the repo):
- Data audit — `claude.ai/code/artifact/e8113c4f-0e53-4f2f-8d70-222f5c5a5a60`
- Assignment 2 feedback response — `claude.ai/code/artifact/8788c14c-184e-41dc-8f03-51b171eaee7e`
- Synthetic inventory slide guide — `claude.ai/artifact/6mAfNKxhALy8WCWgMxTzEi`

**Not in the repo:** the five spec PDFs (Lab 2, Lab 3, two architecture guides,
sprint progress note) and the Canva deck. Re-attach if a question turns on their
detail.
