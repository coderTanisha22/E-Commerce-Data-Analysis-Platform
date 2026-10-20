"""Pure transforms that build the synthetic inventory table.

The split this module enforces is the point of the whole exercise:

* ``units_sold``, ``first_sale_date``, ``active_days`` and ``daily_sales_rate``
  are **derived from real Olist orders** and contain no randomness.
* ``lead_time_days``, ``current_quantity`` and ``last_restock_date`` are
  **generated** from a seeded random number generator.
* ``reorder_point``, ``days_of_inventory`` and ``status`` are **deterministic
  functions** of the two groups above.

No function here reads or writes a file (docs/CODING_STANDARDS.md section 2), so
each rule is testable on a handful of rows and the whole table is reproducible
from a seed alone.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------- defaults
SEED = 42
"""Fixed so two runs of the pipeline produce a byte-identical table."""

AS_OF = date(2018, 9, 1)
"""The day stock is imagined to be counted. One day after the analysis window
closes, so every sale in the window is already history."""

WINDOW_START = date(2017, 2, 1)
WINDOW_END = date(2018, 8, 31)
"""Nov 2016 has zero orders and 19 of the last 20 orders were cancelled, so both
ends of the raw Olist range would distort any sales-per-day figure."""

EXCLUDED_STATUSES: tuple[str, ...] = ("canceled", "unavailable")
"""These orders never shipped, so counting them would overstate demand."""

EVIDENCE_MIN_UNITS = 3
"""Below three units a sales rate is one or two events, not a trend. Such rows
are kept but flagged, never silently dropped."""

MIN_ACTIVE_DAYS = 30
"""Floor on the rate denominator. A product first sold three days before AS_OF
would otherwise show an implausible rate from a single order."""

LEAD_TIME_RANGE = (5, 20)
SAFETY_DAYS = 3
STOCK_FACTOR_RANGE = (0.2, 3.0)
RESTOCK_LOOKBACK_DAYS = (1, 60)
MONITOR_EXTRA_DAYS = 7

STATUS_INSUFFICIENT = "Insufficient data"
STATUS_URGENT = "Urgent"
STATUS_MONITOR = "Monitor"
STATUS_HEALTHY = "Healthy"

REAL_COLUMNS: tuple[str, ...] = (
    "seller_id",
    "product_id",
    "units_sold",
    "first_sale_date",
    "active_days",
    "daily_sales_rate",
    "evidence",
)
"""Columns derived only from Olist. A generator change must never move these."""

SYNTHETIC_COLUMNS: tuple[str, ...] = (
    "lead_time_days",
    "current_quantity",
    "last_restock_date",
)


@dataclass(frozen=True)
class GeneratorParams:
    """Every knob the generator has, so sensitivity analysis varies data not code.

    Attributes:
        seed: Seed for the random number generator.
        as_of: Date the stock snapshot is taken on.
        window: Inclusive sales window used for the rate denominator.
        excluded_statuses: Order statuses that do not count as demand.
        evidence_min_units: Units below which a rate is flagged as weak evidence.
        min_active_days: Floor applied to the rate denominator.
        lead_time_range: Inclusive integer range for a seller's lead time.
        safety_days: Extra days of cover added on top of the lead time.
        stock_factor_range: Multiplier applied to the reorder point for stock.
        restock_lookback_days: Range of days before ``as_of`` for the last restock.
        monitor_extra_days: Days beyond lead time that still counts as Monitor.
    """

    seed: int = SEED
    as_of: date = AS_OF
    window: tuple[date, date] = (WINDOW_START, WINDOW_END)
    excluded_statuses: tuple[str, ...] = EXCLUDED_STATUSES
    evidence_min_units: int = EVIDENCE_MIN_UNITS
    min_active_days: int = MIN_ACTIVE_DAYS
    lead_time_range: tuple[int, int] = LEAD_TIME_RANGE
    safety_days: int = SAFETY_DAYS
    stock_factor_range: tuple[float, float] = STOCK_FACTOR_RANGE
    restock_lookback_days: tuple[int, int] = RESTOCK_LOOKBACK_DAYS
    monitor_extra_days: int = MONITOR_EXTRA_DAYS
    metadata: dict = field(default_factory=dict, compare=False)

    def as_dict(self) -> dict:
        """Return the parameters as plain JSON-safe values for the manifest."""
        return {
            "seed": self.seed,
            "as_of": str(self.as_of),
            "window_start": str(self.window[0]),
            "window_end": str(self.window[1]),
            "excluded_statuses": list(self.excluded_statuses),
            "evidence_min_units": self.evidence_min_units,
            "min_active_days": self.min_active_days,
            "lead_time_range": list(self.lead_time_range),
            "safety_days": self.safety_days,
            "stock_factor_range": list(self.stock_factor_range),
            "restock_lookback_days": list(self.restock_lookback_days),
            "monitor_extra_days": self.monitor_extra_days,
        }


def _eligible_lines(
    order_lines: pd.DataFrame, orders: pd.DataFrame, params: GeneratorParams
) -> pd.DataFrame:
    """Join order lines to their order and keep only rows that count as demand."""
    joined = order_lines.merge(
        orders[["order_id", "order_status", "order_purchase_timestamp"]],
        on="order_id",
        how="inner",
        validate="many_to_one",
    )
    joined = joined[~joined["order_status"].isin(params.excluded_statuses)]
    start = pd.Timestamp(params.window[0])
    end = pd.Timestamp(params.window[1]) + pd.Timedelta(days=1)
    return joined[joined["order_purchase_timestamp"].between(start, end, inclusive="left")]


def filter_funnel(
    order_lines: pd.DataFrame, orders: pd.DataFrame, params: GeneratorParams
) -> list[tuple[str, int]]:
    """Count rows surviving each filter, for the reconciliation table.

    Explains why the full dataset holds 34,448 seller-product pairs but the
    generated table holds fewer.

    Returns:
        Ordered ``(step, count)`` pairs.
    """
    pairs_all = order_lines.groupby(["seller_id", "product_id"], sort=False).ngroups
    joined = order_lines.merge(
        orders[["order_id", "order_status", "order_purchase_timestamp"]],
        on="order_id",
        how="inner",
        validate="many_to_one",
    )
    kept_status = joined[~joined["order_status"].isin(params.excluded_statuses)]
    eligible = _eligible_lines(order_lines, orders, params)
    grain = eligible.groupby(["seller_id", "product_id"], sort=False)["quantity"].sum()
    sufficient = int((grain >= params.evidence_min_units).sum())

    return [
        ("order_lines rows", len(order_lines)),
        ("distinct (seller_id, product_id) pairs, all data", pairs_all),
        ("lines joined to orders", len(joined)),
        (f"after excluding {list(params.excluded_statuses)}", len(kept_status)),
        (f"after window {params.window[0]} to {params.window[1]}", len(eligible)),
        ("grain: (seller_id, product_id) pairs generated", len(grain)),
        (f"of which evidence sufficient (units >= {params.evidence_min_units})", sufficient),
        ("of which evidence insufficient", len(grain) - sufficient),
    ]


def build_sales_base(
    order_lines: pd.DataFrame, orders: pd.DataFrame, params: GeneratorParams
) -> pd.DataFrame:
    """Aggregate real sales to seller-product grain. Contains no randomness.

    Args:
        order_lines: Processed order lines with a ``quantity`` column.
        orders: Processed orders carrying status and purchase timestamp.
        params: Window, exclusions and evidence threshold.

    Returns:
        One row per selling (seller_id, product_id) with the real-derived
        columns listed in :data:`REAL_COLUMNS`, sorted for reproducibility.
    """
    eligible = _eligible_lines(order_lines, orders, params)
    base = eligible.groupby(["seller_id", "product_id"], as_index=False).agg(
        units_sold=("quantity", "sum"),
        first_sale_date=("order_purchase_timestamp", "min"),
    )
    base["units_sold"] = base["units_sold"].astype("int64")
    base["first_sale_date"] = base["first_sale_date"].dt.normalize()

    elapsed = (pd.Timestamp(params.as_of) - base["first_sale_date"]).dt.days
    base["active_days"] = np.maximum(params.min_active_days, elapsed).astype("int64")
    base["daily_sales_rate"] = base["units_sold"] / base["active_days"]
    base["evidence"] = np.where(
        base["units_sold"] >= params.evidence_min_units, "sufficient", "insufficient"
    )

    base = base.sort_values(["seller_id", "product_id"], ignore_index=True)
    logger.info("sales base: %d seller-product pairs from real orders", len(base))
    return base


def assign_lead_times(
    sellers: pd.Series, rng: np.random.Generator, params: GeneratorParams
) -> pd.DataFrame:
    """Draw one lead time per seller, not per row.

    Lead time is a property of a supplier relationship, so every product from
    the same seller must share it. Drawing per row would let one seller hold
    twenty different lead times, which no real supplier does.

    Returns:
        Columns ``seller_id`` and ``lead_time_days``.
    """
    unique = np.sort(sellers.unique())
    low, high = params.lead_time_range
    return pd.DataFrame(
        {
            "seller_id": unique,
            "lead_time_days": rng.integers(low, high + 1, size=len(unique)).astype("int64"),
        }
    )


def add_synthetic_stock(
    base: pd.DataFrame,
    lead_times: pd.DataFrame,
    rng: np.random.Generator,
    params: GeneratorParams,
) -> pd.DataFrame:
    """Attach lead time, reorder point, current stock and last restock date.

    The reorder point is deliberately a function of the *real* sales rate, so a
    fast-selling product gets a larger trigger than a slow one. Only the stock
    multiplier and the restock date are random.

    Returns:
        ``base`` plus the synthetic columns and ``reorder_point``.
    """
    out = base.merge(lead_times, on="seller_id", how="left", validate="many_to_one")

    cover_days = out["lead_time_days"] + params.safety_days
    out["reorder_point"] = np.maximum(1, np.ceil(out["daily_sales_rate"] * cover_days)).astype(
        "int64"
    )

    low, high = params.stock_factor_range
    factor = rng.uniform(low, high, size=len(out))
    out["current_quantity"] = np.round(out["reorder_point"] * factor).astype("int64")

    lo_days, hi_days = params.restock_lookback_days
    offset = rng.integers(lo_days, hi_days + 1, size=len(out))
    out["last_restock_date"] = pd.Timestamp(params.as_of) - pd.to_timedelta(offset, unit="D")
    return out


def classify_status(df: pd.DataFrame, params: GeneratorParams) -> pd.DataFrame:
    """Add ``days_of_inventory`` and the restock ``status``.

    Weak-evidence rows are labelled rather than scored, because a status derived
    from one or two sales would look like a finding while being noise.

    Returns:
        ``df`` plus ``days_of_inventory``, ``status`` and ``is_synthetic``.
    """
    out = df.copy()
    rate = out["daily_sales_rate"].to_numpy()
    out["days_of_inventory"] = np.where(
        rate > 0, out["current_quantity"].to_numpy() / np.where(rate > 0, rate, 1), np.inf
    )

    lead = out["lead_time_days"].to_numpy()
    doi = out["days_of_inventory"].to_numpy()
    status = np.where(
        out["evidence"].to_numpy() == "insufficient",
        STATUS_INSUFFICIENT,
        np.where(
            doi < lead,
            STATUS_URGENT,
            np.where(doi < lead + params.monitor_extra_days, STATUS_MONITOR, STATUS_HEALTHY),
        ),
    )
    out["status"] = status
    out["is_synthetic"] = True
    return out


def generate_synthetic_inventory(
    order_lines: pd.DataFrame,
    orders: pd.DataFrame,
    params: GeneratorParams | None = None,
) -> pd.DataFrame:
    """Build the whole synthetic inventory table from real order data.

    Deterministic: the same inputs and the same ``params.seed`` always produce an
    identical table, which is what makes the output hashable and reviewable.

    Args:
        order_lines: Processed order lines.
        orders: Processed orders.
        params: Generator settings. Defaults to the documented constants.

    Returns:
        One row per (seller_id, product_id), sorted by that key.
    """
    params = params or GeneratorParams()
    rng = np.random.default_rng(params.seed)

    base = build_sales_base(order_lines, orders, params)
    lead_times = assign_lead_times(base["seller_id"], rng, params)
    with_stock = add_synthetic_stock(base, lead_times, rng, params)
    out = classify_status(with_stock, params)

    ordered = [
        *REAL_COLUMNS,
        "lead_time_days",
        "reorder_point",
        "current_quantity",
        "last_restock_date",
        "days_of_inventory",
        "status",
        "is_synthetic",
    ]
    out = out[ordered].sort_values(["seller_id", "product_id"], ignore_index=True)
    logger.info(
        "generated %d synthetic inventory rows (seed=%d): %s",
        len(out),
        params.seed,
        out["status"].value_counts().to_dict(),
    )
    return out
