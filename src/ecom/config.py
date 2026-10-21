"""Immutable settings and named analytical constants.

Every number that can change a published result lives here with a comment
explaining the value, per docs/CODING_STANDARDS.md section 8.
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]

# --------------------------------------------------------------------- domain
DELIVERED_STATUS = "delivered"
"""Only delivered orders count as realised sales; 2,963 orders are not delivered."""

UNKNOWN_CATEGORY = "unknown"
"""Bucket for the 610 products whose product_category_name is NULL."""

EXCLUDED_STATUSES: tuple[str, ...] = ("canceled", "unavailable")
"""Order statuses that are genuine failures and so count as no evidence at all.

Every other status -- including ``shipped``, ``invoiced`` and ``processing`` --
describes an order that was really placed and is simply still in flight.

This is the project's single rule for which orders count as evidence of
behaviour, and it is deliberately *not* the same as ``is_delivered``. Requiring
delivery was measured to discard 32 product pairs belonging to in-flight
orders while removing only 4 belonging to failed ones: delivery is a logistics
outcome and says nothing about whether a customer chose two products together.

Realised *revenue* is the one place the stricter delivered-only filter is still
correct, because an in-flight order is not money yet. See profile_sales."""

# The observation window excludes both unusable ends of the Olist timeline:
# Nov 2016 has 0 orders and Dec 2016 has 1, so the opening months would inflate
# the denominator of every velocity figure; and of the 20 orders after
# 2018-09-01, 19 are cancelled and 1 is shipped, with no deliveries at all.
WINDOW_START = date(2017, 2, 1)
WINDOW_END = date(2018, 8, 31)

MIN_COOCCURRENCE_COUNT = 2
"""Edges seen in a single order are noise: 94.9% of raw pairs have weight 1."""

RESTOCK_URGENT_RATIO = 1.0
"""days_of_inventory <= lead_time_days * this -> URGENT."""

RESTOCK_MONITOR_RATIO = 2.0
"""days_of_inventory <= lead_time_days * this -> MONITOR, else HEALTHY."""


class Settings(BaseSettings):
    """Runtime configuration, read from the environment or a .env file."""

    model_config = SettingsConfigDict(
        env_prefix="ECOM_", env_file=".env", extra="ignore", frozen=True
    )

    storage_backend: str = "local"
    source_dir: Path = Path("data")
    raw_root: Path = Path("data/raw")
    processed_root: Path = Path("data/processed")

    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "ecom-platform"
    minio_secure: bool = False

    window_start: date = WINDOW_START
    window_end: date = WINDOW_END
    log_level: str = "INFO"

    fast_reader: bool = False
    """Parse raw CSVs with Arrow instead of pandas during cleaning.

    Off by default so the published numbers come from the path the project has
    always run. Both paths produce an identical processed layer -- that
    equivalence is asserted by tests/test_bench.py and by ``ecom bench
    --verify-flag`` -- so this is a pure performance switch, not a variant.
    Set ECOM_FAST_READER=1 to enable."""

    reports_dir: Path = Field(default=Path("reports"))

    def resolve(self, value: Path) -> Path:
        """Make a configured path absolute against the repo root."""
        return value if value.is_absolute() else REPO_ROOT / value

    @property
    def window_days(self) -> int:
        """Length of the observation window, the denominator for sales velocity."""
        return (self.window_end - self.window_start).days + 1


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()
