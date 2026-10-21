"""Alternative implementations of the pipeline's expensive operations.

Each workload is one operation the pipeline really performs, implemented several
ways so the strategies can be compared on identical input. Every strategy in a
group must return the same answer; :mod:`ecom.bench.harness` checks that and
records any disagreement instead of trusting it.

The strategies are chosen to exercise named concepts from the course rather than
to be an arbitrary collection of tricks:

* **Join methods** — the co-occurrence self-join is written as a nested-loop
  join, a hash join, a sort-merge join, a declarative SQL join handed to a cost
  based optimiser, and a sparse linear-algebra product. These are the lecture's
  J1--J4 plus the formulation a column store would actually use.
* **Projection and predicate pushdown** — reading two columns of a Parquet file
  versus reading all fourteen and discarding twelve.
* **Vectorisation** — replacing per-element Python calls with Arrow kernels that
  run over a whole column in native code.
* **Correctness versus speed** — the row counter includes a strategy that is
  the fastest available and also wrong, because the report needs to show that
  the study checked rather than assumed.

Every function here is pure: it takes frames or paths and returns a value, and
performs no writes (docs/CODING_STANDARDS.md section 2).
"""

from __future__ import annotations

import csv
import itertools
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pa_csv
import pyarrow.parquet as pq
import scipy.sparse as sp

PAIR_COLUMNS = ["product_a", "product_b", "order_count"]
"""Output contract shared by every co-occurrence strategy."""

OLIST_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
"""Every Olist timestamp column uses this exact layout, so the parser never has
to infer it. Inference costs a Python-level scan of the column to find a format
that works, then re-parses; supplying the format skips the search entirely."""


# --------------------------------------------------------------- co-occurrence
# All five take the deduplicated (order_id, product_id) frame and return one row
# per unordered pair with the number of distinct orders containing both.


def cooccur_nested_loop(order_products: pd.DataFrame) -> pd.DataFrame:
    """Baseline: iterate baskets in Python and count pairs with a dict.

    This is the shape of a classic nested-loop join (the lecture's J1): for each
    basket, every product is paired with every later product. Cost is
    ``sum(k choose 2)`` over baskets, all of it in interpreted code, so it pays
    roughly a microsecond of overhead per pair regardless of how few pairs there
    are.
    """
    sizes = order_products.groupby("order_id")["product_id"].size()
    multi = sizes[sizes >= 2].index
    baskets = order_products[order_products["order_id"].isin(multi)].groupby("order_id")[
        "product_id"
    ]

    counter: Counter[tuple[str, str]] = Counter()
    for _, products in baskets:
        for pair in itertools.combinations(sorted(set(products)), 2):
            counter[pair] += 1

    return pd.DataFrame(
        [(first, second, count) for (first, second), count in counter.items()],
        columns=PAIR_COLUMNS,
    )


def cooccur_hash_join(order_products: pd.DataFrame) -> pd.DataFrame:
    """Self-join the frame on ``order_id`` and aggregate, the J4 hash join.

    pandas hashes the smaller side and probes with the larger, producing every
    ordered pair within a basket; keeping ``product_a < product_b`` discards the
    mirror half and the self-pairs in one vectorised comparison. The grouping
    that follows is also vectorised, so no pair is ever a Python object.
    """
    pairs = order_products.merge(order_products, on="order_id", suffixes=("_a", "_b"))
    pairs = pairs[pairs["product_id_a"] < pairs["product_id_b"]]
    out = (
        pairs.groupby(["product_id_a", "product_id_b"], sort=False)
        .size()
        .reset_index(name="order_count")
    )
    return out.rename(columns={"product_id_a": "product_a", "product_id_b": "product_b"})


def cooccur_sort_merge(order_products: pd.DataFrame) -> pd.DataFrame:
    """Sort once, then emit pairs per contiguous basket with numpy, the J3 shape.

    Sorting by ``order_id`` makes each basket a contiguous block, so the pair
    generation needs no hashing and no grouping object -- just slice boundaries
    found with ``np.unique``. Pair indices come from ``np.triu_indices``, which
    builds the combination structure in native code. The final count is a single
    ``np.unique`` over the pair array.
    """
    # Work on integer surrogate keys, not the 32-character product strings.
    # A real sort-merge join sorts fixed-width keys for exactly this reason:
    # comparing and hashing 8-byte integers is far cheaper than comparing
    # variable-length text, and numpy cannot sort or dedupe object arrays at all.
    product_codes, product_labels = pd.factorize(order_products["product_id"], sort=True)
    frame = pd.DataFrame(
        {"order_id": order_products["order_id"].to_numpy(), "code": product_codes}
    ).sort_values(["order_id", "code"], kind="stable")

    orders = frame["order_id"].to_numpy()
    codes = frame["code"].to_numpy()
    starts = np.flatnonzero(np.r_[True, orders[1:] != orders[:-1]])
    bounds = np.r_[starts, len(orders)]

    left_parts, right_parts = [], []
    for begin, end in itertools.pairwise(bounds):
        size = end - begin
        if size < 2:
            continue
        rows, cols = np.triu_indices(size, k=1)
        block = codes[begin:end]
        left_parts.append(block[rows])
        right_parts.append(block[cols])

    if not left_parts:
        return pd.DataFrame(columns=PAIR_COLUMNS)

    left = np.concatenate(left_parts)
    right = np.concatenate(right_parts)
    # Codes within a basket were sorted, so left < right already holds. Packing
    # the two codes into one 64-bit key lets a single sort do the counting.
    packed = (left.astype(np.int64) << np.int64(32)) | right.astype(np.int64)
    uniq, counts = np.unique(packed, return_counts=True)
    high = (uniq >> np.int64(32)).astype(np.int64)
    low = (uniq & np.int64(0xFFFFFFFF)).astype(np.int64)
    return pd.DataFrame(
        {
            "product_a": product_labels[high],
            "product_b": product_labels[low],
            "order_count": counts,
        }
    )


def cooccur_sparse_matrix(order_products: pd.DataFrame) -> pd.DataFrame:
    """Count pairs as the sparse product ``B.T @ B`` over a basket matrix.

    ``B`` is a boolean orders-by-products incidence matrix, so entry ``(i, j)``
    of ``B.T @ B`` is the number of orders containing both product ``i`` and
    product ``j``. Taking the strict upper triangle drops the diagonal (a
    product's own frequency) and the mirrored half.

    This is how a vectorised engine would express the problem, and it never
    materialises the intermediate pair list that the join strategies build --
    the counting happens inside the sparse multiply.
    """
    order_codes, _ = pd.factorize(order_products["order_id"], sort=False)
    # sort=True matters: the strict upper triangle keeps pairs with code_a <
    # code_b, and only a sorted factorisation makes that the same thing as
    # product_a < product_b. With appearance-order codes the pair set is still
    # correct but individual rows come out with the two products swapped.
    product_codes, product_labels = pd.factorize(order_products["product_id"], sort=True)

    incidence = sp.csr_matrix(
        (np.ones(len(order_codes), dtype=np.int32), (order_codes, product_codes)),
        shape=(order_codes.max() + 1, len(product_labels)),
    )
    counts = sp.triu(incidence.T @ incidence, k=1).tocoo()

    return pd.DataFrame(
        {
            "product_a": product_labels[counts.row],
            "product_b": product_labels[counts.col],
            "order_count": counts.data.astype("int64"),
        }
    )


def cooccur_duckdb(order_products: pd.DataFrame) -> pd.DataFrame:
    """Hand the self-join to DuckDB as SQL and let its optimiser plan it.

    The point of this strategy is not the SQL dialect but the division of
    labour: the query states *what* is wanted and a cost-based optimiser picks
    the physical join, the parallelism and the aggregation. DuckDB is a
    vectorised column-at-a-time engine, so it executes the same logical plan as
    the hash-join strategy without pandas' intermediate frames.
    """
    import duckdb

    connection = duckdb.connect(":memory:")
    try:
        connection.register("op", order_products)
        return connection.execute("""
            SELECT a.product_id AS product_a,
                   b.product_id AS product_b,
                   COUNT(*)     AS order_count
            FROM op AS a
            JOIN op AS b
              ON a.order_id = b.order_id
             AND a.product_id < b.product_id
            GROUP BY 1, 2
            """).fetch_df()
    finally:
        connection.close()


COOCCURRENCE_STRATEGIES = (
    ("nested_loop_python", cooccur_nested_loop),
    ("hash_join_pandas", cooccur_hash_join),
    ("sort_merge_numpy", cooccur_sort_merge),
    ("sparse_matrix_scipy", cooccur_sparse_matrix),
    ("sql_duckdb", cooccur_duckdb),
)
"""Baseline first; the harness quotes every speedup against it."""


# ------------------------------------------------------------- CSV row counting


def count_rows_csv_reader(path: Path) -> int:
    """Baseline: parse every row with :mod:`csv` and count what comes out.

    Correct on every Olist file because the parser understands quoting, but it
    builds a Python list per row only to throw it away.
    """
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return max(sum(1 for _ in csv.reader(handle)) - 1, 0)


def count_rows_arrow(path: Path) -> int:
    """Count with Arrow's multi-threaded CSV reader.

    Arrow parses in native code and only materialises the columns it is asked
    for, so reading a single narrow column is enough to learn the row count.
    It still honours quoting, so the answer stays correct.
    """
    table = pa_csv.read_csv(
        path,
        read_options=pa_csv.ReadOptions(use_threads=True),
        convert_options=pa_csv.ConvertOptions(include_columns=None),
    )
    return table.num_rows


def count_rows_newlines(path: Path) -> int:
    """Count ``\\n`` bytes in fixed-size chunks -- fast and, on some files, wrong.

    This is kept in the study on purpose. It is the quickest way to count a
    file and it gives the right answer for most Olist tables, but review
    comments contain newlines inside quoted fields, so the physical line count
    exceeds the logical row count. Including it demonstrates that the benchmark
    verifies answers rather than assuming the fastest strategy is usable.
    """
    newlines = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            newlines += chunk.count(b"\n")
    return max(newlines - 1, 0)


ROW_COUNT_STRATEGIES = (
    ("csv_reader_python", count_rows_csv_reader),
    ("arrow_csv_native", count_rows_arrow),
    ("newline_bytes_unsafe", count_rows_newlines),
)


# -------------------------------------------------- CSV read + whitespace trim
# These strategies take a path rather than a frame, because the measurement
# that first motivated this workload attributed the cost to the trim function
# when it actually belongs to the dtype the CSV was read into. Splitting the
# two apart hid that; measuring read-then-trim as one stage exposes it.


def _string_columns(df: pd.DataFrame) -> list[str]:
    """Return the columns holding text, whatever string dtype backs them."""
    return [
        column
        for column in df.columns
        if df[column].dtype == "object" or str(df[column].dtype).startswith("string")
    ]


def trim_python_strip(df: pd.DataFrame) -> pd.DataFrame:
    """Strip every string column with pandas' ``.str.strip()``.

    Shared by the read-and-trim strategies below so that only the dtype they
    were read into differs. On numpy-object and pandas-``string`` storage this
    dispatches per element; on Arrow-backed storage the identical call runs as
    a native kernel over the whole column, which is the entire point of the
    comparison.
    """
    out = df.copy()
    for column in _string_columns(out):
        out[column] = out[column].str.strip()
    return out


def read_object_then_trim(path: Path) -> pd.DataFrame:
    """Read with pandas' default object dtype, then trim.

    The slowest option and the one the pipeline deliberately avoids: object
    columns hold a pointer to a separate Python string per cell.
    """
    return trim_python_strip(pd.read_csv(path, dtype=object, encoding="utf-8-sig"))


def read_string_then_trim(path: Path) -> pd.DataFrame:
    """Read into pandas' ``string`` dtype, then trim -- what the pipeline does.

    This is the baseline. The dtype is nullable and semantically correct, but
    it is still backed by Python string objects, so the trim pays a per-cell
    interpreter cost.
    """
    return trim_python_strip(pd.read_csv(path, dtype="string", encoding="utf-8-sig"))


def read_arrow_then_trim(path: Path) -> pd.DataFrame:
    """Read into Arrow-backed strings, then trim with the same call.

    ``string[pyarrow]`` stores a column as one contiguous buffer of UTF-8 bytes
    plus offsets, so ``.str.strip()`` becomes a single native kernel pass with
    no Python objects created. The trim code is unchanged -- only the storage
    the data landed in differs, which is why this result belongs to the read
    path and not to the transform.
    """
    return trim_python_strip(pd.read_csv(path, dtype="string[pyarrow]", encoding="utf-8-sig"))


def read_arrow_then_detect_skip(path: Path) -> pd.DataFrame:
    """Read into Arrow-backed strings and trim only the columns that need it.

    Measured on the real files, no Olist column carries leading or trailing
    whitespace, so every trim is overhead. One vectorised comparison per column
    establishes that and skips the work, while leaving the documented rule in
    force for any future file that does arrive padded.
    """
    df = pd.read_csv(path, dtype="string[pyarrow]", encoding="utf-8-sig")
    out = df.copy()
    for column in _string_columns(out):
        values = pa.array(out[column])
        if pc.any(pc.not_equal(pc.utf8_trim_whitespace(values), values)).as_py():
            out[column] = out[column].str.strip()
    return out


def read_arrow_engine_then_trim(path: Path) -> pd.DataFrame:
    """Parse the CSV with Arrow's reader, not pandas', then trim.

    The strategies above change what the parsed values are stored *in*, which
    turns out to optimise the smaller half of the stage: the trim is roughly
    90 ms of a 350 ms read-and-trim, so no dtype choice can win more than about
    1.4x. This strategy replaces the parser itself. Arrow's CSV reader is
    multi-threaded and writes directly into columnar buffers, so it attacks the
    part of the stage that actually dominates.

    This is Amdahl's law applied to a data pipeline: the ceiling on optimising
    any component is set by that component's share of the total.
    """
    table = pa_csv.read_csv(
        path,
        read_options=pa_csv.ReadOptions(use_threads=True),
        convert_options=pa_csv.ConvertOptions(
            # Every column is read as text, matching the pipeline's rule that
            # type coercion is one explicit later step rather than inference.
            column_types=dict.fromkeys(_csv_header(path), pa.string()),
            # Arrow defaults strings_can_be_null to False, which makes an empty
            # CSV field the empty string rather than null. On this dataset that
            # silently turns 2,965 missing delivery dates into "", so the
            # no-nulls quality gate would pass on data that is in fact missing.
            # The benchmark's correctness check caught exactly this, which is
            # why the check exists: the fastest reader is only usable once its
            # null semantics are made to match the baseline's.
            strings_can_be_null=True,
        ),
    )
    frame = table.to_pandas(types_mapper=pd.ArrowDtype)
    return trim_python_strip(frame)


def _csv_header(path: Path) -> list[str]:
    """Return a CSV's column names, read from the header row alone."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return next(csv.reader(handle))


READ_TRIM_STRATEGIES = (
    ("read_string_then_trim", read_string_then_trim),
    ("read_object_then_trim", read_object_then_trim),
    ("read_arrow_then_trim", read_arrow_then_trim),
    ("read_arrow_detect_skip", read_arrow_then_detect_skip),
    ("arrow_parser_then_trim", read_arrow_engine_then_trim),
)
"""Baseline first: ``read_string_then_trim`` is the pipeline's current read path."""


# --------------------------------------------------------------- timestamp parsing


def parse_timestamps_inferred(series: pd.Series) -> pd.Series:
    """Baseline: let pandas work out the timestamp layout for itself."""
    return pd.to_datetime(series, errors="coerce")


def parse_timestamps_with_format(series: pd.Series) -> pd.Series:
    """Parse with the known layout supplied, skipping format inference."""
    return pd.to_datetime(series, format=OLIST_TIMESTAMP_FORMAT, errors="coerce")


def parse_timestamps_arrow(series: pd.Series) -> pd.Series:
    """Parse in Arrow, then hand the result back to pandas.

    ``strptime`` is an Arrow kernel, so parsing runs column-at-a-time in native
    code. Unparseable values become null rather than raising, matching the
    ``errors="coerce"`` contract the pipeline relies on.
    """
    parsed = pc.strptime(
        pa.array(series), format=OLIST_TIMESTAMP_FORMAT, unit="ns", error_is_null=True
    )
    return parsed.to_pandas()


TIMESTAMP_STRATEGIES = (
    ("pandas_inferred", parse_timestamps_inferred),
    ("pandas_explicit_format", parse_timestamps_with_format),
    ("arrow_strptime", parse_timestamps_arrow),
)


# ---------------------------------------------------- projection pushdown (read)


def read_all_then_select(path: Path, columns: list[str]) -> pd.DataFrame:
    """Baseline: read every column from Parquet, then keep the wanted ones."""
    return pq.read_table(path).to_pandas()[columns]


def read_with_projection(path: Path, columns: list[str]) -> pd.DataFrame:
    """Ask Parquet for only the needed columns.

    Parquet stores each column in its own contiguous chunk, so naming the
    columns means the other chunks are never decompressed or even read off disk.
    This is projection pushdown, and it is the reason the project stores Parquet
    rather than CSV -- a CSV reader must scan every byte to find the commas.
    """
    return pq.read_table(path, columns=columns).to_pandas()


PROJECTION_STRATEGIES = (
    ("read_all_columns", read_all_then_select),
    ("projection_pushdown", read_with_projection),
)
