# E-Commerce Data Engineering Platform

Batch data-engineering pipeline on the Olist Brazilian E-Commerce dataset, built
for two analytical use cases: **product co-occurrence** (explainable
recommendations) and **inventory analytics** (rule-based restocking).

No AI/ML by deliberate choice — recommendations come from a weighted
co-occurrence graph and restocking from deterministic rules.

```
Olist CSVs → ingestion → raw zone → cleaning → processed zone
                                                    ├── synthetic inventory → restock rules
                                                    └── co-occurrence graph → recommendations
             (dbt → BigQuery → FastAPI → dashboard: not yet built)
```

## Project layout

```
src/ecom/
  config.py              Settings and named analytical constants
  contracts.py           Source contracts for the 6 tables the analysis uses
  source_registry.py     Source contracts for all 9 Olist CSVs
  logging_setup.py       One logging configuration
  cli.py                 Command-line entrypoints
  storage/               StorageBackend interface: local filesystem and MinIO
  ingestion/             Source → raw zone
    ingest.py              Contract-checked landing with a SHA-256 manifest
    source_reader.py       Header validation, checksums, row counting
    raw_writer.py          Run-date partitioned raw zone + provenance manifest
    run_ingestion.py       Ingestion CLI
  cleaning/              Raw → processed, pandas path
  spark/                 Raw → processed, Spark path (optional dependency)
    zones.py               Storage-zone paths
    schema_contracts.py    Cleaned-data contracts per table
    cleaning_utils.py      Pure Spark transforms
    validators.py          Data-quality checks
    quality_report.py      Per-run quality report
    clean_pipeline.py      Spark cleaning orchestration
  quality/               Quality gates for the pandas path
  synthetic/             Synthetic inventory generator and validation
  analysis/              Profiling metrics, co-occurrence graph, figures
  bench/                 Optimisation study
    harness.py             Timing, memory and correctness checking
    workloads.py           Alternative implementations of the hot operations
    fragmentation.py       Storage layouts and the queries that separate them
    studies.py             Selectivity, shard-count, scaling and materialisation sweeps
    run_bench.py           Benchmark orchestration (the only I/O here)
    report.py              Renders results.json as Markdown and figures
tests/                   pytest suite for both paths
docs/
  CODING_STANDARDS.md    Conventions, implementing the project tracker's rules
  PROJECT_STATUS.md      Current state, measured findings, open decisions
  OPTIMISATION_CONCEPTS.md  Course concept → where it is measured in the code
  contracts.md           Data contracts between pipeline stages
data/                    Olist source CSVs as downloaded, never modified
reports/                 Generated reports, figures and slide charts
```

## Two cleaning paths, on purpose

The pipeline has **two implementations of the cleaning stage**:

| Path | Engine | Module | Run with |
|---|---|---|---|
| pandas | pandas | `ecom.cleaning` | `make clean` |
| Spark | PySpark | `ecom.spark.clean_pipeline` | `python -m ecom.spark.clean_pipeline <run-date>` |

They are kept side by side deliberately so the two engines can be benchmarked
against each other on identical input — the optimisation comparison the course
asks for. PySpark is an **optional dependency**; the pandas path and every test
that does not need Spark run without it installed.

## Setup

Requires Python 3.10+. Java 17+ only if you want the Spark path.

```bash
make install                    # venv + dependencies
pip install -e '.[spark]'       # optional: adds PySpark
pip install -e '.[minio]'       # optional: adds the MinIO backend
cp .env.example .env
```

## Running it

```bash
make pipeline      # ingest → clean → inventory → analyse  (pandas path)
make ingest        # source → raw zone
make clean         # raw → processed  (pandas)
make inventory     # generate the synthetic inventory table
make analyse       # profiling metrics + figures
make bench         # optimisation study → results.json + report + figures
make check         # ruff + black + pytest
```

Spark path, for a given run date:

```bash
python -m ecom.ingestion.run_ingestion --run-date 2026-10-13
python -m ecom.spark.clean_pipeline 2026-10-13
```

Storage backend is a config switch, not a rewrite:

```bash
make minio-up
ECOM_STORAGE_BACKEND=minio make pipeline
```

## Configuration

Every path is an environment variable with a local-filesystem default.

| Variable | Default | Used by |
|---|---|---|
| `ECOM_STORAGE_BACKEND` | `local` | pandas path (`local` or `minio`) |
| `ECOM_SOURCE_DIR` | `data` | pandas ingestion |
| `ECOM_RAW_ROOT` | `data/raw` | pandas ingestion |
| `ECOM_PROCESSED_ROOT` | `data/processed` | pandas cleaning |
| `ECOM_FAST_READER` | `0` | pandas cleaning — parse raw CSVs with Arrow instead of pandas. Verified to produce an identical processed layer; 1.6× on the cleaning stage. |
| `OLIST_SOURCE_DIR` | `data` | Spark-path ingestion |
| `OLIST_RAW_ZONE_DIR` | `storage/raw/olist` | Spark-path ingestion and cleaning |
| `OLIST_PROCESSED_ZONE_DIR` | `storage/processed/olist` | Spark cleaning |
| `OLIST_QUARANTINE_ZONE_DIR` | `storage/quarantine/olist` | Spark cleaning |
| `OLIST_REPORTS_DIR` | `storage/reports` | Spark cleaning |

## Documentation

- **`docs/PROJECT_STATUS.md`** — read this first: current state, measured
  findings, open decisions and the next workstream.
- `docs/CODING_STANDARDS.md` — conventions. The load-bearing rule is that a
  transform takes a DataFrame and returns a DataFrame and never does I/O.
- `docs/contracts.md` — the data contract between ingestion and cleaning.
- `docs/OPTIMISATION_CONCEPTS.md` — which course concept each benchmark
  exercises, and which ones deliberately do not apply here.
- `reports/benchmarks/optimisation_report.md` — the measured optimisation
  study: strategy comparisons, the fragmentation matrix, the selectivity
  crossover and the scaling curves.
- `reports/synthetic_inventory_validation.md` — how the synthetic data was
  validated.
