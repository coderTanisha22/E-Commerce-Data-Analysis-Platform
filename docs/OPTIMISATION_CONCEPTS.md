# Concepts exercised by the optimisation study

Where each idea from the course appears in this repository as running,
measured code. The measurements themselves live in
`reports/benchmarks/optimisation_report.md`; this file is the index from
syllabus to implementation, so a claim in a viva can be traced to a file.

## Query processing and optimisation

| Concept | Where it is implemented | What was measured |
|---|---|---|
| Join methods J1–J4 | `bench/workloads.py` — `cooccur_nested_loop` (J1 nested loop), `cooccur_hash_join` (J4 hash), `cooccur_sort_merge` (J3 sort–merge), plus a sparse linear-algebra form and a SQL form | Five implementations of one self-join, verified to return identical output |
| Cost-based optimisation | `cooccur_duckdb` — the query states *what*, DuckDB's optimiser chooses the physical plan and the parallelism | The only strategy with a sublinear fitted scaling exponent |
| Selectivity and selection cardinality | `bench/studies.py` — `selectivity_sweep` | The crossover selectivity at which pruning stops paying |
| Projection pushdown | `bench/workloads.py` — `read_with_projection` vs `read_all_then_select` | Reading 2 of 12 columns vs reading all and discarding |
| Predicate pushdown / partition pruning | `bench/fragmentation.py` — `q_revenue_for_months` on the `horizontal` layout | Bytes read, measured from the files actually opened |
| Pipelining vs materialisation | `bench/studies.py` — `materialisation_study` | Cost of writing Parquet between stages vs keeping intermediates in memory |
| Amdahl's law | `bench/run_bench.py` — `_bench_pipeline_flag` | A 12.9× component speedup against its much smaller whole-stage effect |

## Distributed data: fragmentation and sharding

| Concept | Where it is implemented | What was measured |
|---|---|---|
| Horizontal (range) fragmentation | `write_horizontal`, partitioning by `order_month` | Best layout for a month predicate, worst for a seller predicate |
| Vertical fragmentation | `write_vertical`, hot/cold column split rejoined on `row_id` | **Rejected on evidence** — 1.35× when a query stays in the hot fragment (which Parquet gives free), 0.025× when it spans the split |
| Hash sharding | `write_sharded`, `blake2b(seller_id) % n` | Speedup never turns over through 4,096 shards, but storage overhead reaches +80%, so the recommendation is a constrained optimum, not an argmax |
| Stable partitioning function | `_shard_of` uses blake2b, not Python's salted `hash()` | A layout written in one process stays readable in the next |
| Skew | Range fragmentation on month is uneven (1,711 to 7,616 rows); hash sharding is even by construction | Per-partition row counts |

## Storage and file formats

| Concept | Where it is implemented | What was measured |
|---|---|---|
| Columnar storage | Parquet throughout the processed layer | Projection pushdown; and why vertical fragmentation adds nothing |
| Arrow in-memory columnar layout | `StorageBackend.get_csv_arrow` | ~11× faster read-and-trim, ~7× less Python heap, identical output |
| Compression vs file count | `PARQUET_COMPRESSION`, `_layout_stats` | Partitioning *reduced* storage 20% by clustering a constant column, yet was still slower on a full scan |
| Small-file penalty | `shard_sweep` out to 4,096 shards | Storage overhead climbing from +1.6% to +79.7% as files shrink |

## Warehouse modelling

| Concept | Where it is implemented | What was measured |
|---|---|---|
| Fact table grain | `build_fact_table` — one row per (order, product, seller) | 99,130 delivered rows inside the window |
| Surrogate key | `row_id`, which is what lets vertical fragments rejoin | — |
| Partitioning and clustering choice | Carried into the warehouse design: partition `fct_orders` by month, cluster by `seller_id` | The layout matrix is the evidence for choosing differently per column |

## Data quality as a first-class concern

The study's correctness checking is not incidental — it is the part that makes
the performance numbers usable.

| Concept | Where it is implemented | What it caught |
|---|---|---|
| Verifying an optimisation preserves semantics | `harness.outputs_match`, compared against the baseline for every strategy | Two faster strategies that returned different answers |
| Null semantics across engines | `get_csv_arrow` sets `strings_can_be_null=True` | Arrow reading 2,965 missing delivery dates as `""` instead of null |
| Parser correctness under quoting | `count_rows_newlines` vs `count_rows_csv_reader` | A 5,495-row overcount on the reviews file |
| Reproducibility as a regression test | The synthetic inventory SHA-256 is unchanged by the optimisation | That the fast reader is result-neutral end to end |

## Deliberately not applicable

Recording these matters as much as the rest: a study that claims every concept
applies has not understood any of them.

- **Transactions, 2PL, isolation levels, 2PC.** This is a single-writer batch
  pipeline. There is no concurrency to control. The nearest real analogue is
  that materialising each stage plus the SHA-256 manifest gives recovery and
  auditability, which is the durability concern rather than the isolation one.
  Isolation would become relevant if the planned FastAPI layer read the
  processed layer while a pipeline run rewrote it.
- **Kafka consumer lag.** Named in the feedback as an example metric, but this
  pipeline is batch. Latency, throughput and peak memory are the applicable
  metrics and are what the harness records.
- **Big data infrastructure.** The whole dataset is about 121 MB and the full
  pipeline runs in seconds. This is emphatically *not* big data, and claiming
  otherwise would be the weakest thing in the report. The defensible claim is
  the opposite one: the dataset is small enough to measure precisely and to run
  a full factorial of layouts and volumes, which is why the study can report a
  crossover point rather than a single anecdote. The patterns built here —
  partitioning, columnar storage, contracts, idempotency, verified
  optimisation — are the ones that transfer to a volume that would need a
  cluster.
