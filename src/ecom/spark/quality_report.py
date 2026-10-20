"""Builds and writes the per-run data-quality report.

This JSON file is the evidence artifact for the handoff to B: it is what
proves a cleaning run's outputs are trustworthy without anyone having to
re-run the pipeline to check.
"""

import json
from datetime import datetime, timezone
from pathlib import Path


def build_table_quality_summary(
    table_name,
    input_row_count,
    output_row_count,
    quarantined_row_count,
    null_counts,
    duplicate_key_count,
):
    """Assemble one table's entry in the data-quality report.

    Duplicate keys are reported but deliberately not quarantined here -
    deduplication strategy (keep-first, keep-latest, merge) is a staging
    decision for B to make in dbt, not something Spark cleaning should
    decide silently. The status distinguishes the two cases so that
    distinction is never lost: "pass_with_quarantine" means rows were
    actually removed from the clean output; "pass_with_duplicates" means
    every row is still present but B needs to dedupe before using the key.
    """
    if quarantined_row_count > 0:
        status = "pass_with_quarantine"
    elif duplicate_key_count > 0:
        status = "pass_with_duplicates"
    else:
        status = "pass"

    return {
        "table_name": table_name,
        "input_row_count": input_row_count,
        "output_row_count": output_row_count,
        "quarantined_row_count": quarantined_row_count,
        "null_counts_by_required_column": null_counts,
        "duplicate_key_row_count": duplicate_key_count,
        "status": status,
    }


def build_run_report(run_date, run_id, table_summaries):
    """Assemble the full report for one cleaning run across all tables."""
    return {
        "run_date": run_date,
        "run_id": run_id,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "tables": table_summaries,
    }


def write_quality_report(report, report_path):
    """Write the run's data-quality report as a single JSON file."""
    report_path = Path(report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
