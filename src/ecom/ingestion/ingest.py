"""Ingestion: copy source files into the raw layer without altering them.

Ingestion does three things and nothing else: check the file is present and has
the columns its contract declares, land the bytes unchanged, and record what was
landed. Cleaning and type coercion belong to the next stage, so the raw layer
stays a faithful copy of the evidence.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from ecom.config import Settings, get_settings
from ecom.contracts import OLIST_CONTRACTS, TableContract
from ecom.storage import StorageBackend, get_storage

logger = logging.getLogger(__name__)

MANIFEST_KEY = "raw/_manifest.json"
SOURCE_NAME = "olist"


class IngestionError(RuntimeError):
    """Raised when a source file is missing or violates its contract."""


@dataclass(frozen=True)
class TableManifest:
    """What one ingested table looked like at landing time.

    ``sha256`` makes re-runs verifiable: unchanged input yields an identical
    manifest, which is how the pipeline claims idempotency.
    """

    table: str
    source_file: str
    raw_key: str
    rows: int
    columns: int
    bytes: int
    sha256: str
    expected_rows: int | None
    row_drift: int | None


def _read_header(data: bytes) -> list[str]:
    """Return the CSV header, tolerating a UTF-8 BOM.

    The category translation file ships with a BOM, which would otherwise make
    its first column name fail an exact contract match.
    """
    text = data.decode("utf-8-sig", errors="strict")
    reader = csv.reader(io.StringIO(text))
    try:
        return next(reader)
    except StopIteration as exc:
        raise IngestionError("source file is empty") from exc


def _count_rows(data: bytes) -> int:
    """Count data rows, honouring quoted newlines.

    Review comments in Olist contain embedded newlines, so a line count would
    overstate the row count. Parsing is slower but correct.
    """
    text = data.decode("utf-8-sig", errors="strict")
    reader = csv.reader(io.StringIO(text))
    next(reader, None)  # header
    return sum(1 for _ in reader)


def validate_against_contract(data: bytes, contract: TableContract) -> tuple[int, list[str]]:
    """Check a source file satisfies its declared schema.

    Args:
        data: Raw file bytes.
        contract: The contract the file must satisfy.

    Returns:
        The data row count and the header actually found.

    Raises:
        IngestionError: If declared columns are missing. Extra columns are
            allowed and logged, because a widened source is not a reason to
            halt a batch, while a missing column silently breaks every join.
    """
    header = _read_header(data)
    missing = [column for column in contract.columns if column not in header]
    if missing:
        raise IngestionError(
            f"table {contract.name!r} is missing declared columns {missing}; found {header}"
        )

    extra = [column for column in header if column not in contract.columns]
    if extra:
        logger.warning("table %s has undeclared extra columns %s", contract.name, extra)

    return _count_rows(data), header


def ingest_table(
    contract: TableContract,
    *,
    storage: StorageBackend,
    source_dir: Path,
) -> TableManifest:
    """Validate one source file and land it in the raw layer unchanged.

    Args:
        contract: Contract for the table being ingested.
        storage: Backend receiving the raw bytes.
        source_dir: Directory holding the untouched download.

    Returns:
        The manifest entry describing what was landed.

    Raises:
        IngestionError: If the file is absent or violates its contract.
    """
    source_path = source_dir / contract.filename
    if not source_path.exists():
        raise IngestionError(f"source file not found for {contract.name!r}: {source_path}")

    data = source_path.read_bytes()
    rows, _ = validate_against_contract(data, contract)

    key = storage.raw_key(SOURCE_NAME, contract.name)
    storage.put_bytes(key, data)

    drift = None if contract.expected_rows is None else rows - contract.expected_rows
    if drift:
        logger.warning(
            "table %s row count %d differs from reference %d by %+d",
            contract.name,
            rows,
            contract.expected_rows,
            drift,
        )

    logger.info("ingested %-22s %7d rows -> %s", contract.name, rows, key)
    return TableManifest(
        table=contract.name,
        source_file=contract.filename,
        raw_key=key,
        rows=rows,
        columns=len(contract.columns),
        bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        expected_rows=contract.expected_rows,
        row_drift=drift,
    )


def ingest_all(
    *,
    storage: StorageBackend | None = None,
    settings: Settings | None = None,
    contracts: tuple[TableContract, ...] = OLIST_CONTRACTS,
) -> dict[str, object]:
    """Ingest every contracted table and write the run manifest.

    Args:
        storage: Backend to write into. Defaults to the configured one.
        settings: Override settings, mainly for tests.
        contracts: Tables to ingest. Defaults to the Olist set.

    Returns:
        The manifest that was written, as a plain dict.

    Raises:
        IngestionError: On the first table that fails validation, so a partial
            raw layer is never reported as a success.
    """
    settings = settings or get_settings()
    storage = storage or get_storage(settings)
    source_dir = settings.resolve(settings.source_dir)

    logger.info("ingesting %d tables from %s", len(contracts), source_dir)
    entries = [
        ingest_table(contract, storage=storage, source_dir=source_dir) for contract in contracts
    ]

    manifest: dict[str, object] = {
        "ingested_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_dir": str(source_dir),
        "storage": storage.describe(),
        "table_count": len(entries),
        "total_rows": sum(entry.rows for entry in entries),
        "tables": [asdict(entry) for entry in entries],
    }
    storage.put_bytes(MANIFEST_KEY, json.dumps(manifest, indent=2).encode())
    logger.info("manifest written: %d tables, %d rows", len(entries), manifest["total_rows"])
    return manifest
