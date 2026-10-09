"""Tests for the quality gate."""

from __future__ import annotations

import pandas as pd
import pytest

from ecom.quality.checks import (
    DataQualityError,
    check_foreign_key,
    check_no_nulls,
    check_unique_key,
    run_gate,
)


def test_unique_key_detects_duplicates() -> None:
    df = pd.DataFrame({"id": ["a", "a", "b"]})
    result = check_unique_key(df, "t", ("id",))
    assert not result.passed
    assert result.offending_rows == 1


def test_unique_key_passes_on_clean_key() -> None:
    assert check_unique_key(pd.DataFrame({"id": ["a", "b"]}), "t", ("id",)).passed


def test_foreign_key_detects_orphans() -> None:
    child = pd.DataFrame({"pid": ["p1", "p9"]})
    parent = pd.DataFrame({"product_id": ["p1"]})
    result = check_foreign_key(child, parent, "pid", "product_id", "c->p")
    assert not result.passed
    assert result.offending_rows == 1


def test_no_nulls_counts_rows_not_cells() -> None:
    df = pd.DataFrame({"a": [1, None], "b": [None, None]})
    assert check_no_nulls(df, "t", ("a", "b")).offending_rows == 2


def test_gate_raises_on_error_severity() -> None:
    failing = check_unique_key(pd.DataFrame({"id": ["a", "a"]}), "t", ("id",))
    with pytest.raises(DataQualityError, match="1 check\\(s\\) failed"):
        run_gate([failing], stage="test")


def test_gate_tolerates_declared_warnings() -> None:
    """A documented Olist quirk must not halt the batch."""
    warned = check_unique_key(pd.DataFrame({"id": ["a", "a"]}), "t", ("id",), severity="warn")
    assert run_gate([warned], stage="test") == [warned]


def test_gate_reports_every_failure_not_just_the_first() -> None:
    bad = pd.DataFrame({"id": ["a", "a"]})
    checks = [
        check_unique_key(bad, "t1", ("id",)),
        check_unique_key(bad, "t2", ("id",)),
    ]
    with pytest.raises(DataQualityError) as exc:
        run_gate(checks, stage="test")
    assert "t1" in str(exc.value)
    assert "t2" in str(exc.value)
