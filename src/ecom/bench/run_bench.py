"""Benchmark orchestration: the only module in the package that does I/O.

Mirrors the split the rest of the project uses -- :mod:`ecom.bench.workloads`
and :mod:`ecom.bench.studies` hold pure measurement logic, and this module
reads the processed layer, runs everything and writes the results file.

The output is a single JSON document so that the report, the charts and any
future comparison all read the same numbers. Re-running overwrites it, and the
environment block records enough about the machine that two results files can
be told apart rather than silently compared.
"""

from __future__ import annotations

import json
import logging
import platform
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

import pandas as pd

from ecom.bench import fragmentation as frag
from ecom.bench import studies
from ecom.bench.harness import DEFAULT_TRIALS, WorkloadResult, run_workload, time_callable
from ecom.bench.workloads import (
    COOCCURRENCE_STRATEGIES,
    PROJECTION_STRATEGIES,
    READ_TRIM_STRATEGIES,
    ROW_COUNT_STRATEGIES,
    TIMESTAMP_STRATEGIES,
)
from ecom.config import Settings, get_settings
from ecom.storage import StorageBackend, get_storage

logger = logging.getLogger(__name__)

RESULTS_SUBDIR = "benchmarks"
"""Everything the study produces lands under reports/benchmarks/."""

ROW_COUNT_FILE = "olist_order_reviews_dataset.csv"
"""The reviews file is the row-count benchmark's input because it is the one
Olist table with newlines inside quoted fields, which is what separates a
correct counter from a merely fast one."""

TRIM_CELLS_PER_TABLE = 795_528
"""String cells in the orders table: 99,441 rows x 8 text columns. Used as the
throughput denominator for the read-and-trim workload. The whole raw layer
holds 2,390,364 such cells across six tables."""

FRAGMENTATION_SCALE = 4
"""The fragmentation study runs on a 4x fact table. At the real 99k rows every
query finishes in roughly ten milliseconds, where timer noise is a large
fraction of the measurement and the crossover estimate wobbles. 4x keeps the
queries comfortably above the noise floor without exhausting memory."""

SWEEP_TRIALS = 9
"""More trials for the sweeps than for single workloads: the crossover point is
derived from the ratio of two small numbers, so it needs the tighter median."""


def _environment() -> dict[str, object]:
    """Record what the numbers were measured on."""
    return {
        "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "processor": platform.machine(),
        "pandas": pd.__version__,
        "cache_state": "warm",
        "caveat": (
            "Single machine, single process, warm page cache. Relative costs "
            "between strategies are the result; absolute times are not portable."
        ),
    }


def _bench_cooccurrence(order_products: pd.DataFrame) -> WorkloadResult:
    """Five join strategies for the product co-occurrence self-join."""
    return run_workload(
        workload="co-occurrence self-join",
        concept="Join methods J1-J4; vectorised vs interpreted execution",
        strategies=[
            (name, lambda run=fn: run(order_products)) for name, fn in COOCCURRENCE_STRATEGIES
        ],
        input_rows=len(order_products),
        unit="order-product rows",
        notes={
            "nested_loop_python": "Current pipeline implementation.",
            "sql_duckdb": "Plan chosen by a cost-based optimiser, not by us.",
            "sort_merge_numpy": "Pair generation is vectorised but the per-basket loop is not.",
        },
    )


def _bench_row_count(source_dir: Path) -> WorkloadResult:
    """Three ways to count CSV rows, one of them wrong."""
    path = source_dir / ROW_COUNT_FILE
    return run_workload(
        workload="CSV row count",
        concept="Scan cost; correctness under quoted newlines",
        strategies=[(name, lambda run=fn: run(path)) for name, fn in ROW_COUNT_STRATEGIES],
        input_rows=0,
        unit="file",
        measure_memory=False,
        notes={
            "newline_bytes_unsafe": (
                "Fastest and wrong: counts newlines inside quoted review text as "
                "row terminators, overcounting this file."
            )
        },
    )


def _bench_read_trim(settings: Settings) -> WorkloadResult:
    """Four read-and-trim paths differing only in the dtype the CSV lands in.

    This workload reads from the raw directory directly rather than through the
    storage backend, because the strategies under test *are* different reader
    configurations and a backend that hides the file would hide the variable.
    It is therefore local-filesystem only, like the rest of the layout study.
    """
    from ecom.ingestion.ingest import SOURCE_NAME

    path = settings.resolve(settings.raw_root) / SOURCE_NAME / "orders.csv"
    return run_workload(
        workload="CSV read + whitespace trim",
        concept="Columnar in-memory layout; vectorisation; measure before optimising",
        strategies=[(name, lambda run=fn: run(path)) for name, fn in READ_TRIM_STRATEGIES],
        input_rows=TRIM_CELLS_PER_TABLE,
        unit="string cells",
        notes={
            "read_string_then_trim": "Current pipeline read path.",
            "read_arrow_then_trim": (
                "Identical trim code; only the dtype the CSV was read into differs."
            ),
            "read_arrow_detect_skip": (
                "No Olist column carries padding, so this skips the trim entirely."
            ),
        },
    )


def _bench_timestamps(storage: StorageBackend) -> WorkloadResult:
    """Three ways to parse a timestamp column."""
    from ecom.ingestion.ingest import SOURCE_NAME

    frame = storage.get_csv(
        storage.raw_key(SOURCE_NAME, "orders"), dtype="string", encoding="utf-8-sig"
    )
    series = frame["order_purchase_timestamp"]
    return run_workload(
        workload="timestamp parsing",
        concept="Avoiding per-value interpretation; Arrow kernels",
        strategies=[(name, lambda run=fn: run(series)) for name, fn in TIMESTAMP_STRATEGIES],
        input_rows=len(series),
        unit="timestamps",
    )


def _bench_projection(root: Path, fact: pd.DataFrame) -> WorkloadResult:
    """Reading two columns of Parquet, with and without pushdown."""
    root.mkdir(parents=True, exist_ok=True)
    path = root / "fact_projection.parquet"
    frag._write_one(fact, path)
    columns = ["seller_id", "line_revenue"]
    return run_workload(
        workload="Parquet projection",
        concept="Projection pushdown; columnar storage",
        strategies=[
            (name, lambda run=fn: run(path, columns)) for name, fn in PROJECTION_STRATEGIES
        ],
        input_rows=len(fact),
        unit="fact rows",
        notes={
            "projection_pushdown": (
                f"Reads 2 of {len(fact.columns)} columns; the rest are never decompressed."
            )
        },
    )


def _layout_comparison(fact: pd.DataFrame, root: Path, trials: int) -> dict[str, object]:
    """Query four physical layouts three ways each.

    This is the matrix that shows a layout is not good or bad in itself. Each
    cell is checked against the true answer computed from the frame in memory,
    so a layout cannot win by returning something wrong.
    """
    shutil.rmtree(root, ignore_errors=True)
    layouts: dict[str, tuple[Path, int]] = {}
    stats: list[frag.LayoutStats] = [frag.write_monolithic(fact, root / "monolithic")]
    layouts["monolithic"] = (root / "monolithic", 0)
    stats.append(frag.write_horizontal(fact, root / "horizontal"))
    layouts["horizontal"] = (root / "horizontal", 0)
    stats.append(frag.write_vertical(fact, root / "vertical"))
    layouts["vertical"] = (root / "vertical", 0)
    shards = 16
    stats.append(frag.write_sharded(fact, root / "sharded", shards))
    layouts[f"sharded_{shards}"] = (root / "sharded", shards)

    baseline_bytes = stats[0].total_bytes
    for stat in stats:
        stat.overhead_pct = round(100 * (stat.total_bytes / baseline_bytes - 1), 1)

    months = sorted(fact["order_month"].unique())[:2]
    seller = fact["seller_id"].value_counts().index[0]
    truth = {
        "total_revenue": float(fact["line_revenue"].sum()),
        "two_month_revenue": float(
            fact.loc[fact["order_month"].isin(months), "line_revenue"].sum()
        ),
        "seller_revenue": float(fact.loc[fact["seller_id"] == seller, "line_revenue"].sum()),
    }

    # Each query takes the same three arguments so the matrix below can call
    # them uniformly; the two that cannot use a shard count ignore it.
    queries = {
        "total_revenue": lambda root, layout, _shards: frag.q_total_revenue(root, layout),
        "two_month_revenue": lambda root, layout, _shards: frag.q_revenue_for_months(
            root, months, layout
        ),
        "seller_revenue": lambda root, layout, shards: frag.q_revenue_for_seller(
            root, seller, layout, shards
        ),
    }

    results: list[dict[str, object]] = []
    for query_name, query in queries.items():
        for layout, (path, sh) in layouts.items():
            times, outcome = time_callable(
                lambda run=query, root=path, lay=layout, shards=sh: run(root, lay, shards), trials
            )
            seconds = median(times)
            results.append(
                {
                    "query": query_name,
                    "layout": layout,
                    "seconds": round(seconds, 5),
                    "bytes_read": outcome.bytes_read,
                    "correct": abs(outcome.answer - truth[query_name]) < 0.01,
                }
            )
            logger.info("%-20s %-14s %.5fs %10d B", query_name, layout, seconds, outcome.bytes_read)

    frame = pd.DataFrame(results)
    # Speedup is quoted per query against the monolithic layout, because that
    # is the design the pipeline would otherwise keep.
    base = frame[frame["layout"] == "monolithic"].set_index("query")["seconds"]
    frame["speedup_vs_monolithic"] = frame.apply(
        lambda row: round(base[row["query"]] / row["seconds"], 3) if row["seconds"] else 0.0,
        axis=1,
    )
    base_bytes = frame[frame["layout"] == "monolithic"].set_index("query")["bytes_read"]
    frame["bytes_saved_pct"] = frame.apply(
        lambda row: (
            round(100 * (1 - row["bytes_read"] / base_bytes[row["query"]]), 1)
            if base_bytes[row["query"]]
            else 0.0
        ),
        axis=1,
    )

    return {
        "fact_rows": len(fact),
        "layouts": [
            {
                "layout": stat.layout,
                "file_count": stat.file_count,
                "total_bytes": stat.total_bytes,
                "storage_overhead_pct": stat.overhead_pct,
            }
            for stat in stats
        ],
        "cells": frame.to_dict(orient="records"),
        "all_correct": bool(frame["correct"].all()),
    }


def _bench_pipeline_flag(settings: Settings, work: Path, trials: int) -> dict[str, object]:
    """Time the whole cleaning stage with and without the fast reader.

    The single-workload benchmarks measure components in isolation, which is
    how a 12.9x read speedup can coexist with a far smaller end-to-end gain.
    This study closes that gap: it runs the real ``clean_all`` both ways and
    reports what the optimisation is worth once the quality gates, transforms
    and Parquet writes it does not touch are included -- Amdahl's law measured
    rather than asserted.

    It also proves the switch is safe. Both runs write a full processed layer
    and every table is compared value by value, ignoring only the dtype backend
    the frames are held in, which is the one thing the flag is allowed to
    change.

    Returns:
        Times, speedup, and the per-table equivalence verdict.
    """
    from ecom.cleaning.run_clean import clean_all

    outputs: dict[str, dict[str, pd.DataFrame]] = {}
    timings: dict[str, float] = {}
    counts: dict[str, dict[str, int]] = {}

    for label, fast in (("baseline", False), ("fast_reader", True)):
        run_settings = settings.model_copy(
            update={"processed_root": work / f"flag_{label}", "fast_reader": fast}
        )
        run_storage = get_storage(run_settings)
        times, result = time_callable(
            lambda store=run_storage, conf=run_settings: clean_all(storage=store, settings=conf),
            trials,
        )
        timings[label] = median(times)
        counts[label] = result
        outputs[label] = {
            table: run_storage.get_parquet(run_storage.processed_key(table)) for table in result
        }
        logger.info("clean_all %-12s %.3fs", label, timings[label])

    def canonical(frame: pd.DataFrame) -> pd.DataFrame:
        """Strip the dtype backend so only values are compared."""
        return frame.astype(object).where(frame.notna(), None).reset_index(drop=True)

    tables = []
    for table in counts["baseline"]:
        left = outputs["baseline"][table]
        right = outputs["fast_reader"][table][left.columns]
        identical = canonical(left).equals(canonical(right))
        tables.append({"table": table, "rows": len(left), "identical": identical})

    base, fast_s = timings["baseline"], timings["fast_reader"]
    return {
        "baseline_s": round(base, 4),
        "fast_reader_s": round(fast_s, 4),
        "speedup": round(base / fast_s, 3) if fast_s else 0.0,
        "row_counts_identical": counts["baseline"] == counts["fast_reader"],
        "tables": tables,
        "all_tables_identical": all(entry["identical"] for entry in tables),
    }


def run_all(
    *,
    storage: StorageBackend | None = None,
    settings: Settings | None = None,
    trials: int = DEFAULT_TRIALS,
    scale_factors: tuple[int, ...] = studies.SCALE_FACTORS,
    work_dir: Path | None = None,
) -> dict[str, object]:
    """Run every workload and study, write the results file, return the results.

    Args:
        storage: Backend to read the processed layer from.
        settings: Override settings, mainly for tests.
        trials: Measured runs per strategy for the single workloads.
        scale_factors: Volume multipliers for the scaling study.
        work_dir: Scratch directory for the layouts written during the study.
            Defaults to a ``_bench_work`` folder beside the results, and is
            removed afterwards because the layouts are reproducible artefacts,
            not deliverables.

    Returns:
        The full results document, exactly as written to ``results.json``.
    """
    settings = settings or get_settings()
    storage = storage or get_storage(settings)
    reports = settings.resolve(settings.reports_dir) / RESULTS_SUBDIR
    reports.mkdir(parents=True, exist_ok=True)
    work = work_dir or reports / "_bench_work"
    work.mkdir(parents=True, exist_ok=True)

    order_products = storage.get_parquet(storage.processed_key("order_products"))
    order_lines = storage.get_parquet(storage.processed_key("order_lines"))
    orders = storage.get_parquet(storage.processed_key("orders"))

    fact = frag.build_fact_table(
        order_lines,
        orders,
        pd.Timestamp(settings.window_start),
        pd.Timestamp(settings.window_end),
    )
    scaled_fact = frag.replicate_fact(fact, FRAGMENTATION_SCALE)
    logger.info(
        "fact table %d rows, fragmentation study at %dx = %d rows",
        len(fact),
        FRAGMENTATION_SCALE,
        len(scaled_fact),
    )

    logger.info("--- workloads")
    workloads = [
        _bench_cooccurrence(order_products),
        _bench_row_count(settings.resolve(settings.source_dir)),
        _bench_read_trim(settings),
        _bench_timestamps(storage),
        _bench_projection(work, fact),
    ]

    logger.info("--- layout comparison")
    layout = _layout_comparison(scaled_fact, work / "layouts", trials)

    logger.info("--- selectivity sweep")
    sweep = studies.selectivity_sweep(scaled_fact, work / "sweep", trials=SWEEP_TRIALS)

    logger.info("--- shard sweep")
    shard = studies.shard_sweep(scaled_fact, work / "shards", trials=SWEEP_TRIALS)

    logger.info("--- materialisation vs pipelining")
    materialisation = studies.materialisation_study(scaled_fact, work / "mat", trials=trials)

    logger.info("--- pipeline flag: fast reader on the real clean stage")
    pipeline_flag = _bench_pipeline_flag(settings, work, trials=3)

    logger.info("--- volume scaling")
    scaling = studies.volume_scaling(order_products, factors=scale_factors)

    document: dict[str, object] = {
        "environment": _environment(),
        "trials": trials,
        "fragmentation_scale": FRAGMENTATION_SCALE,
        "fact_rows_1x": len(fact),
        "workloads": [workload.to_dict() for workload in workloads],
        "layout_comparison": layout,
        "selectivity_sweep": {
            "rows": sweep.to_dict(orient="records"),
            "crossover_selectivity_pct": studies.crossover_point(sweep),
            "all_correct": bool(sweep["answers_correct"].all()),
        },
        "shard_sweep": {
            "rows": shard.to_dict(orient="records"),
            **studies.shard_recommendation(shard),
            "all_correct": bool(shard["answer_correct"].all()),
        },
        "materialisation": materialisation.to_dict(orient="records"),
        "pipeline_flag": pipeline_flag,
        "volume_scaling": {
            "rows": scaling.to_dict(orient="records"),
            "exponents": {
                name: studies.fit_scaling_exponent(scaling, name)
                for name in scaling["strategy"].unique()
            },
        },
    }

    results_path = reports / "results.json"
    results_path.write_text(json.dumps(document, indent=2, default=str))
    logger.info("wrote %s", results_path)

    shutil.rmtree(work, ignore_errors=True)
    return document
