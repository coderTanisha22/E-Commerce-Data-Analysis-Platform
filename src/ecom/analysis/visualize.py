"""Figure generation for the analysis report.

One visual system across every figure: a single accent hue for magnitude, the
reserved status hues only for genuine status, recessive axes, and a directly
labelled value on every bar so a figure is readable without a legend. Charts are
written as PNG into ``reports/figures``.
"""

from __future__ import annotations

import logging
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless: no display on a pipeline worker
import matplotlib.pyplot as plt
import pandas as pd

logger = logging.getLogger(__name__)

# One palette, shared with the written report so figures and prose match.
ACCENT = "#35618C"
CRITICAL = "#B02418"
WARNING = "#C08A00"
INK = "#151A21"
MUTED = "#68747F"
RULE = "#D3DAE1"
PAPER = "#FFFFFF"

FIGURE_DPI = 150


def _style_axes(ax: plt.Axes, *, xlabel: str = "", ylabel: str = "") -> None:
    """Apply the shared recessive-axis treatment."""
    ax.set_facecolor(PAPER)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(RULE)
    ax.tick_params(colors=MUTED, labelsize=9, length=0)
    ax.set_xlabel(xlabel, color=MUTED, fontsize=9)
    ax.set_ylabel(ylabel, color=MUTED, fontsize=9)
    ax.grid(axis="x", color=RULE, linewidth=0.6, alpha=0.7)
    ax.set_axisbelow(True)


def _new_figure(
    title: str, subtitle: str, size: tuple[float, float]
) -> tuple[plt.Figure, plt.Axes]:
    """Create a figure with the shared title block."""
    fig, ax = plt.subplots(figsize=size, facecolor=PAPER)
    fig.suptitle(title, x=0.02, ha="left", fontsize=12.5, fontweight="bold", color=INK)
    ax.set_title(subtitle, loc="left", fontsize=9.5, color=MUTED, pad=10)
    return fig, ax


def _save(fig: plt.Figure, path: Path) -> Path:
    """Write and close a figure."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.savefig(path, dpi=FIGURE_DPI, facecolor=PAPER, bbox_inches="tight")
    plt.close(fig)
    logger.info("wrote %s", path)
    return path


def plot_distribution(
    distribution: dict[int, int],
    *,
    title: str,
    subtitle: str,
    key_label: str,
    out_path: Path,
    limit: int = 8,
) -> Path:
    """Draw a horizontal bar chart of a small integer-keyed distribution.

    A linear scale is deliberate where one bar dominates: the imbalance is the
    finding, and a log scale would hide it.

    Args:
        distribution: Mapping of bucket to count.
        title: Figure title.
        subtitle: One-line explanation under the title.
        key_label: Noun for the bucket, e.g. "products".
        out_path: Destination PNG path.
        limit: Maximum buckets to draw, lowest keys first.

    Returns:
        The path written.
    """
    items = sorted(distribution.items())[:limit]
    labels = [f"{key} {key_label}" for key, _ in items]
    values = [count for _, count in items]

    fig, ax = _new_figure(title, subtitle, (7.4, 0.46 * len(items) + 1.7))
    positions = range(len(items))
    ax.barh(list(positions), values, color=ACCENT, height=0.62)
    ax.set_yticks(list(positions), labels)
    ax.invert_yaxis()
    _style_axes(ax, xlabel="orders" if "order" in key_label else "count")

    span = max(values) if values else 1
    for slot, value in zip(positions, values, strict=True):
        ax.text(
            value + span * 0.012,
            slot,
            f"{value:,}",
            va="center",
            fontsize=9,
            color=INK,
            fontfamily="monospace",
        )
    ax.set_xlim(0, span * 1.14)
    return _save(fig, out_path)


def plot_monthly_orders(
    orders_by_month: dict[str, int], *, out_path: Path, usable_from: str, usable_to: str
) -> Path:
    """Draw monthly order volume, marking the months outside the usable window.

    Status colour is used here for genuine status - months excluded from the
    analysis window - and every marked bar is also named in the legend, so the
    distinction never rests on colour alone.
    """
    series = pd.Series(orders_by_month)
    series.index = pd.to_datetime(series.index)
    series = series.sort_index()

    start, end = pd.Timestamp(usable_from), pd.Timestamp(usable_to)
    colors = [ACCENT if start <= idx <= end else WARNING for idx in series.index]

    fig, ax = _new_figure(
        "Orders per month",
        f"Months outside {usable_from} to {usable_to} are excluded from every velocity figure",
        (8.6, 3.5),
    )
    ax.bar(series.index, series.to_numpy(), width=22, color=colors)
    _style_axes(ax, ylabel="orders")
    ax.grid(axis="y", color=RULE, linewidth=0.6, alpha=0.7)
    ax.grid(axis="x", visible=False)

    peak = series.idxmax()
    ax.annotate(
        f"{series.max():,}",
        xy=(peak, series.max()),
        xytext=(0, 5),
        textcoords="offset points",
        ha="center",
        fontsize=9,
        color=INK,
        fontfamily="monospace",
    )
    handles = [
        plt.Rectangle((0, 0), 1, 1, color=ACCENT),
        plt.Rectangle((0, 0), 1, 1, color=WARNING),
    ]
    ax.legend(
        handles,
        ["Inside analysis window", "Excluded (sparse start / truncated tail)"],
        frameon=False,
        fontsize=8.5,
        labelcolor=MUTED,
        loc="upper left",
    )
    return _save(fig, out_path)


def plot_graph_shape(cooccurrence: dict[str, object], *, out_path: Path) -> Path:
    """Draw the reachability of the co-occurrence graph as a share of catalogue.

    A single stacked bar rather than a pie: the comparison is one part against a
    whole, and a bar keeps both values directly labelled.
    """
    nodes = int(cooccurrence["graph_nodes"])
    total = int(cooccurrence["catalogue_products"])
    unreachable = total - nodes

    fig, ax = _new_figure(
        "Recommendation coverage",
        f"Only {nodes:,} of {total:,} products appear in any product pair",
        (8.0, 1.9),
    )
    ax.barh([0], [nodes], color=ACCENT, height=0.46)
    ax.barh([0], [unreachable], left=[nodes], color=RULE, height=0.46)
    ax.set_yticks([])
    ax.set_xlim(0, total)
    ax.set_ylim(-0.75, 0.55)
    _style_axes(ax, xlabel="products")
    ax.grid(visible=False)

    # Direct labels rather than a legend: a legend box inside a single stacked
    # bar overlaps the marks it describes and becomes unreadable on the fill.
    ax.text(
        nodes / 2,
        0,
        f"{100 * nodes / total:.1f}%",
        ha="center",
        va="center",
        color=PAPER,
        fontsize=10,
        fontweight="bold",
    )
    ax.text(
        nodes + total * 0.015,
        0,
        f"{unreachable:,} products have no neighbours",
        ha="left",
        va="center",
        color=INK,
        fontsize=9.5,
    )
    ax.annotate(
        f"in graph: {nodes:,}",
        xy=(nodes / 2, -0.28),
        ha="center",
        va="top",
        fontsize=8.5,
        color=ACCENT,
    )
    return _save(fig, out_path)


def _sections(profile: dict[str, object]) -> tuple[dict, dict, dict]:
    """Unpack the profile into the three sections the figures need.

    ``catalogue_products`` is folded into the co-occurrence section so the
    coverage figure can express nodes as a share of the whole catalogue.
    """
    cooc = dict(profile["cooccurrence"])  # type: ignore[arg-type]
    cooc["catalogue_products"] = profile["catalogue"]["products"]  # type: ignore[index]
    return cooc, profile["sales"], profile["velocity"]  # type: ignore[return-value]


def render_all(profile: dict[str, object], *, figures_dir: Path) -> list[Path]:
    """Render every figure for the analysis report.

    Args:
        profile: Output of :func:`ecom.analysis.profile.build_profile`.
        figures_dir: Directory to write PNGs into.

    Returns:
        Paths written, in render order.
    """
    cooc, sales, velocity = _sections(profile)
    return [
        plot_distribution(
            cooc["basket_size_distribution"],  # type: ignore[arg-type]
            title="Distinct products per order",
            subtitle=(
                f"{cooc['multi_product_share_pct']}% of orders contain two or more products - "
                "the entire basis of the graph"
            ),
            key_label="products",
            out_path=figures_dir / "01_basket_size.png",
        ),
        plot_distribution(
            cooc["pair_weight_distribution"],  # type: ignore[arg-type]
            title="Product pair weight",
            subtitle=(
                f"{cooc['weight_1_share_pct']}% of {cooc['pairs_total']:,} pairs were bought "
                "together exactly once"
            ),
            key_label="shared orders",
            out_path=figures_dir / "02_pair_weight.png",
        ),
        plot_monthly_orders(
            sales["orders_by_month"],  # type: ignore[arg-type]
            out_path=figures_dir / "03_monthly_orders.png",
            usable_from=str(sales["window_start"]),
            usable_to=str(sales["window_end"]),
        ),
        plot_graph_shape(cooc, out_path=figures_dir / "04_coverage.png"),
        plot_distribution(
            velocity["units_distribution_head"],  # type: ignore[arg-type]
            title="Units sold per seller-product",
            subtitle=(
                f"{velocity['sold_once_share_pct']}% sold exactly one unit in the window, "
                "which is why velocity alone cannot drive restocking"
            ),
            key_label="units",
            out_path=figures_dir / "05_units_sold.png",
        ),
    ]
