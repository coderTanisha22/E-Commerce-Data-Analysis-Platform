"""Tests for the deployment features: retailer login and the saved overview.

Both are off by default, so the rest of the API suite runs unchanged. Here a
tiny processed layer is written to a temporary directory so the real loader runs.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from ecom.api import create_app
from ecom.api.auth import SessionSigner, hash_password, parse_users, verify_password
from ecom.api.loader import OVERVIEW_KEY, load_platform, save_overview
from ecom.config import Settings
from ecom.ingestion.ingest import MANIFEST_KEY as RAW_MANIFEST_KEY
from ecom.storage.local import LocalStorage
from ecom.synthetic.run_generate import MANIFEST_KEY as INVENTORY_MANIFEST_KEY

SECRET = "test-secret"


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    """A processed layer of three orders and four products, plus both run manifests."""
    store = LocalStorage(tmp_path / "raw", tmp_path / "processed")
    orders = pd.DataFrame(
        {
            "order_id": ["o1", "o2", "o3"],
            "order_status": ["delivered", "delivered", "canceled"],
            "order_purchase_timestamp": pd.to_datetime(["2017-03-05", "2017-04-10", "2017-04-11"]),
            "is_delivered": [True, True, False],
        }
    )
    order_lines = pd.DataFrame(
        {
            "order_id": ["o1", "o1", "o2", "o3"],
            "product_id": ["p1", "p2", "p3", "p4"],
            "seller_id": ["s1", "s1", "s2", "s2"],
            "quantity": [1, 2, 1, 1],
            "line_revenue": [10.0, 40.0, 30.0, 99.0],
        }
    )
    tables = {
        "orders": orders,
        "order_lines": order_lines,
        "order_products": order_lines[["order_id", "product_id"]],
        "products": pd.DataFrame(
            {
                "product_id": ["p1", "p2", "p3", "p4"],
                "product_category_english": ["toys", "toys", "bed_bath_table", None],
            }
        ),
        "sellers": pd.DataFrame(
            {
                "seller_id": ["s1", "s2"],
                "seller_city": ["campinas", "rio"],
                "seller_state": ["SP", "RJ"],
            }
        ),
        "product_cooccurrence": pd.DataFrame(
            {"product_a": ["p1"], "product_b": ["p2"], "order_count": [3]}
        ),
        "synthetic_inventory": pd.DataFrame(
            {
                "seller_id": ["s1", "s2"],
                "product_id": ["p2", "p3"],
                "units_sold": [12, 30],
                "daily_sales_rate": [0.2, 0.5],
                "evidence": ["sufficient", "sufficient"],
                "lead_time_days": [10, 7],
                "reorder_point": [2.6, 5.0],
                "current_quantity": [30, 2],
                "last_restock_date": pd.to_datetime(["2018-07-01"] * 2),
                "days_of_inventory": [150.0, 4.0],
                "status": ["Healthy", "Urgent"],
                "is_synthetic": [True, True],
            }
        ),
    }
    for name, frame in tables.items():
        store.put_parquet(store.processed_key(name), frame)
    _write_manifests(store, ingested_at="2026-11-06T20:55:44+00:00")
    return store


def _write_manifests(store: LocalStorage, *, ingested_at: str) -> None:
    store.put_bytes(RAW_MANIFEST_KEY, json.dumps({"ingested_at": ingested_at}).encode())
    store.put_bytes(
        INVENTORY_MANIFEST_KEY, json.dumps({"generated_at": "2026-11-06T20:55:48+00:00"}).encode()
    )


# ---------------------------------------------------------------- passwords and sessions


def test_password_hash_round_trip() -> None:
    """The right password verifies; a wrong one or a malformed hash does not."""
    encoded = hash_password("s3cret")
    assert encoded.startswith("pbkdf2_sha256$")
    assert verify_password("s3cret", encoded)
    assert not verify_password("wrong", encoded)
    assert not verify_password("s3cret", "not-a-hash")


def test_parse_users_rejects_malformed_entries() -> None:
    """Accounts parse as name=<hash>; an entry without a hash is an error."""
    assert parse_users("alice=h1; bob=h2") == {"alice": "h1", "bob": "h2"}
    with pytest.raises(ValueError):
        parse_users("alice")


def test_session_tokens_cannot_be_forged_or_reused_after_expiry() -> None:
    """A tampered token or one past its expiry identifies nobody."""
    signer = SessionSigner(SECRET, hours=1)
    token = signer.issue("alice")
    assert signer.read(token) == "alice"
    assert SessionSigner("other-secret", hours=1).read(token) is None
    assert signer.read(token[:-4] + "AAAA") is None
    assert SessionSigner(SECRET, hours=0).read(SessionSigner(SECRET, hours=0).issue("a")) is None


# ---------------------------------------------------------------- login flow


def _auth_settings() -> Settings:
    return Settings(auth_users=f"retailer={hash_password('pw123')}", session_secret=SECRET)


def test_routes_require_login_when_accounts_are_configured(storage: LocalStorage) -> None:
    """Without a session the dashboard redirects and the API answers 401; /health stays open."""
    app = create_app(loader=lambda: load_platform(storage=storage), settings=_auth_settings())
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        home = client.get("/", follow_redirects=False)
        assert home.status_code == 303 and home.headers["location"] == "/login"
        assert client.get("/overview").status_code == 401


def test_login_logout_flow(storage: LocalStorage) -> None:
    """A wrong password is refused; the right one grants access until logout."""
    app = create_app(loader=lambda: load_platform(storage=storage), settings=_auth_settings())
    with TestClient(app) as client:
        wrong = client.post("/login", data={"username": "retailer", "password": "nope"})
        assert wrong.status_code == 401
        ok = client.post(
            "/login", data={"username": "retailer", "password": "pw123"}, follow_redirects=False
        )
        assert ok.status_code == 303
        assert client.get("/overview").status_code == 200
        assert client.get("/session").json() == {"user": "retailer"}
        client.get("/logout")
        assert client.get("/overview").status_code == 401


def test_accounts_without_a_session_secret_are_refused() -> None:
    """Configuring logins without a signing key is a deployment mistake, caught at start-up."""
    with pytest.raises(ValueError):
        create_app(settings=Settings(auth_users="a=h", session_secret=None))


# ---------------------------------------------------------------- saved overview


def test_saved_overview_matches_computed_and_skips_large_tables(
    storage: LocalStorage, tmp_path: Path
) -> None:
    """The saved figures equal the computed ones, so the large tables need not be read."""
    computed = load_platform(storage=storage, use_saved_overview=False).overview
    save_overview(storage=storage)
    for name in ("orders", "order_lines", "order_products"):
        (tmp_path / "processed" / f"{name}.parquet").unlink()
    saved = load_platform(storage=storage, use_saved_overview=True).overview
    assert saved == computed


def test_saved_overview_from_another_run_is_ignored(storage: LocalStorage) -> None:
    """After a new ingestion the saved file no longer matches, so figures are recomputed."""
    save_overview(storage=storage)
    stale = json.loads(storage.get_bytes(OVERVIEW_KEY))
    stale["overview"]["orders_in_window"] = 999
    storage.put_bytes(OVERVIEW_KEY, json.dumps(stale).encode())
    _write_manifests(storage, ingested_at="2026-11-13T00:00:00+00:00")
    overview = load_platform(storage=storage, use_saved_overview=True).overview
    assert overview.orders_in_window != 999
