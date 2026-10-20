"""Reads and validates the Olist source CSVs before they enter the raw zone.

Every check here is cheap on purpose: it reads headers and streams bytes for
checksums rather than loading full files into memory, since
olist_geolocation_dataset.csv alone is around 1 million rows.
"""

import csv
import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from ecom.source_registry import get_required_columns


@dataclass
class SourceValidationResult:
    """Outcome of validating one source file against its schema contract."""

    file_name: str
    file_path: Path
    missing_columns: list = field(default_factory=list)

    @property
    def is_valid(self):
        return not self.missing_columns


def discover_source_files(source_dir, expected_file_names):
    """Map each expected file name to its path, if present in source_dir.

    Files that are expected but missing from source_dir are simply absent
    from the returned dict - callers decide whether that is fatal.
    """
    found = {}
    for file_name in expected_file_names:
        candidate = Path(source_dir) / file_name
        if candidate.exists():
            found[file_name] = candidate
    return found


def read_source_header(file_path):
    """Return the column names in a CSV's header row.

    Uses utf-8-sig so a BOM-prefixed file (product_category_name_translation.csv
    ships with one) doesn't corrupt the first column name.
    """
    with open(file_path, encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        header_row = next(reader)
    return [column.strip() for column in header_row]


def validate_source_file(file_name, file_path):
    """Check one source file's header against its required-columns contract."""
    actual_columns = set(read_source_header(file_path))
    required_columns = get_required_columns(file_name)
    missing_columns = [column for column in required_columns if column not in actual_columns]
    return SourceValidationResult(file_name, file_path, missing_columns)


def compute_file_checksum(file_path, chunk_size=1024 * 1024):
    """Return the sha256 checksum of a file, reading it in chunks.

    The checksum is what lets a later audit prove a raw-zone copy still
    matches the original Olist export byte-for-byte.
    """
    digest = hashlib.sha256()
    with open(file_path, "rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def count_data_rows(file_path):
    """Return the number of data rows in a CSV, excluding the header.

    Uses csv.reader rather than a raw physical-line count. Some Olist
    columns (review comments in particular) contain embedded newlines
    inside quoted fields, so counting '\\n' bytes overcounts those files -
    this matters because the result goes straight into the ingestion
    manifest as provenance evidence.
    """
    with open(file_path, encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        row_count = sum(1 for _ in reader)
    return max(row_count - 1, 0)
