"""Checks that the dbt warehouse agrees with the pipeline that feeds it.

The warehouse and the pandas pipeline compute co-occurrence independently, one
in SQL and one in pandas, so pair-for-pair agreement is evidence that both are
right rather than a tautology. Each function is pure and returns a
:class:`CheckResult`; reading DuckDB and storage happens in
``ecom.orchestration.steps``.
"""

from __future__ import annotations

import pandas as pd

from ecom.quality.checks import CheckResult

PAIR_COLUMNS: tuple[str, ...] = ("product_a", "product_b", "order_count")

SUM_TOLERANCE = 0.011
"""Half a centavo either side of a cent: DuckDB sums DECIMAL, pandas sums float."""


def check_row_parity(name: str, *, warehouse_rows: int, pipeline_rows: int) -> CheckResult:
    """The warehouse model holds exactly as many rows as its pipeline table."""
    drift = warehouse_rows - pipeline_rows
    return CheckResult(
        f"parity:{name}",
        drift == 0,
        "error",
        f"warehouse {warehouse_rows:,} vs pipeline {pipeline_rows:,} rows",
        abs(drift),
    )


def check_sum_parity(name: str, *, warehouse_sum: float, pipeline_sum: float) -> CheckResult:
    """A money column totals the same on both sides, so no join multiplied rows."""
    gap = abs(warehouse_sum - pipeline_sum)
    return CheckResult(
        f"sum:{name}",
        gap < SUM_TOLERANCE,
        "error",
        f"warehouse {warehouse_sum:,.2f} vs pipeline {pipeline_sum:,.2f}",
    )


def check_pairs_identical(warehouse: pd.DataFrame, pipeline: pd.DataFrame) -> CheckResult:
    """Every co-occurrence pair and weight matches, compared as sets of rows."""
    columns = list(PAIR_COLUMNS)
    left = warehouse[columns].astype({"product_a": str, "product_b": str, "order_count": "int64"})
    right = pipeline[columns].astype({"product_a": str, "product_b": str, "order_count": "int64"})
    merged = left.merge(right, how="outer", on=columns, indicator=True)
    only_warehouse = int((merged["_merge"] == "left_only").sum())
    only_pipeline = int((merged["_merge"] == "right_only").sum())
    return CheckResult(
        "identical:product_cooccurrence",
        only_warehouse == 0 and only_pipeline == 0,
        "error",
        f"{only_warehouse} rows only in the warehouse, {only_pipeline} only in the pipeline",
        only_warehouse + only_pipeline,
    )
