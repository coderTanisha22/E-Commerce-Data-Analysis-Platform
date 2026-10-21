"""Multi-point studies: sweeps that need many measurements to mean anything.

A single benchmark number answers "which is faster here". These studies answer
the more useful question, "where does the answer change". Each returns a tidy
DataFrame so the report and the charts share one source of truth.

* :func:`selectivity_sweep` varies how much of the table a query asks for and
  finds the **crossover point** -- the selectivity above which partition
  pruning stops paying for itself. This is the single most informative result
  in the study, because it turns "partitioning helped 3x" into a rule for when
  to partition at all.
* :func:`shard_sweep` varies the number of shards to show that the optimum is
  interior: too few shards prune little, too many drown the gain in per-file
  overhead.
* :func:`volume_scaling` re-runs the join strategies at increasing volume. At
  the project's real size everything finishes in under a second, so the
  interesting fact is not the absolute time but whether the curves diverge --
  which is what distinguishes an algorithmic win from a constant-factor one.
* :func:`materialisation_study` compares writing every stage to Parquet against
  keeping intermediates in memory, quantifying the price the pipeline pays for
  restartability.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from statistics import median

import numpy as np
import pandas as pd

from ecom.bench import fragmentation as frag
from ecom.bench.harness import DEFAULT_TRIALS, time_callable
from ecom.bench.workloads import COOCCURRENCE_STRATEGIES

logger = logging.getLogger(__name__)

SCALE_FACTORS = (1, 2, 4, 8)
"""Volume multipliers. Doubling four times is enough to separate a linear curve
from a quadratic one while keeping the slowest strategy's total runtime sane."""

SELECTIVITY_STEPS = (1, 2, 3, 5, 7, 10, 13, 16, 19)
"""Months requested out of 19. Dense at the low end because that is where the
crossover lies, and partition pruning is only interesting when it prunes."""


def selectivity_sweep(fact: pd.DataFrame, root: Path, trials: int = DEFAULT_TRIALS) -> pd.DataFrame:
    """Measure partitioned versus monolithic cost across query selectivity.

    Both layouts are written once, then queried for an increasing number of
    months. The monolithic layout's cost is flat -- it always reads everything
    -- while the partitioned layout's cost grows with the number of partitions
    touched. Where the two lines meet is the crossover.

    Args:
        fact: Fact table carrying ``order_month``.
        root: Directory to write both layouts under; it is replaced.
        trials: Measured runs per point.

    Returns:
        One row per selectivity step with times, bytes and the speedup.
    """
    shutil.rmtree(root, ignore_errors=True)
    mono_root, horiz_root = root / "mono", root / "horiz"
    frag.write_monolithic(fact, mono_root)
    frag.write_horizontal(fact, horiz_root)

    months = sorted(fact["order_month"].unique())
    rows = []
    for count in SELECTIVITY_STEPS:
        if count > len(months):
            continue
        wanted = months[:count]
        truth = float(fact.loc[fact["order_month"].isin(wanted), "line_revenue"].sum())

        mono_times, mono_out = time_callable(
            lambda months=wanted: frag.q_revenue_for_months(mono_root, months, "monolithic"),
            trials,
        )
        horiz_times, horiz_out = time_callable(
            lambda months=wanted: frag.q_revenue_for_months(horiz_root, months, "horizontal"),
            trials,
        )
        # A sweep that silently returned wrong numbers would still draw a
        # smooth curve, so every point is checked against the truth.
        correct = abs(mono_out.answer - truth) < 0.01 and abs(horiz_out.answer - truth) < 0.01

        mono_s, horiz_s = median(mono_times), median(horiz_times)
        rows.append(
            {
                "months_selected": count,
                "selectivity_pct": round(100 * count / len(months), 1),
                "rows_matched": int(fact["order_month"].isin(wanted).sum()),
                "monolithic_s": round(mono_s, 5),
                "horizontal_s": round(horiz_s, 5),
                "speedup": round(mono_s / horiz_s, 3) if horiz_s else 0.0,
                "monolithic_bytes": mono_out.bytes_read,
                "horizontal_bytes": horiz_out.bytes_read,
                "bytes_saved_pct": (
                    round(100 * (1 - horiz_out.bytes_read / mono_out.bytes_read), 1)
                    if mono_out.bytes_read
                    else 0.0
                ),
                "answers_correct": correct,
            }
        )
        logger.info(
            "selectivity %2d/19 mono %.4fs horiz %.4fs x%.2f",
            count,
            mono_s,
            horiz_s,
            mono_s / horiz_s if horiz_s else 0,
        )
    return pd.DataFrame(rows)


def crossover_point(sweep: pd.DataFrame) -> float | None:
    """Interpolate the selectivity at which the speedup curve crosses 1.0.

    The sweep samples discrete month counts, so the crossover almost never
    lands on a sampled point. Linear interpolation between the last point above
    1.0 and the first point below it gives a usable estimate.

    Returns:
        Selectivity in percent, or None if the curve never crosses.
    """
    above = sweep[sweep["speedup"] >= 1.0]
    below = sweep[sweep["speedup"] < 1.0]
    if above.empty or below.empty:
        return None
    last = above.iloc[-1]
    first = below.iloc[0]
    span = last["speedup"] - first["speedup"]
    if span == 0:
        return float(first["selectivity_pct"])
    weight = (last["speedup"] - 1.0) / span
    span_pct = first["selectivity_pct"] - last["selectivity_pct"]
    return round(float(last["selectivity_pct"] + weight * span_pct), 1)


def shard_sweep(
    fact: pd.DataFrame,
    root: Path,
    counts: tuple[int, ...] = frag.SHARD_COUNTS,
    trials: int = DEFAULT_TRIALS,
) -> pd.DataFrame:
    """Measure single-seller lookup cost against the number of hash shards.

    The lookup touches exactly one shard, so more shards means a smaller file
    to read -- until the files get small enough that opening one costs more
    than scanning it, and the Parquet footer becomes a significant fraction of
    each file. The result is a U-shaped curve with an interior optimum.

    Returns:
        One row per shard count, plus a ``monolithic`` reference row.
    """
    shutil.rmtree(root, ignore_errors=True)
    mono_root = root / "mono"
    mono_stats = frag.write_monolithic(fact, mono_root)
    seller = fact["seller_id"].value_counts().index[0]
    truth = float(fact.loc[fact["seller_id"] == seller, "line_revenue"].sum())

    mono_times, mono_out = time_callable(
        lambda: frag.q_revenue_for_seller(mono_root, seller, "monolithic"), trials
    )
    mono_s = median(mono_times)
    rows = [
        {
            "shards": 1,
            "layout": "monolithic",
            "lookup_s": round(mono_s, 5),
            "speedup": 1.0,
            "bytes_read": mono_out.bytes_read,
            "file_count": mono_stats.file_count,
            "total_bytes": mono_stats.total_bytes,
            "storage_overhead_pct": 0.0,
            "answer_correct": abs(mono_out.answer - truth) < 0.01,
        }
    ]

    for shards in counts:
        shard_root = root / f"sh{shards}"
        stats = frag.write_sharded(fact, shard_root, shards)
        times, out = time_callable(
            lambda count=shards, root=shard_root: frag.q_revenue_for_seller(
                root, seller, f"sharded_{count}", count
            ),
            trials,
        )
        seconds = median(times)
        rows.append(
            {
                "shards": shards,
                "layout": f"sharded_{shards}",
                "lookup_s": round(seconds, 5),
                "speedup": round(mono_s / seconds, 3) if seconds else 0.0,
                "bytes_read": out.bytes_read,
                "file_count": stats.file_count,
                "total_bytes": stats.total_bytes,
                "storage_overhead_pct": round(
                    100 * (stats.total_bytes / mono_stats.total_bytes - 1), 1
                ),
                "answer_correct": abs(out.answer - truth) < 0.01,
            }
        )
        logger.info("shards %4d lookup %.5fs x%.2f", shards, seconds, mono_s / seconds)
    return pd.DataFrame(rows)


PLATEAU_TOLERANCE = 0.85
"""A shard count counts as "on the plateau" if it reaches 85% of the best
speedup available inside the storage budget. The band is deliberately wider
than the run-to-run variance observed in this study (the 64- and 256-shard
points moved by about 15% between runs and swapped order), so the
recommendation is reproducible rather than a reading of one run's noise."""

STORAGE_BUDGET_PCT = 10.0
"""How much extra storage a sharded layout may cost before it stops being
worth recommending. Ten percent is a declared engineering budget, not a
measured constant -- it is stated here so the recommendation the study makes is
auditable and can be changed deliberately."""


def shard_recommendation(sweep: pd.DataFrame) -> dict[str, object]:
    """Recommend a shard count, and report the fastest one beside it.

    The fastest layout tested is always the most-sharded one: the lookup reads
    exactly one file and that file keeps shrinking, so speedup creeps upward
    without bound while storage climbs steeply. Reporting the argmax would
    therefore recommend the most expensive layout in the sweep every time.

    A first attempt used the derivative -- the point after which doubling the
    shards stops buying ten percent more speed. That proved unstable: the gain
    between adjacent points is a ratio of sub-ten-millisecond measurements, so
    one noisy point breaks the chain and the answer moved between 64 and 1,024
    shards across runs of this same study.

    What this reports instead is bounded on both sides. Candidates must fit a
    declared storage budget (:data:`STORAGE_BUDGET_PCT`), which is measured
    from the filesystem and so does not move between runs; and among those, the
    *smallest* shard count on the speedup plateau wins
    (:data:`PLATEAU_TOLERANCE`), because several counts are tied within the
    measurement noise and fewer files is the better choice when speed is not
    distinguishable.

    Args:
        sweep: Output of :func:`shard_sweep`.

    Returns:
        The recommendation, the fastest layout, and the budget applied.
    """
    sharded = sweep[sweep["layout"] != "monolithic"].sort_values("shards").reset_index(drop=True)
    fastest = sharded.loc[sharded["speedup"].idxmax()]

    affordable = sharded[sharded["storage_overhead_pct"] <= STORAGE_BUDGET_PCT]
    if len(affordable):
        # Within the budget, take the *smallest* shard count that reaches the
        # plateau rather than the single fastest point. 64 and 256 shards are
        # statistically indistinguishable on this workload -- they swapped
        # places between runs -- so picking the argmax would report a precision
        # the measurement does not have. Fewer files is better when speed is
        # tied: smaller manifests, fewer handles, less metadata.
        ceiling = float(affordable["speedup"].max())
        plateau = affordable[affordable["speedup"] >= ceiling * PLATEAU_TOLERANCE]
        pick = plateau.sort_values("shards").iloc[0]
    else:
        # Keep the contract total: if nothing fits the budget, still say which
        # layout the study would pick.
        pick = sharded.iloc[0]

    return {
        "storage_budget_pct": STORAGE_BUDGET_PCT,
        "recommended_shards": int(pick["shards"]),
        "recommended_speedup": float(pick["speedup"]),
        "recommended_storage_overhead_pct": float(pick["storage_overhead_pct"]),
        "recommended_fits_budget": bool(len(affordable)),
        "fastest_shards": int(fastest["shards"]),
        "fastest_speedup": float(fastest["speedup"]),
        "fastest_storage_overhead_pct": float(fastest["storage_overhead_pct"]),
    }


def replicate_order_products(order_products: pd.DataFrame, factor: int) -> pd.DataFrame:
    """Scale the co-occurrence input while preserving basket structure.

    Each copy gets suffixed order and product ids, so baskets keep their shapes
    and the number of distinct pairs grows in proportion. Repeating rows
    verbatim instead would merge every copy's pairs into the same keys, making
    the group-by cheaper per row as the data grew and flattering every strategy.
    """
    if factor == 1:
        return order_products.copy()
    copies = []
    for index in range(factor):
        copy = order_products.copy()
        if index:
            suffix = f"_{index}"
            copy["order_id"] = copy["order_id"].astype("string") + suffix
            copy["product_id"] = copy["product_id"].astype("string") + suffix
        copies.append(copy)
    return pd.concat(copies, ignore_index=True)


def volume_scaling(
    order_products: pd.DataFrame,
    factors: tuple[int, ...] = SCALE_FACTORS,
    trials: int = 3,
    skip_above_seconds: float = 20.0,
) -> pd.DataFrame:
    """Re-run every co-occurrence strategy at increasing input volume.

    Args:
        order_products: The real deduplicated basket frame.
        factors: Volume multipliers to test.
        trials: Measured runs per point; fewer than elsewhere because the
            largest points are slow and the ranking is already stable at three.
        skip_above_seconds: Once a strategy exceeds this at some scale, it is
            not run at larger scales. Without this the Python nested loop
            dominates the total runtime of the study for no extra insight.

    Returns:
        One row per (strategy, factor) with time and derived throughput.
    """
    rows = []
    abandoned: set[str] = set()
    for factor in factors:
        scaled = replicate_order_products(order_products, factor)
        for name, fn in COOCCURRENCE_STRATEGIES:
            if name in abandoned:
                continue
            times, out = time_callable(lambda run=fn, frame=scaled: run(frame), trials)
            seconds = median(times)
            rows.append(
                {
                    "strategy": name,
                    "factor": factor,
                    "input_rows": len(scaled),
                    "pairs_out": len(out),
                    "seconds": round(seconds, 5),
                    "rows_per_s": round(len(scaled) / seconds) if seconds else 0,
                }
            )
            logger.info("scaling x%d %-22s %8.4fs", factor, name, seconds)
            if seconds > skip_above_seconds:
                abandoned.add(name)
                logger.info("abandoning %s above x%d: %.1fs", name, factor, seconds)
    return pd.DataFrame(rows)


def materialisation_study(
    fact: pd.DataFrame, root: Path, trials: int = DEFAULT_TRIALS
) -> pd.DataFrame:
    """Compare materialising each stage to disk against pipelining in memory.

    The pipeline writes Parquet between every stage. That is what makes a run
    restartable and auditable, but it is not free: each stage pays a serialise,
    compress and write, and the next stage pays a read and decompress for data
    that was already in memory.

    Three stages are simulated on the fact table -- filter, aggregate, rank --
    which is the shape of the real clean/inventory/analyse sequence.

    Returns:
        One row per approach with time, bytes written and the derived overhead.
    """
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)

    def stage_filter(frame: pd.DataFrame) -> pd.DataFrame:
        return frame[frame["quantity"] >= 1]

    def stage_aggregate(frame: pd.DataFrame) -> pd.DataFrame:
        return frame.groupby(["seller_id", "order_month"], as_index=False, sort=False).agg(
            revenue=("line_revenue", "sum"), units=("quantity", "sum")
        )

    def stage_rank(frame: pd.DataFrame) -> pd.DataFrame:
        return frame.sort_values("revenue", ascending=False, ignore_index=True).head(100)

    def materialised() -> pd.DataFrame:
        filtered = stage_filter(fact)
        frag._write_one(filtered, root / "s1.parquet")
        reloaded = pd.read_parquet(root / "s1.parquet")
        aggregated = stage_aggregate(reloaded)
        frag._write_one(aggregated, root / "s2.parquet")
        return stage_rank(pd.read_parquet(root / "s2.parquet"))

    def pipelined() -> pd.DataFrame:
        return stage_rank(stage_aggregate(stage_filter(fact)))

    mat_times, mat_out = time_callable(materialised, trials)
    pipe_times, pipe_out = time_callable(pipelined, trials)
    written = sum(parquet.stat().st_size for parquet in root.glob("*.parquet"))

    mat_s, pipe_s = median(mat_times), median(pipe_times)
    identical = mat_out.reset_index(drop=True).equals(pipe_out.reset_index(drop=True))
    return pd.DataFrame(
        [
            {
                "approach": "materialise_each_stage",
                "seconds": round(mat_s, 5),
                "intermediate_bytes": written,
                "overhead_pct": round(100 * (mat_s / pipe_s - 1), 1) if pipe_s else 0.0,
                "restartable": True,
                "answers_identical": identical,
            },
            {
                "approach": "pipeline_in_memory",
                "seconds": round(pipe_s, 5),
                "intermediate_bytes": 0,
                "overhead_pct": 0.0,
                "restartable": False,
                "answers_identical": identical,
            },
        ]
    )


def fit_scaling_exponent(scaling: pd.DataFrame, strategy: str) -> float | None:
    """Estimate the exponent ``k`` in ``time ~ rows**k`` by a log-log fit.

    A value near 1.0 means the strategy scales linearly with input size; a
    value meaningfully above 1.0 means its cost grows faster than the data,
    which is the thing worth knowing before the dataset doubles.

    Returns:
        The fitted exponent, or None with fewer than two points.
    """
    subset = scaling[scaling["strategy"] == strategy]
    subset = subset[(subset["seconds"] > 0) & (subset["input_rows"] > 0)]
    if len(subset) < 2:
        return None
    slope = np.polyfit(np.log(subset["input_rows"]), np.log(subset["seconds"]), 1)[0]
    return round(float(slope), 3)
