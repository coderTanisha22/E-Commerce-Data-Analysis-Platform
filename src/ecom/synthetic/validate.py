"""Validation evidence for the synthetic inventory table.

Produces the three things a reader needs in order to trust generated data:
whether conclusions survive a change of seed (stability), whether the rule reacts
sensibly to its own parameters (sensitivity), and whether the synthetic stock is
anchored to the real sales rate (faithfulness).
"""

from __future__ import annotations

import logging
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from ecom.synthetic.inventory import (
    GeneratorParams,
    generate_synthetic_inventory,
)
from ecom.synthetic.run_generate import frame_digest

logger = logging.getLogger(__name__)

ACCENT = "#35618C"
CRITICAL = "#B02418"
WARNING = "#C08A00"
GOOD = "#2E7D57"
MUTED = "#68747F"
RULE = "#D3DAE1"
PAPER = "#FFFFFF"
STATUSES = ("Urgent", "Monitor", "Healthy", "Insufficient data")


def status_shares(table: pd.DataFrame) -> dict[str, float]:
    """Return each status as a percentage of all rows."""
    counts = table["status"].value_counts()
    return {s: round(100 * counts.get(s, 0) / len(table), 3) for s in STATUSES}


def seed_stability(order_lines: pd.DataFrame, orders: pd.DataFrame, seeds: range) -> pd.DataFrame:
    """Regenerate under many seeds and summarise how much the shares move.

    A small standard deviation is the evidence that a conclusion drawn from the
    table is a property of the data, not of one lucky random draw.
    """
    rows = []
    for seed in seeds:
        table = generate_synthetic_inventory(order_lines, orders, GeneratorParams(seed=seed))
        rows.append({"seed": seed, **status_shares(table)})
    return pd.DataFrame(rows)


def sensitivity(order_lines: pd.DataFrame, orders: pd.DataFrame) -> pd.DataFrame:
    """Vary one parameter at a time and record how the status shares respond."""
    cases: list[tuple[str, str, GeneratorParams]] = []
    for safety in (0, 3, 7):
        cases.append(("safety_days", str(safety), GeneratorParams(safety_days=safety)))
    for rng_pair in ((0.2, 3.0), (0.5, 2.0), (0.1, 4.0)):
        cases.append(
            ("stock_factor_range", str(rng_pair), GeneratorParams(stock_factor_range=rng_pair))
        )
    for lead in ((3, 10), (5, 20), (10, 30)):
        cases.append(("lead_time_range", str(lead), GeneratorParams(lead_time_range=lead)))

    rows = []
    for parameter, value, params in cases:
        table = generate_synthetic_inventory(order_lines, orders, params)
        shares = status_shares(table)
        rows.append(
            {
                "parameter": parameter,
                "value": value,
                **shares,
                "median_reorder_point": float(table["reorder_point"].median()),
                "median_days_of_inventory": round(float(table["days_of_inventory"].median()), 1),
            }
        )
    return pd.DataFrame(rows)


def reproducibility_check(order_lines: pd.DataFrame, orders: pd.DataFrame) -> dict:
    """Confirm one seed reproduces exactly and another seed does not."""
    a = frame_digest(generate_synthetic_inventory(order_lines, orders, GeneratorParams(seed=42)))
    b = frame_digest(generate_synthetic_inventory(order_lines, orders, GeneratorParams(seed=42)))
    c = frame_digest(generate_synthetic_inventory(order_lines, orders, GeneratorParams(seed=7)))
    return {
        "seed_42_run_1": a,
        "seed_42_run_2": b,
        "seed_7": c,
        "identical": a == b,
        "differs_across_seeds": a != c,
    }


def real_data_untouched(order_lines: pd.DataFrame, orders: pd.DataFrame) -> dict:
    """Hash the real inputs before and after generation to prove we never wrote to them."""
    before = (frame_digest(order_lines), frame_digest(orders))
    generate_synthetic_inventory(order_lines, orders, GeneratorParams())
    after = (frame_digest(order_lines), frame_digest(orders))
    return {
        "order_lines_unchanged": before[0] == after[0],
        "orders_unchanged": before[1] == after[1],
        "order_lines_sha256": before[0],
        "orders_sha256": before[1],
    }


# ------------------------------------------------------------------- figures


def _style(ax: plt.Axes, xlabel: str = "", ylabel: str = "") -> None:
    ax.set_facecolor(PAPER)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(RULE)
    ax.tick_params(colors=MUTED, labelsize=8)
    ax.set_xlabel(xlabel, color=MUTED, fontsize=9)
    ax.set_ylabel(ylabel, color=MUTED, fontsize=9)
    ax.grid(axis="y", color=RULE, linewidth=0.6, alpha=0.7)
    ax.set_axisbelow(True)


def plot_distributions(table: pd.DataFrame, out_dir: Path) -> Path:
    """Real sales rate beside synthetic stock, both on a log scale."""
    fig, axes = plt.subplots(1, 2, figsize=(9.2, 3.1), facecolor=PAPER)
    axes[0].hist(table["daily_sales_rate"], bins=60, color=ACCENT)
    axes[0].set_yscale("log")
    axes[0].set_title("Real: daily sales rate", fontsize=10, loc="left")
    _style(axes[0], "units per day", "seller-products (log)")

    axes[1].hist(table["current_quantity"], bins=60, color=WARNING)
    axes[1].set_yscale("log")
    axes[1].set_title("Synthetic: current quantity", fontsize=10, loc="left")
    _style(axes[1], "units in stock", "seller-products (log)")

    fig.tight_layout()
    path = out_dir / "inv_01_distributions.png"
    fig.savefig(path, dpi=180, facecolor=PAPER, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_stock_scales_with_speed(table: pd.DataFrame, out_dir: Path) -> Path:
    """Mean reorder point and stock by sales-rate decile.

    The mean is used rather than the median on purpose: because the reorder
    point is an integer with a floor of 1, the median is 1 for nine deciles out
    of ten and hides the relationship entirely. The mean shows the gradient that
    is actually there, and the caption states that most individual values are 1.
    """
    served = table[table["evidence"] == "sufficient"].copy()
    served["decile"] = pd.qcut(served["daily_sales_rate"], 10, labels=False, duplicates="drop")
    grouped = served.groupby("decile").agg(
        rate=("daily_sales_rate", "mean"),
        reorder=("reorder_point", "mean"),
        stock=("current_quantity", "mean"),
    )

    fig, ax = plt.subplots(figsize=(7.2, 3.3), facecolor=PAPER)
    width = 0.38
    positions = np.arange(len(grouped))
    ax.bar(positions - width / 2, grouped["reorder"], width, color=ACCENT, label="Reorder point")
    ax.bar(positions + width / 2, grouped["stock"], width, color=WARNING, label="Current quantity")
    ax.set_xticks(positions, [f"D{i + 1}" for i in range(len(grouped))])
    ax.set_yscale("log")
    ax.set_title(
        "Synthetic stock scales with real sales speed (mean per decile)",
        fontsize=10,
        loc="left",
    )
    _style(ax, "real sales-rate decile, slowest to fastest", "units (log scale)")
    ax.legend(frameon=False, fontsize=8, labelcolor=MUTED, loc="upper left")
    fig.tight_layout()
    path = out_dir / "inv_02_stock_vs_speed.png"
    fig.savefig(path, dpi=180, facecolor=PAPER, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_seed_stability(stability: pd.DataFrame, out_dir: Path) -> Path:
    """Status share per seed, showing how little the conclusion moves."""
    fig, ax = plt.subplots(figsize=(7.4, 3.1), facecolor=PAPER)
    colors = {"Urgent": CRITICAL, "Monitor": WARNING, "Healthy": GOOD}
    for status, color in colors.items():
        ax.plot(
            stability["seed"],
            stability[status],
            marker="o",
            ms=3,
            lw=1.6,
            color=color,
            label=status,
        )
        mean = stability[status].mean()
        ax.axhline(mean, color=color, lw=0.8, ls=":", alpha=0.6)
    ax.set_title("Status share across 30 seeds", fontsize=10, loc="left")
    _style(ax, "seed", "share of all rows (%)")
    ax.legend(frameon=False, fontsize=8, labelcolor=MUTED, ncol=3, loc="upper right")
    fig.tight_layout()
    path = out_dir / "inv_03_seed_stability.png"
    fig.savefig(path, dpi=180, facecolor=PAPER, bbox_inches="tight")
    plt.close(fig)
    return path


def spread(stability: pd.DataFrame) -> pd.DataFrame:
    """Mean and standard deviation of each status share across seeds."""
    return pd.DataFrame(
        {
            "status": list(STATUSES),
            "mean_pct": [round(stability[s].mean(), 3) for s in STATUSES],
            "std_pct": [round(float(np.std(stability[s], ddof=1)), 4) for s in STATUSES],
            "min_pct": [round(stability[s].min(), 3) for s in STATUSES],
            "max_pct": [round(stability[s].max(), 3) for s in STATUSES],
        }
    )


def run_validation(
    order_lines: pd.DataFrame,
    orders: pd.DataFrame,
    table: pd.DataFrame,
    figures_dir: Path,
    seeds: range = range(1, 31),
) -> dict:
    """Run every validation check and render the figures.

    Groups the checks the way the report presents them so a caller gets one
    structure back rather than orchestrating nine functions itself.

    Args:
        order_lines: Processed order lines, the real input.
        orders: Processed orders, the real input.
        table: The generated synthetic inventory table.
        figures_dir: Directory to write the three figures into.
        seeds: Seeds to test stability across.

    Returns:
        Keys ``reproducibility``, ``untouched``, ``stability``, ``spread``,
        ``sensitivity`` and ``figures``.
    """
    figures_dir.mkdir(parents=True, exist_ok=True)
    stability = seed_stability(order_lines, orders, seeds)
    return {
        "reproducibility": reproducibility_check(order_lines, orders),
        "untouched": real_data_untouched(order_lines, orders),
        "stability": stability,
        "spread": spread(stability),
        "sensitivity": sensitivity(order_lines, orders),
        "figures": [
            plot_distributions(table, figures_dir),
            plot_stock_scales_with_speed(table, figures_dir),
            plot_seed_stability(stability, figures_dir),
        ],
    }
