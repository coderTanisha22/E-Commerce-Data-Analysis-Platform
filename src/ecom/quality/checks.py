"""Quality checks that gate the pipeline.

A check returns a :class:`CheckResult`; :func:`run_gate` decides what to do with
a batch of them. Anything with ``severity="error"`` that fails raises, because a
pipeline that warns and continues produces a dashboard nobody can trust
(docs/CODING_STANDARDS.md section 7).

The ``warn`` severity is reserved for documented properties of Olist itself -
the 775 orders with no item rows, for instance - so a known quirk never masks a
real regression.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

import pandas as pd

logger = logging.getLogger(__name__)

Severity = Literal["error", "warn"]


class DataQualityError(RuntimeError):
    """Raised when one or more error-severity checks fail."""


@dataclass(frozen=True)
class CheckResult:
    """Outcome of a single check.

    Attributes:
        name: Short identifier, e.g. ``unique:orders.order_id``.
        passed: Whether the expectation held.
        severity: ``error`` raises on failure; ``warn`` only logs.
        detail: Human-readable explanation, always populated on failure.
        offending_rows: How many rows violated the expectation.
    """

    name: str
    passed: bool
    severity: Severity
    detail: str
    offending_rows: int = 0


def check_unique_key(
    df: pd.DataFrame, table: str, key: tuple[str, ...], severity: Severity = "error"
) -> CheckResult:
    """Assert the declared key uniquely identifies every row."""
    name = f"unique:{table}.{'+'.join(key)}"
    missing = [c for c in key if c not in df.columns]
    if missing:
        return CheckResult(name, False, severity, f"key columns absent: {missing}")

    duplicates = int(df.duplicated(subset=list(key)).sum())
    return CheckResult(
        name,
        duplicates == 0,
        severity,
        (
            f"{duplicates} duplicate rows on {key}"
            if duplicates
            else f"{len(df)} rows unique on {key}"
        ),
        duplicates,
    )


def check_no_nulls(
    df: pd.DataFrame, table: str, columns: tuple[str, ...], severity: Severity = "error"
) -> CheckResult:
    """Assert the given columns contain no nulls."""
    name = f"not_null:{table}.{'+'.join(columns)}"
    present = [c for c in columns if c in df.columns]
    if len(present) != len(columns):
        absent = sorted(set(columns) - set(present))
        return CheckResult(name, False, severity, f"columns absent: {absent}")

    nulls = int(df[present].isna().any(axis=1).sum())
    return CheckResult(
        name,
        nulls == 0,
        severity,
        f"{nulls} rows have a null in {present}" if nulls else f"no nulls in {present}",
        nulls,
    )


def check_foreign_key(
    child: pd.DataFrame,
    parent: pd.DataFrame,
    child_column: str,
    parent_column: str,
    label: str,
    severity: Severity = "error",
) -> CheckResult:
    """Assert every child value exists in the parent column."""
    name = f"foreign_key:{label}"
    if child_column not in child.columns or parent_column not in parent.columns:
        return CheckResult(name, False, severity, "join columns absent")

    orphans = int((~child[child_column].isin(set(parent[parent_column]))).sum())
    return CheckResult(
        name,
        orphans == 0,
        severity,
        f"{orphans} orphan rows on {child_column}" if orphans else f"no orphans on {child_column}",
        orphans,
    )


def check_row_count(
    df: pd.DataFrame, table: str, minimum: int, severity: Severity = "error"
) -> CheckResult:
    """Assert a table is not unexpectedly empty or truncated."""
    name = f"row_count:{table}"
    ok = len(df) >= minimum
    return CheckResult(
        name, ok, severity, f"{len(df)} rows (minimum {minimum})", 0 if ok else minimum - len(df)
    )


def run_gate(results: list[CheckResult], *, stage: str) -> list[CheckResult]:
    """Log every result and raise if any error-severity check failed.

    Args:
        results: Checks to evaluate.
        stage: Pipeline stage name, used in the log and exception message.

    Returns:
        The results, unchanged, so callers can persist them in a report.

    Raises:
        DataQualityError: If any ``error`` check failed. The message lists every
            failure rather than only the first, so one run surfaces all of them.
    """
    failures = [r for r in results if not r.passed and r.severity == "error"]
    warnings = [r for r in results if not r.passed and r.severity == "warn"]

    for result in results:
        if result.passed:
            logger.debug("PASS %-46s %s", result.name, result.detail)
        elif result.severity == "warn":
            logger.warning("WARN %-46s %s", result.name, result.detail)
        else:
            logger.error("FAIL %-46s %s", result.name, result.detail)

    logger.info(
        "quality gate %s: %d passed, %d warned, %d failed",
        stage,
        sum(r.passed for r in results),
        len(warnings),
        len(failures),
    )

    if failures:
        summary = "; ".join(f"{r.name}: {r.detail}" for r in failures)
        raise DataQualityError(f"{len(failures)} check(s) failed at stage {stage!r}: {summary}")
    return results
