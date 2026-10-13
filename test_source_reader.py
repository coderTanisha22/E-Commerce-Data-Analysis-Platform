"""Tests for data_ingestion.source_reader."""

import csv

from data_ingestion.source_reader import (
    compute_file_checksum,
    count_data_rows,
    discover_source_files,
    read_source_header,
    validate_source_file,
)


def write_csv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def test_discover_source_files_finds_present_files(tmp_path):
    write_csv(tmp_path / "a.csv", ["id"], [["1"]])
    found = discover_source_files(tmp_path, ["a.csv", "b.csv"])
    assert list(found.keys()) == ["a.csv"]


def test_read_source_header_strips_bom(tmp_path):
    file_path = tmp_path / "bom.csv"
    file_path.write_bytes("﻿col_a,col_b\n1,2\n".encode("utf-8"))
    assert read_source_header(file_path) == ["col_a", "col_b"]


def test_validate_source_file_detects_missing_columns(tmp_path):
    file_path = tmp_path / "olist_sellers_dataset.csv"
    write_csv(file_path, ["seller_id", "seller_city"], [["s1", "Pune"]])

    result = validate_source_file("olist_sellers_dataset.csv", file_path)

    assert not result.is_valid
    assert "seller_zip_code_prefix" in result.missing_columns
    assert "seller_state" in result.missing_columns


def test_validate_source_file_passes_with_all_columns(tmp_path):
    file_path = tmp_path / "olist_sellers_dataset.csv"
    write_csv(
        file_path,
        ["seller_id", "seller_zip_code_prefix", "seller_city", "seller_state"],
        [["s1", "13056", "Campinas", "SP"]],
    )

    result = validate_source_file("olist_sellers_dataset.csv", file_path)

    assert result.is_valid
    assert result.missing_columns == []


def test_compute_file_checksum_is_deterministic(tmp_path):
    file_path = tmp_path / "data.csv"
    write_csv(file_path, ["id"], [["1"], ["2"]])

    first = compute_file_checksum(file_path)
    second = compute_file_checksum(file_path)

    assert first == second
    assert len(first) == 64  # sha256 hex digest length


def test_count_data_rows_excludes_header(tmp_path):
    file_path = tmp_path / "data.csv"
    write_csv(file_path, ["id"], [["1"], ["2"], ["3"]])

    assert count_data_rows(file_path) == 3
