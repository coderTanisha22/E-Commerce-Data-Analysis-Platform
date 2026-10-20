"""Tests for the storage adapter.

Only the local backend is exercised here; the MinIO backend is verified against
a running container via ``make minio-up``, because mocking an S3 client tests the
mock rather than the integration.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from ecom.storage import LocalStorage, StorageBackend


@pytest.fixture
def store(tmp_path: Path) -> LocalStorage:
    return LocalStorage(raw_root=tmp_path / "raw", processed_root=tmp_path / "processed")


def test_round_trips_bytes(store: LocalStorage) -> None:
    store.put_bytes("raw/olist/orders.csv", b"order_id\na\n")
    assert store.get_bytes("raw/olist/orders.csv") == b"order_id\na\n"
    assert store.exists("raw/olist/orders.csv")


def test_round_trips_parquet_preserving_dtypes(store: LocalStorage) -> None:
    """Parquet over CSV exists precisely so dtypes survive the processed layer."""
    df = pd.DataFrame({"n": [1, 2], "t": pd.to_datetime(["2017-01-01", "2018-01-01"])})
    store.put_parquet("processed/x.parquet", df)
    back = store.get_parquet("processed/x.parquet")
    pd.testing.assert_frame_equal(df, back)


def test_missing_key_raises_filenotfound(store: LocalStorage) -> None:
    with pytest.raises(FileNotFoundError):
        store.get_bytes("raw/olist/absent.csv")


def test_unknown_prefix_is_rejected(store: LocalStorage) -> None:
    with pytest.raises(ValueError, match="must start with"):
        store.put_bytes("scratch/x.csv", b"")


def test_path_traversal_is_rejected(store: LocalStorage) -> None:
    with pytest.raises(ValueError, match="outside its root"):
        store.put_bytes("raw/../../escaped.csv", b"")


def test_list_keys_filters_by_prefix(store: LocalStorage) -> None:
    store.put_bytes("raw/olist/a.csv", b"x")
    store.put_bytes("processed/b.parquet", b"y")
    assert store.list_keys("raw/") == ["raw/olist/a.csv"]
    assert len(store.list_keys()) == 2


def test_key_builders_match_documented_layout() -> None:
    assert StorageBackend.raw_key("olist", "orders") == "raw/olist/orders.csv"
    assert StorageBackend.processed_key("orders") == "processed/orders.parquet"
