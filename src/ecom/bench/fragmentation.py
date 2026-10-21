"""Horizontal fragmentation, vertical fragmentation and hash sharding.

The question this module answers is not "is partitioning good" but "for which
query, and at what cost". Each layout is written to disk once and then queried
four ways, so the same physical design can be shown to help one access pattern
and hurt another.

Layouts
-------
``monolithic``
    One Parquet file. The reference design, and what the pipeline writes today.
``horizontal``
    One file per ``order_month``, the classic range fragmentation. A predicate
    on the partition key is answered by opening a subset of files, so the
    pruning happens in the filesystem before any decompression. A predicate on
    any other column still touches every file, and now pays per-file overhead
    nineteen times over.
``vertical``
    Columns split into a frequently-read fragment and a rarely-read one, joined
    back on a surrogate row key. This is the fragmentation that classical
    distributed-database theory recommends, and on a column store it is largely
    redundant: Parquet already stores each column separately, so a projection
    is pruned without any help from the physical layout.
``sharded``
    ``hash(seller_id) % n`` files. Unlike range fragmentation this spreads rows
    evenly regardless of skew, which is what makes it the usual choice for
    distributing load; the cost is that no range predicate can be pruned.

Bytes read
----------
Every query reports the bytes it had to open, computed by summing the sizes of
exactly those files the reader touches. That number is auditable from the
filesystem and, unlike wall time, is unaffected by the page cache -- which
matters because these benchmarks necessarily run warm-cache.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

logger = logging.getLogger(__name__)

HOT_COLUMNS = ("row_id", "order_id", "product_id", "seller_id", "quantity", "line_revenue")
"""Columns the analytical queries actually touch, measured from the use cases:
revenue aggregation needs the money and the keys and nothing else."""

COLD_COLUMNS = (
    "row_id",
    "unit_price",
    "line_freight",
    "shipping_limit_date",
    "order_purchase_timestamp",
    "customer_id",
)
"""Columns kept for lineage and shipping analysis but absent from the hot path."""

SHARD_COUNTS = (4, 16, 64, 256, 1024, 4096)
"""Powers of four from coarse to absurd. The range is deliberately pushed past
the useful point: at 4,096 shards a 400k-row table holds about a hundred rows
per file, so each Parquet footer is a large fraction of its own file. Stopping
at 256 showed speedup still climbing and would have left the question of where
it turns unanswered."""

PARQUET_COMPRESSION = "snappy"
"""Matches what the pipeline writes, so storage overhead figures are comparable
to the real processed layer rather than to an idealised uncompressed one."""


@dataclass
class LayoutStats:
    """Physical cost of one storage layout.

    Attributes:
        layout: Layout name as it appears in the report.
        file_count: Number of Parquet files written.
        total_bytes: Sum of all file sizes, the storage the layout occupies.
        overhead_pct: Percentage more storage than the monolithic layout, which
            is where per-file footers and lost cross-row compression show up.
    """

    layout: str
    file_count: int
    total_bytes: int
    overhead_pct: float = 0.0


def build_fact_table(
    order_lines: pd.DataFrame,
    orders: pd.DataFrame,
    window_start: pd.Timestamp,
    window_end: pd.Timestamp,
) -> pd.DataFrame:
    """Join lines to orders and keep delivered rows inside the window.

    This is the ``fct_orders`` grain the warehouse design calls for: one row per
    (order, product, seller) with its month attached, which is the column the
    horizontal layout fragments on.

    Args:
        order_lines: Processed order lines.
        orders: Processed orders, carrying the purchase timestamp and flag.
        window_start: First day of the observation window, inclusive.
        window_end: Last day of the observation window, inclusive.

    Returns:
        The fact table with a ``row_id`` surrogate key and ``order_month``.
    """
    fact = order_lines.merge(
        orders[["order_id", "order_purchase_timestamp", "is_delivered", "customer_id"]],
        on="order_id",
        how="inner",
    )
    fact = fact[fact["is_delivered"].fillna(False)].drop(columns=["is_delivered"])
    in_window = fact["order_purchase_timestamp"].between(
        window_start, window_end + pd.Timedelta(days=1), inclusive="left"
    )
    fact = fact[in_window].reset_index(drop=True)
    fact["order_month"] = fact["order_purchase_timestamp"].dt.strftime("%Y-%m")
    # A surrogate key is what lets the vertical fragments be rejoined. Without
    # it the two fragments would have to carry the full composite key, which
    # would inflate the "cold" fragment with the very columns we moved out.
    fact["row_id"] = np.arange(len(fact), dtype="int64")
    return fact


def replicate_fact(fact: pd.DataFrame, factor: int) -> pd.DataFrame:
    """Return the fact table repeated ``factor`` times with distinct keys.

    Scaling the input is the only way to answer "does this optimisation matter",
    because at the real 99k rows every strategy finishes in well under a second
    and fixed overheads dominate. Keys are suffixed per copy so that cardinality
    grows with volume; repeating rows verbatim would instead make every group-by
    artificially cheaper as the data grew.

    Args:
        fact: Output of :func:`build_fact_table`.
        factor: Number of copies. 1 returns an unmodified copy.

    Returns:
        A frame with ``factor * len(fact)`` rows and a fresh ``row_id``.
    """
    if factor == 1:
        return fact.copy()

    copies = []
    for index in range(factor):
        copy = fact.copy()
        if index:
            suffix = f"_{index}"
            for column in ("order_id", "product_id", "seller_id"):
                copy[column] = copy[column].astype("string") + suffix
        copies.append(copy)
    out = pd.concat(copies, ignore_index=True)
    out["row_id"] = np.arange(len(out), dtype="int64")
    return out


def _write_one(frame: pd.DataFrame, path: Path) -> None:
    """Write a single Parquet file, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.Table.from_pandas(frame, preserve_index=False), path, compression=PARQUET_COMPRESSION
    )


def _layout_stats(layout: str, root: Path) -> LayoutStats:
    """Count files and bytes under ``root``."""
    files = sorted(root.rglob("*.parquet"))
    return LayoutStats(
        layout=layout,
        file_count=len(files),
        total_bytes=sum(parquet.stat().st_size for parquet in files),
    )


def write_monolithic(fact: pd.DataFrame, root: Path) -> LayoutStats:
    """Write the whole fact table as one Parquet file."""
    shutil.rmtree(root, ignore_errors=True)
    _write_one(fact, root / "fact.parquet")
    return _layout_stats("monolithic", root)


def write_horizontal(fact: pd.DataFrame, root: Path, key: str = "order_month") -> LayoutStats:
    """Write one Parquet file per distinct value of ``key``, Hive style.

    The partition value is encoded in the directory name **and kept in the file
    body**. A production Hive layout would drop it, since it is constant within
    the file and recoverable from the path, and that saves real space.

    It is retained here because this layout exists to answer one question --
    does pruning files help, and at what selectivity -- and dropping the column
    would confound that with a second, unrelated saving. Measured at 4x scale,
    a layout that drops the key reads 20% fewer bytes even on a full scan,
    which made the partitioned layout look 1.79x faster at 100% selectivity
    where the honest answer is that it is slower. Keeping the column means
    every layout reads identical columns, so the only variable left is how many
    files the query opens.

    Keeping the column turns out to cost almost nothing, and measuring it
    overturned the assumption that motivated dropping it. This layout stores
    **20% less** than the monolithic file even while carrying the redundant
    column, because partitioning clusters the data: within one file
    ``order_month`` is constant and dictionary-encodes to nearly nothing, and
    the time-ordering makes the remaining columns compress better too. The
    layout is nonetheless slower on a full scan, which is the useful lesson --
    bytes on disk are not the binding constraint here, per-file overhead is.
    """
    shutil.rmtree(root, ignore_errors=True)
    for value, group in fact.groupby(key, sort=True):
        _write_one(group, root / f"{key}={value}" / "part.parquet")
    return _layout_stats("horizontal", root)


def write_vertical(fact: pd.DataFrame, root: Path) -> LayoutStats:
    """Split the columns into a hot and a cold fragment sharing ``row_id``."""
    shutil.rmtree(root, ignore_errors=True)
    _write_one(fact[list(HOT_COLUMNS)], root / "hot.parquet")
    _write_one(fact[list(COLD_COLUMNS)], root / "cold.parquet")
    return _layout_stats("vertical", root)


def _shard_of(values: pd.Series, shards: int) -> np.ndarray:
    """Map each key to a shard with a stable hash.

    Python's built-in ``hash`` is salted per process, so a layout written in one
    run could not be queried in the next. Blake2b with a short digest is stable
    across processes and fast enough to shard a million keys.
    """
    return np.array(
        [
            int.from_bytes(hashlib.blake2b(str(key_value).encode(), digest_size=8).digest(), "big")
            % shards
            for key_value in values
        ],
        dtype="int64",
    )


def write_sharded(
    fact: pd.DataFrame, root: Path, shards: int, key: str = "seller_id"
) -> LayoutStats:
    """Write ``shards`` files, assigning rows by a stable hash of ``key``."""
    shutil.rmtree(root, ignore_errors=True)
    assignment = _shard_of(fact[key], shards)
    for shard in range(shards):
        group = fact[assignment == shard]
        if len(group):
            _write_one(group, root / f"shard={shard:04d}" / "part.parquet")
    return _layout_stats(f"sharded_{shards}", root)


# ------------------------------------------------------------------- queries
# Each query returns (answer, bytes_read) so the report can show both the time
# and the I/O that produced it. The answer is what the harness compares across
# layouts: a layout that is fast and wrong must not be reported as a win.


@dataclass
class QueryOutcome:
    """Answer and bytes read for one query against one layout."""

    answer: float
    bytes_read: int


def q_revenue_for_months(root: Path, months: list[str], layout: str) -> QueryOutcome:
    """Total revenue for a set of months -- a predicate on the partition key.

    This is the access pattern horizontal fragmentation exists to serve. On the
    partitioned layout only the matching directories are opened; on every other
    layout the whole table is read and the predicate applied afterwards.
    """
    wanted = set(months)
    if layout == "horizontal":
        files = [
            candidate
            for candidate in sorted(root.rglob("*.parquet"))
            if candidate.parent.name.split("=", 1)[1] in wanted
        ]
        if not files:
            return QueryOutcome(0.0, 0)
        # The same two columns the monolithic branch reads, and the same
        # predicate over them. Every file opened here is known to match, so the
        # filter is redundant -- but leaving it in keeps the work per row
        # identical across layouts, so the measurement isolates pruning alone.
        total = 0.0
        for parquet in files:
            frame = pq.read_table(parquet, columns=["order_month", "line_revenue"]).to_pandas()
            total += float(frame.loc[frame["order_month"].isin(wanted), "line_revenue"].sum())
        return QueryOutcome(total, sum(parquet.stat().st_size for parquet in files))

    files = sorted(root.rglob("*.parquet"))
    if layout == "vertical":
        # order_month lives in neither fragment's hot path by itself, so the
        # hot fragment alone cannot answer this query; both must be read and
        # rejoined. This is the cost vertical fragmentation imposes when a
        # query spans the split.
        hot = pq.read_table(root / "hot.parquet", columns=["row_id", "line_revenue"]).to_pandas()
        cold = pq.read_table(
            root / "cold.parquet", columns=["row_id", "order_purchase_timestamp"]
        ).to_pandas()
        merged = hot.merge(cold, on="row_id")
        month = merged["order_purchase_timestamp"].dt.strftime("%Y-%m")
        total = float(merged.loc[month.isin(wanted), "line_revenue"].sum())
        return QueryOutcome(total, sum(parquet.stat().st_size for parquet in files))

    total = 0.0
    for parquet in files:
        frame = pq.read_table(parquet, columns=["order_month", "line_revenue"]).to_pandas()
        total += float(frame.loc[frame["order_month"].isin(wanted), "line_revenue"].sum())
    return QueryOutcome(total, sum(parquet.stat().st_size for parquet in files))


def q_revenue_for_seller(root: Path, seller_id: str, layout: str, shards: int = 0) -> QueryOutcome:
    """Total revenue for one seller -- a predicate on a non-partition column.

    Horizontal fragmentation by month cannot prune anything here, so it reads
    every file and pays nineteen file-open costs for one logical scan. Sharding
    on ``seller_id`` prunes to a single file, which is exactly the trade the two
    layouts make against each other.
    """
    if layout.startswith("sharded") and shards:
        target = int(_shard_of(pd.Series([seller_id]), shards)[0])
        path = root / f"shard={target:04d}" / "part.parquet"
        if not path.exists():
            return QueryOutcome(0.0, 0)
        frame = pq.read_table(path, columns=["seller_id", "line_revenue"]).to_pandas()
        total = float(frame.loc[frame["seller_id"] == seller_id, "line_revenue"].sum())
        return QueryOutcome(total, path.stat().st_size)

    if layout == "vertical":
        hot = pq.read_table(root / "hot.parquet", columns=["seller_id", "line_revenue"]).to_pandas()
        total = float(hot.loc[hot["seller_id"] == seller_id, "line_revenue"].sum())
        return QueryOutcome(total, (root / "hot.parquet").stat().st_size)

    files = sorted(root.rglob("*.parquet"))
    total = 0.0
    for parquet in files:
        frame = pq.read_table(parquet, columns=["seller_id", "line_revenue"]).to_pandas()
        total += float(frame.loc[frame["seller_id"] == seller_id, "line_revenue"].sum())
    return QueryOutcome(total, sum(parquet.stat().st_size for parquet in files))


def q_total_revenue(root: Path, layout: str) -> QueryOutcome:
    """Grand total revenue -- a full scan of exactly one column.

    No layout can prune rows for this query, so it isolates the per-file
    overhead of fragmentation and the benefit of a narrow hot fragment.
    """
    if layout == "vertical":
        path = root / "hot.parquet"
        column = pq.read_table(path, columns=["line_revenue"])["line_revenue"]
        return QueryOutcome(float(column.to_pandas().sum()), path.stat().st_size)

    files = sorted(root.rglob("*.parquet"))
    total = sum(
        float(pq.read_table(parquet, columns=["line_revenue"])["line_revenue"].to_pandas().sum())
        for parquet in files
    )
    return QueryOutcome(total, sum(parquet.stat().st_size for parquet in files))
