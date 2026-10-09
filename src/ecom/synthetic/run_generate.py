"""Generate the synthetic inventory table and write it with a manifest.

The only module in this package that performs I/O. It reads the processed layer,
calls the pure generator, and writes the table plus a manifest recording the
seed, every parameter and a SHA-256 of the output, so any run can be reproduced
and verified later.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
from datetime import datetime, timezone

import pandas as pd

from ecom.config import Settings, get_settings
from ecom.storage import StorageBackend, get_storage
from ecom.synthetic.inventory import GeneratorParams, filter_funnel, generate_synthetic_inventory

logger = logging.getLogger(__name__)

TABLE_NAME = "synthetic_inventory"
MANIFEST_KEY = "processed/_synthetic_inventory_manifest.json"


def frame_digest(df: pd.DataFrame) -> str:
    """Return a SHA-256 of the frame's contents.

    Hashes a canonical CSV rendering rather than the Parquet bytes, because
    Parquet embeds writer metadata that can change between library versions
    while the data stays identical. The digest must track the data only.
    """
    buffer = io.StringIO()
    df.to_csv(buffer, index=False, float_format="%.10f", lineterminator="\n")
    return hashlib.sha256(buffer.getvalue().encode("utf-8")).hexdigest()


def build_manifest(
    df: pd.DataFrame, params: GeneratorParams, funnel: list[tuple[str, int]]
) -> dict:
    """Describe a generated table well enough to reproduce and audit it."""
    return {
        "table": TABLE_NAME,
        "is_synthetic": True,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rows": len(df),
        "columns": list(df.columns),
        "sha256": frame_digest(df),
        "seed": params.seed,
        "parameters": params.as_dict(),
        "filter_funnel": [{"step": s, "count": int(c)} for s, c in funnel],
        "status_counts": {k: int(v) for k, v in df["status"].value_counts().items()},
        "sellers": int(df["seller_id"].nunique()),
        "products": int(df["product_id"].nunique()),
    }


def generate_and_store(
    *,
    storage: StorageBackend | None = None,
    settings: Settings | None = None,
    params: GeneratorParams | None = None,
) -> dict:
    """Read the processed layer, generate the table, and write it with a manifest.

    Args:
        storage: Backend to read and write. Defaults to the configured one.
        settings: Override settings, mainly for tests.
        params: Generator settings. Defaults to the documented constants.

    Returns:
        The manifest that was written.
    """
    settings = settings or get_settings()
    storage = storage or get_storage(settings)
    params = params or GeneratorParams()

    order_lines = storage.get_parquet(storage.processed_key("order_lines"))
    orders = storage.get_parquet(storage.processed_key("orders"))

    funnel = filter_funnel(order_lines, orders, params)
    for step, count in funnel:
        logger.info("  %-52s %8d", step, count)

    table = generate_synthetic_inventory(order_lines, orders, params)
    storage.put_parquet(storage.processed_key(TABLE_NAME), table)

    manifest = build_manifest(table, params, funnel)
    storage.put_bytes(MANIFEST_KEY, json.dumps(manifest, indent=2).encode())
    logger.info("wrote %s (%d rows, sha256 %s)", TABLE_NAME, len(table), manifest["sha256"][:16])
    return manifest
