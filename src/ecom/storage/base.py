"""Storage backend interface.

The pipeline addresses storage by logical key (``raw/olist/orders.csv``), never
by filesystem path or bucket name. That indirection is the whole point: the
local and MinIO backends are interchangeable, so the raw/processed layer
responsibility is identical whether or not an object store is running.
"""

from __future__ import annotations

import io
from abc import ABC, abstractmethod

import pandas as pd

RAW_PREFIX = "raw"
PROCESSED_PREFIX = "processed"


class StorageBackend(ABC):
    """A key-addressed byte store with Parquet and CSV conveniences."""

    @abstractmethod
    def put_bytes(self, key: str, data: bytes) -> None:
        """Write raw bytes at ``key``, overwriting any existing object."""

    @abstractmethod
    def get_bytes(self, key: str) -> bytes:
        """Read the object at ``key``.

        Raises:
            FileNotFoundError: If no object exists at that key.
        """

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Return whether an object exists at ``key``."""

    @abstractmethod
    def list_keys(self, prefix: str = "") -> list[str]:
        """Return every key under ``prefix``, sorted."""

    @abstractmethod
    def describe(self) -> str:
        """Return a short human-readable location, for logs and manifests."""

    # ------------------------------------------------------------ conveniences
    def put_parquet(self, key: str, df: pd.DataFrame) -> None:
        """Serialise a DataFrame to Parquet and store it at ``key``.

        Parquet rather than CSV because the processed layer must carry its
        dtypes; re-inferring them downstream is how silent type bugs start.
        """
        buffer = io.BytesIO()
        df.to_parquet(buffer, index=False, engine="pyarrow", compression="snappy")
        self.put_bytes(key, buffer.getvalue())

    def get_parquet(self, key: str) -> pd.DataFrame:
        """Read a Parquet object back into a DataFrame."""
        return pd.read_parquet(io.BytesIO(self.get_bytes(key)), engine="pyarrow")

    def get_csv(self, key: str, **read_csv_kwargs: object) -> pd.DataFrame:
        """Read a CSV object into a DataFrame, passing kwargs to ``read_csv``."""
        return pd.read_csv(io.BytesIO(self.get_bytes(key)), **read_csv_kwargs)  # type: ignore[arg-type]

    @staticmethod
    def raw_key(source: str, table: str, suffix: str = "csv") -> str:
        """Build the raw-layer key for a table, e.g. ``raw/olist/orders.csv``."""
        return f"{RAW_PREFIX}/{source}/{table}.{suffix}"

    @staticmethod
    def processed_key(table: str) -> str:
        """Build the processed-layer key for a table, e.g. ``processed/orders.parquet``."""
        return f"{PROCESSED_PREFIX}/{table}.parquet"
