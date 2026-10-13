"""CLI entrypoint for the ingestion stage.

Airflow (owned by D) will eventually call run_ingestion_pipeline() directly
from a PythonOperator instead of shelling out to this script, so the
pipeline logic lives in a plain function rather than inside __main__.
"""

import argparse
import sys
from datetime import date
from pathlib import Path

from data_ingestion.config import RAW_ZONE_DIR, SOURCE_DATA_DIR
from data_ingestion.raw_writer import (
    build_manifest_entry,
    build_run_id,
    copy_source_to_raw,
    raw_partition_path,
    write_manifest,
)
from data_ingestion.schema_registry import get_expected_source_files
from data_ingestion.source_reader import (
    compute_file_checksum,
    count_data_rows,
    discover_source_files,
    validate_source_file,
)


def parse_args():
    parser = argparse.ArgumentParser(description="Ingest Olist source CSVs into the raw zone.")
    parser.add_argument(
        "--run-date",
        default=date.today().isoformat(),
        help="Logical run date for this ingestion run (YYYY-MM-DD). Defaults to today.",
    )
    return parser.parse_args()


def build_manifest_path(run_date, run_id):
    """Return where this run's manifest file should be written."""
    return Path(RAW_ZONE_DIR) / "_manifests" / f"{run_date}_{run_id}.json"


def ingest_one_file(file_name, file_path, run_date, run_id):
    """Validate, copy, and build a manifest entry for a single source file."""
    validation = validate_source_file(file_name, file_path)
    if not validation.is_valid:
        return build_manifest_entry(
            file_name=file_name,
            checksum="",
            row_count=0,
            run_id=run_id,
            status="rejected_missing_columns",
            missing_columns=validation.missing_columns,
        )

    table_name = file_name.replace(".csv", "")
    destination_dir = raw_partition_path(RAW_ZONE_DIR, table_name, run_date)
    copy_source_to_raw(file_path, destination_dir)

    checksum = compute_file_checksum(file_path)
    row_count = count_data_rows(file_path)
    return build_manifest_entry(
        file_name=file_name,
        checksum=checksum,
        row_count=row_count,
        run_id=run_id,
        status="ingested",
    )


def run_ingestion_pipeline(run_date):
    """Ingest every expected Olist source file for one run_date.

    Returns the list of manifest entries so callers (CLI, tests, Airflow)
    can inspect per-file outcomes without re-reading the manifest file.
    """
    expected_files = get_expected_source_files()
    found_files = discover_source_files(SOURCE_DATA_DIR, expected_files)
    run_id = build_run_id(run_date)

    manifest_entries = []
    for file_name in expected_files:
        if file_name not in found_files:
            manifest_entries.append(
                build_manifest_entry(
                    file_name=file_name,
                    checksum="",
                    row_count=0,
                    run_id=run_id,
                    status="missing_source_file",
                )
            )
            continue
        manifest_entries.append(
            ingest_one_file(file_name, found_files[file_name], run_date, run_id)
        )

    manifest_path = build_manifest_path(run_date, run_id)
    write_manifest(manifest_path, manifest_entries)
    return manifest_entries


def main():
    args = parse_args()
    entries = run_ingestion_pipeline(args.run_date)

    for entry in entries:
        print(f"{entry['status']:<24} {entry['file_name']}")

    rejected = [entry for entry in entries if entry["status"] != "ingested"]
    if rejected:
        print(f"\n{len(rejected)} file(s) failed ingestion.", file=sys.stderr)
        sys.exit(1)

    print(f"\nAll {len(entries)} source files ingested successfully.")


if __name__ == "__main__":
    main()
