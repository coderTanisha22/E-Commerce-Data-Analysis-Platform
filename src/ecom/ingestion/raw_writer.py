"""Writes validated source files into the raw storage zone.

The raw zone is append-only by convention: ingestion copies files in, never
edits them in place, and every run gets its own run_id so re-running
ingestion for the same run_date never silently overwrites a prior run's
output without a trace.
"""

import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path


def build_run_id(run_date):
    """Return a run_id that is unique per invocation but traceable to a date."""
    return f"{run_date}_{uuid.uuid4().hex[:8]}"


def raw_partition_path(raw_zone_dir, table_name, run_date):
    """Return the raw-zone directory for one table and one run_date.

    Layout: <raw_zone_dir>/<table_name>/run_date=<run_date>/
    This partitioning scheme is the contract Spark's cleaning stage reads
    against - see docs/contracts.md.
    """
    return Path(raw_zone_dir) / table_name / f"run_date={run_date}"


def copy_source_to_raw(source_path, destination_dir):
    """Copy one source file into the raw zone unchanged, byte-for-byte."""
    destination_dir = Path(destination_dir)
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination_path = destination_dir / Path(source_path).name
    shutil.copy2(source_path, destination_path)
    return destination_path


def build_manifest_entry(file_name, checksum, row_count, run_id, status, missing_columns=None):
    """Build one manifest record describing an ingested file.

    This is the project's provenance trail: every raw file is traceable to
    the run that produced it, with enough detail to re-verify it later.
    """
    return {
        "file_name": file_name,
        "checksum_sha256": checksum,
        "row_count": row_count,
        "run_id": run_id,
        "status": status,
        "missing_columns": missing_columns or [],
        "ingestion_timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }


def write_manifest(manifest_path, entries):
    """Write the run's manifest entries as a single JSON file."""
    manifest_path = Path(manifest_path)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8") as handle:
        json.dump(entries, handle, indent=2)
