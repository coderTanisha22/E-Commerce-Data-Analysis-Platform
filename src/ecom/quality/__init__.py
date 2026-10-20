"""Data quality gates. Checks raise by default; warnings are declared, not accidental."""

from ecom.quality.checks import (
    CheckResult,
    DataQualityError,
    check_foreign_key,
    check_no_nulls,
    check_unique_key,
    run_gate,
)

__all__ = [
    "CheckResult",
    "DataQualityError",
    "check_foreign_key",
    "check_no_nulls",
    "check_unique_key",
    "run_gate",
]
