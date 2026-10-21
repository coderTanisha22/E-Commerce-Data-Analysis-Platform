# Project Status — handoff note

**Last updated: 21 October 2026.** Read this first when picking the project up in a
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
| Optimisation study | Done | 17 strategies, 4 layouts, 4 sweeps, `make bench` |

**97 tests passing** (2 skipped, Spark) · ruff and black clean · 41 source
modules · ~6,700 LoC.

### Written but NOT merged into main

**The dbt warehouse exists on the `origin/warehouse` branch** (`ebe74a9`, one
commit on top of main's tip) and is *not* reachable from `main`. It holds a
complete dbt project: 6 staging models, 1 intermediate, 7 marts, 5 custom SQL
assertions, a BigQuery loader, a DuckDB local validator and its own docs.

It does not merge cleanly as-is — see §6, "The warehouse grain conflict". No
cloud run is claimed by the package itself.

### Not started

FastAPI · Metabase dashboard · Airflow DAG.

The **optimisation workstream is now built and measured** — see §7.

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

### Optimisation findings
See §7. The headline: partition pruning crosses over to a loss at roughly half
the table, no storage layout wins every query, and the one optimisation landed
is provably result-neutral.

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
make check              # ruff + black + 97 tests
make inventory          # regenerate synthetic inventory only
make bench              # optimisation study -> results.json + report + figures
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
  bench/           optimisation study: harness, workloads, layouts, sweeps
  cli.py           the only module allowed argparse and print
tests/             97 tests
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
| **The warehouse grain conflict** | `origin/warehouse` is built against a different contract than `main` produces. Two mismatches, both real. **(1) Grain:** `fct_order_items` declares one row per (`order_id`, `order_item_id`) and its docs say explicitly "do not aggregate item rows into order-product-seller lines" and "does not invent a `quantity` column". That is exactly what `main`'s `derive_order_lines` does — 112,650 unit rows collapsed into 102,425 lines with a derived `quantity`. **(2) Source names:** `sources.yml` expects the 9 raw Olist table names (`olist_orders_dataset`, …) in BigQuery dataset `olist_cleaned`, i.e. the Spark path's output; `main`'s pandas path writes 6 tables named `orders`, `order_lines`, `order_products`, `products`, `customers`, `sellers`. Someone must decide which grain is canonical before these merge. |

---

## 7. The optimisation workstream — built and measured

**Both instructors gave the same feedback (1 Oct 2026):** this is a Data
Engineering course, so show **pipeline optimisation**, not model selection. They
wanted performance testing with measurable metrics, a baseline, bottleneck
analysis, and optimised-vs-baseline comparison across multiple strategies. One
specifically named **sharding and vertical/horizontal fragmentation**.

Note: Kafka consumer lag was given as an example but **does not apply** — this
pipeline is batch. Latency, throughput and peak memory are used instead.

### What exists now

`src/ecom/bench/` — seven modules, ~2,900 lines, plus 41 tests in
`tests/test_bench.py`. Run with `make bench`; writes
`reports/benchmarks/results.json`, `optimisation_report.md` and five figures.
Every number in the report is generated from that JSON, so prose and
measurement cannot drift. `docs/OPTIMISATION_CONCEPTS.md` maps each course
concept to the file that measures it.

The design rule that makes the study worth anything: **every strategy's output
is compared against the baseline's, and a faster strategy that returns a
different answer is reported as rejected, never as a win.** This caught two
real defects (below).

### Strategy comparison — 5 operations, 17 implementations

Co-occurrence self-join written five ways (nested loop / hash join / sort-merge
/ sparse `BᵀB` / SQL on DuckDB) mapping to the lecture's J1–J4; plus CSV row
counting, read-and-trim, timestamp parsing, and Parquet projection. See the
report for the full tables. Two results worth carrying:

- **The best co-occurrence strategy at 1× is the sparse matrix product** (~2×
  over the current nested loop), but **at 8× volume DuckDB overtakes it**.
- **Timestamp parsing has effectively no winner.** Supplying an explicit format
  gained only 1.05–1.17× and the Arrow kernel was *slower* than the baseline.
  Modern pandas already fast-paths ISO-8601, so the folklore fix is not a fix
  here.

### One optimisation landed, proven result-neutral

`ECOM_FAST_READER=1` (`Settings.fast_reader`, default off) parses raw CSVs with
Arrow instead of pandas via `StorageBackend.get_csv_arrow`.

- **11–13×** on the orders-table read-and-trim; **1.3–1.8×** on the whole
  cleaning stage across five runs.
- All six processed tables identical value-by-value.
- **The synthetic inventory SHA-256 `f0881d74…` reproduces exactly** through the
  optimised path. This is the strongest check in the project.

The gap between 12.9× and 1.5× is Amdahl's law measured rather than asserted,
and is why the study times whole stages and not just the functions that looked
slow in a profile.

### Fragmentation — no layout wins everything

At 4× the fact table (396,520 rows). Speedup vs a single monolithic Parquet file:

| Layout | Full scan | 2 of 19 months | One seller |
|---|---|---|---|
| horizontal (by month) | 0.19× | **3.64×** | 0.85× |
| vertical (hot/cold split) | 0.83× | **0.025×** | 0.98× |
| sharded (by seller hash, 16) | 0.22× | 0.44× | **10.3×** |

(Latest run. The winning cells are stable across runs; the sub-1× cells move
by a few tenths and the vertical full-scan cell has ranged 0.83–1.35×.)

Each layout wins the access pattern it was designed for and loses the others.

**Vertical fragmentation is rejected, but for a sharper reason than "it is
slow".** Its full-scan result has measured anywhere from 0.83× to 1.35× across
runs — that is, **no reliable gain at all**, because the saving it offers (read
the hot fragment, skip the cold one) is exactly what Parquet's column pruning
already does for free from the monolithic file. Meanwhile a query that spans
the split pays a rejoin costing **0.025×, a 40-fold penalty**, and that result
is stable. The layout buys nothing the format does not already give and adds a
catastrophic failure mode.

- **Selectivity crossover ≈50%** (49%, 52%, 53%, 53%, 57% across five runs — it
  is a ratio of ~30 ms timings, so treat it as "roughly half the table", not a
  precise figure). Below it, pruning wins up to ~5×; above it the partitioned
  layout is slower, bottoming out near 0.47× on a full scan.
- **Partitioning here *reduces* storage by 20%**, not increases it: within one
  file `order_month` is constant and dictionary-encodes away, and time-clustering
  helps the other columns compress. It is nonetheless slower on a full scan —
  **bytes on disk are not the binding constraint, per-file overhead is.**
- **Sharding: 64 or 256 shards** (18.7× / 21.1×, +5.0% / +9.8% storage). The
  recommendation is the smallest shard count on the speedup plateau that fits a
  declared 10% storage budget — not the argmax, which would always name the most
  expensive layout tested, since the lookup reads one file and that file keeps
  shrinking. Speedup keeps creeping up to 4,096 shards (23.4×) at **+79.7%
  storage**, which is the trade the budget exists to refuse.

  **64 and 256 are not reliably distinguishable on this machine** — the
  recommendation landed on one or the other across five runs. Prefer **64**: the
  speed difference is inside the noise and it costs half the storage. Two
  earlier drafts of this note each asserted one of them on the strength of a
  single run; neither claim survived more runs.

### Materialisation vs pipelining

Writing Parquet between every stage costs **~650%** over keeping intermediates in
memory on a cheap three-stage sequence (625–658% across runs). The cost is real and deliberate: it buys
restartability and lets the quality gates inspect each stage. It is a fixed
overhead that amortises as per-stage computation grows, and looks worst exactly
when the stages are cheap.

### Scaling — why optimise something that takes 5 seconds

Co-occurrence re-run at 1×/2×/4×/8× volume. Fitted exponents in time ∝ rows^k
sit near 1.05–1.32 for the pandas, numpy and scipy strategies and **0.74–0.79
for DuckDB**, which parallelises as work grows. At 1× the strategies are
**~3×** apart and the sparse matrix wins; at 8× they are **5.8–6.6×** apart and
DuckDB wins. **That divergence is the answer to "why bother at this size":** at the
project's real volume the choice barely matters and the winner is a different
strategy than at scale, which is exactly why it had to be measured rather than
reasoned about.

Second honest result: the naive Python nested loop is *not* catastrophically
slow here, because only 3.28% of orders hold 2+ products, so the quadratic term
in basket size almost never fires. An optimisation's value depends on the data's
shape, not only the algorithm's complexity class.

### Which numbers are solid

Re-running `make bench` moves the timings. Treat as **stable**: every
correctness verdict, all bytes-read and storage figures (measured from the
filesystem, not a timer), the sign and rough magnitude of every speedup, the
fitted scaling exponents, and which strategy wins each workload. Treat as
**approximate**: the crossover percentage, the exact shard recommendation
between 64 and 256, and any single speedup to two decimal places. The report
regenerates all of them from `results.json`, so quote it rather than this note
when precision matters.

### Three corrections to this document's own earlier numbers

1. **The 16.9× `trim_whitespace` speedup does not reproduce** as a property of
   the trim. Across all six raw tables the trim touches 2,390,364 string cells
   and costs ~231 ms total; converting columns to Arrow inside the transform is
   roughly break-even. The real effect belongs to the **read path**, which is
   why it was landed in `get_csv_arrow` and not in `trim_whitespace`.
2. **The earlier fragmentation figures were confounded.** The partitioned writer
   dropped the partition column, so that layout read ~20% fewer bytes by
   construction and appeared faster even on a full scan. Controlling the column
   is what produced the crossover above.
3. **The earlier "16 shards, 5.6×; 64 shards worse" note does not reproduce.**
   Speedup rises monotonically through 4,096 shards; there is no interior
   optimum on this workload, only diminishing returns against rising storage.

### Defects the correctness check caught

- `newline_bytes_unsafe` — fastest row counter, overcounts the reviews file by
  5,495 rows (104,719 vs 99,224) because review text contains newlines inside
  quoted fields.
- **Arrow's CSV reader with default options** — 12.9× faster, but reads an empty
  field as `""` rather than null unless `strings_can_be_null=True`. That
  silently turned 2,965 missing delivery dates into empty strings, which would
  have let the no-nulls quality gate pass on genuinely absent data. Fixed, then
  adopted.

Both would have produced plausible, wrong pipelines that ran faster.

### Carried into the warehouse design

Partition `fct_orders` by order month (dashboard queries are month-scoped, the
selective case pruning serves) and **cluster** rather than partition by
`seller_id` (a month partition cannot prune a seller predicate).

### Still open

- DuckDB is benchmarked for the co-occurrence join but not adopted in the
  pipeline; the sparse-matrix strategy is the better fit and is also not yet
  adopted. Both are measured, neither is landed.
- The Spark cleaning path is not in the comparison — PySpark is an optional
  dependency and is not installed here.
- Cold-cache behaviour is unmeasured; dropping the page cache needs root.

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
| `reports/benchmarks/optimisation_report.md` | The optimisation study: strategy tables, fragmentation matrix, crossover, scaling |
| `reports/benchmarks/results.json` | Every measurement, machine-readable; the report is generated from it |
| `reports/benchmarks/figures/f1–f5*.png` | Crossover curve, scaling curves, layout matrix, shard sweep, strategy speedups |
| `docs/OPTIMISATION_CONCEPTS.md` | Course concept -> the file that measures it, incl. what deliberately does not apply |

**Artifacts** (published pages, not in the repo):
- Data audit — `claude.ai/code/artifact/e8113c4f-0e53-4f2f-8d70-222f5c5a5a60`
- Assignment 2 feedback response — `claude.ai/code/artifact/8788c14c-184e-41dc-8f03-51b171eaee7e`
- Synthetic inventory slide guide — `claude.ai/artifact/6mAfNKxhALy8WCWgMxTzEi`

**Not in the repo:** the five spec PDFs (Lab 2, Lab 3, two architecture guides,
sprint progress note) and the Canva deck. Re-attach if a question turns on their
detail.
