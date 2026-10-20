"""Tests for data_ingestion.raw_writer."""

import json

from data_ingestion.raw_writer import (
    build_manifest_entry,
    build_run_id,
    copy_source_to_raw,
    raw_partition_path,
    write_manifest,
)


def test_build_run_id_includes_the_run_date():
    run_id = build_run_id("2026-10-13")
    assert run_id.startswith("2026-10-13_")


def test_raw_partition_path_follows_the_contracted_layout(tmp_path):
    path = raw_partition_path(tmp_path, "olist_orders_dataset", "2026-10-13")
    assert path == tmp_path / "olist_orders_dataset" / "run_date=2026-10-13"


def test_copy_source_to_raw_preserves_file_bytes(tmp_path):
    source = tmp_path / "source.csv"
    source.write_text("a,b\n1,2\n")
    destination_dir = tmp_path / "raw"

    destination_path = copy_source_to_raw(source, destination_dir)

    assert destination_path.read_text() == source.read_text()


def test_write_manifest_writes_valid_json(tmp_path):
    entry = build_manifest_entry(
        file_name="olist_sellers_dataset.csv",
        checksum="abc123",
        row_count=10,
        run_id="2026-10-13_aaaaaaaa",
        status="ingested",
    )
    manifest_path = tmp_path / "manifest.json"

    write_manifest(manifest_path, [entry])

    loaded = json.loads(manifest_path.read_text())
    assert loaded == [entry]
