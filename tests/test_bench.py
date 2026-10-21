"""Tests for the optimisation study.

Two things here must be trustworthy or the whole study is worthless: the
harness must actually notice when a strategy returns the wrong answer, and the
alternative implementations must agree with each other on input small enough to
verify by hand. Those are the first two groups below.

The fixtures stay tiny for the same reason as the rest of the suite -- a
co-occurrence rule that needs 100k rows to check is one we cannot reason about.
Performance itself is deliberately *not* asserted: timings vary with the machine
and a test that fails on a busy laptop teaches nothing.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from ecom.bench import fragmentation as frag
from ecom.bench import studies
from ecom.bench.harness import outputs_match, run_workload, time_callable
from ecom.bench.workloads import (
    COOCCURRENCE_STRATEGIES,
    ROW_COUNT_STRATEGIES,
    cooccur_nested_loop,
)


@pytest.fixture
def order_products() -> pd.DataFrame:
    """Four baskets with hand-checkable pair counts.

    o1 and o2 both contain (p1, p2), so that pair must come out with count 2.
    o3 is a single-product basket and must contribute nothing. o4 contains
    three products and so must yield three distinct pairs.
    """
    return pd.DataFrame(
        {
            "order_id": ["o1", "o1", "o2", "o2", "o3", "o4", "o4", "o4"],
            "product_id": ["p1", "p2", "p1", "p2", "p9", "p1", "p3", "p4"],
        }
    )


@pytest.fixture
def fact() -> pd.DataFrame:
    """Six fact rows across two months and two sellers."""
    return pd.DataFrame(
        {
            "row_id": range(6),
            "order_id": ["o1", "o2", "o3", "o4", "o5", "o6"],
            "product_id": ["p1", "p2", "p1", "p3", "p2", "p1"],
            "seller_id": ["s1", "s1", "s2", "s2", "s1", "s2"],
            "quantity": [1, 2, 1, 1, 3, 1],
            "unit_price": [10.0, 5.0, 20.0, 7.5, 5.0, 20.0],
            "line_revenue": [10.0, 10.0, 20.0, 7.5, 15.0, 20.0],
            "line_freight": [1.0, 1.0, 2.0, 0.5, 1.5, 2.0],
            "shipping_limit_date": pd.to_datetime(["2017-02-05"] * 3 + ["2017-03-05"] * 3),
            "order_purchase_timestamp": pd.to_datetime(
                ["2017-02-01", "2017-02-10", "2017-02-20", "2017-03-01", "2017-03-10", "2017-03-20"]
            ),
            "customer_id": ["c1", "c2", "c3", "c4", "c5", "c6"],
            "order_month": ["2017-02"] * 3 + ["2017-03"] * 3,
        }
    )


# ------------------------------------------------------------- A. the harness
# If these fail, every number the study reports is unverified.


def test_harness_detects_a_wrong_answer() -> None:
    """A strategy returning different output must be flagged, not reported as a win."""
    frame = pd.DataFrame({"a": [1, 2, 3]})
    result = run_workload(
        workload="t",
        concept="t",
        input_rows=3,
        trials=2,
        strategies=[
            ("baseline", lambda: frame.assign(b=frame["a"] * 2)),
            ("wrong", lambda: frame.assign(b=frame["a"] * 3)),
        ],
    )
    assert result.measurements[1].matches_baseline is False
    assert result.measurements[1].ok is False


def test_harness_excludes_a_wrong_strategy_from_best() -> None:
    """``best()`` must never return a strategy that disagreed, however fast."""
    frame = pd.DataFrame({"a": range(500)})
    result = run_workload(
        workload="t",
        concept="t",
        input_rows=500,
        trials=2,
        strategies=[
            ("baseline", lambda: frame.assign(b=frame["a"].apply(lambda v: v * 2))),
            ("fast_and_wrong", lambda: frame.assign(b=frame["a"])),
        ],
    )
    best = result.best()
    assert best is not None
    assert best.name == "baseline"


def test_harness_records_a_failure_without_raising() -> None:
    """A broken strategy is a result; it must not abort the whole study."""

    def explode() -> None:
        raise RuntimeError("no optional dependency")

    result = run_workload(
        workload="t",
        concept="t",
        input_rows=1,
        trials=2,
        strategies=[("baseline", lambda: pd.DataFrame({"a": [1]})), ("broken", explode)],
    )
    assert "RuntimeError" in result.measurements[1].failed
    assert result.speedup(result.measurements[1]) == 0.0


def test_outputs_match_ignores_row_order_but_not_values() -> None:
    """Join strategies may emit rows in any order; different values are not equal."""
    left = pd.DataFrame({"a": ["x", "y"], "n": [1, 2]})
    assert outputs_match(left, left.iloc[::-1])
    assert not outputs_match(left, pd.DataFrame({"a": ["x", "y"], "n": [1, 3]}))


def test_outputs_match_treats_null_flavours_as_equal() -> None:
    """pd.NA from a pandas reader and None from an Arrow kernel are one answer."""
    assert outputs_match(
        pd.Series(["a", pd.NA], dtype="string"), pd.Series(["a", None], dtype="object")
    )


def test_time_callable_runs_a_warmup_plus_every_trial() -> None:
    calls = []
    time_callable(lambda: calls.append(1), trials=4)
    assert len(calls) == 5, "one discarded warm-up plus four measured trials"


# ----------------------------------------------- B. the strategies agree
# Every alternative must return exactly what the baseline returns.


def test_cooccurrence_baseline_counts_pairs_correctly(order_products: pd.DataFrame) -> None:
    """Pin the expected answer by hand before trusting any alternative to it."""
    pairs = cooccur_nested_loop(order_products).set_index(["product_a", "product_b"])
    assert pairs.loc[("p1", "p2"), "order_count"] == 2, "o1 and o2 both hold this pair"
    assert pairs.loc[("p1", "p3"), "order_count"] == 1
    assert len(pairs) == 4, "one repeated pair plus the three from the triple basket"
    assert "p9" not in pairs.index.get_level_values(0), "a single-product basket makes no pair"


@pytest.mark.parametrize("name,strategy", COOCCURRENCE_STRATEGIES[1:])
def test_every_cooccurrence_strategy_matches_the_baseline(
    name: str, strategy, order_products: pd.DataFrame
) -> None:
    assert outputs_match(cooccur_nested_loop(order_products), strategy(order_products)), name


@pytest.mark.parametrize("name,strategy", COOCCURRENCE_STRATEGIES)
def test_cooccurrence_emits_each_pair_once_in_sorted_order(
    name: str, strategy, order_products: pd.DataFrame
) -> None:
    """``product_a < product_b`` is the stored-once contract every strategy owes."""
    pairs = strategy(order_products)
    assert (pairs["product_a"] < pairs["product_b"]).all(), name
    assert not pairs.duplicated(["product_a", "product_b"]).any(), name


@pytest.mark.parametrize("name,strategy", COOCCURRENCE_STRATEGIES)
def test_cooccurrence_handles_no_multi_product_baskets(name: str, strategy) -> None:
    """Olist is 96.7% single-product baskets, so the empty case is the common edge."""
    singles = pd.DataFrame({"order_id": ["o1", "o2"], "product_id": ["p1", "p2"]})
    assert len(strategy(singles)) == 0, name


def test_unsafe_row_counter_disagrees_on_embedded_newlines(tmp_path: Path) -> None:
    """The fast counter must be shown to be wrong, not assumed to be right.

    This is the behaviour that justifies the harness checking answers at all:
    counting newline bytes overcounts any CSV with a newline inside a quoted
    field, which the real Olist reviews file has 5,495 of.
    """
    path = tmp_path / "quoted.csv"
    path.write_text('id,comment\n1,"line one\nline two"\n2,"plain"\n')
    answers = {name: fn(path) for name, fn in ROW_COUNT_STRATEGIES}
    assert answers["csv_reader_python"] == 2
    assert answers["arrow_csv_native"] == 2
    assert answers["newline_bytes_unsafe"] == 3, "overcounts by the embedded newline"


# --------------------------------------------------- C. layouts and fragments


@pytest.mark.parametrize("layout", ["monolithic", "horizontal", "vertical", "sharded_4"])
def test_every_layout_answers_the_same_queries_identically(
    layout: str, fact: pd.DataFrame, tmp_path: Path
) -> None:
    """A layout that is fast and wrong must not be reportable as a win."""
    root = tmp_path / layout
    shards = 0
    if layout == "monolithic":
        frag.write_monolithic(fact, root)
    elif layout == "horizontal":
        frag.write_horizontal(fact, root)
    elif layout == "vertical":
        frag.write_vertical(fact, root)
    else:
        shards = 4
        frag.write_sharded(fact, root, shards)

    seller = "s1"
    expected_total = float(fact["line_revenue"].sum())
    expected_month = float(fact.loc[fact["order_month"] == "2017-02", "line_revenue"].sum())
    expected_seller = float(fact.loc[fact["seller_id"] == seller, "line_revenue"].sum())

    assert frag.q_total_revenue(root, layout).answer == pytest.approx(expected_total)
    assert frag.q_revenue_for_months(root, ["2017-02"], layout).answer == pytest.approx(
        expected_month
    )
    assert frag.q_revenue_for_seller(root, seller, layout, shards).answer == pytest.approx(
        expected_seller
    )


def test_horizontal_layout_reads_fewer_bytes_for_a_partition_predicate(
    fact: pd.DataFrame, tmp_path: Path
) -> None:
    """Pruning must be visible in bytes, which the page cache cannot flatter."""
    mono, horiz = tmp_path / "m", tmp_path / "h"
    frag.write_monolithic(fact, mono)
    frag.write_horizontal(fact, horiz)
    pruned = frag.q_revenue_for_months(horiz, ["2017-02"], "horizontal").bytes_read
    full = frag.q_revenue_for_months(mono, ["2017-02"], "monolithic").bytes_read
    assert pruned < full


def test_horizontal_layout_writes_one_file_per_partition(
    fact: pd.DataFrame, tmp_path: Path
) -> None:
    stats = frag.write_horizontal(fact, tmp_path / "h")
    assert stats.file_count == fact["order_month"].nunique()


def test_sharding_is_stable_across_processes(fact: pd.DataFrame) -> None:
    """Python's salted hash() would make a layout unreadable on the next run."""
    first = frag._shard_of(fact["seller_id"], 8)
    second = frag._shard_of(fact["seller_id"], 8)
    assert list(first) == list(second)
    assert set(first) <= set(range(8))


def test_build_fact_table_keeps_only_delivered_rows_inside_the_window() -> None:
    order_lines = pd.DataFrame(
        {
            "order_id": ["o1", "o2", "o3"],
            "product_id": ["p1", "p1", "p1"],
            "seller_id": ["s1", "s1", "s1"],
            "quantity": [1, 1, 1],
            "line_revenue": [10.0, 10.0, 10.0],
        }
    )
    orders = pd.DataFrame(
        {
            "order_id": ["o1", "o2", "o3"],
            "order_purchase_timestamp": pd.to_datetime(["2017-06-01", "2017-06-02", "2016-11-01"]),
            "is_delivered": [True, False, True],
            "customer_id": ["c1", "c2", "c3"],
        }
    )
    out = frag.build_fact_table(
        order_lines, orders, pd.Timestamp("2017-02-01"), pd.Timestamp("2018-08-31")
    )
    assert list(out["order_id"]) == ["o1"], "o2 undelivered, o3 before the window"
    assert out["order_month"].iloc[0] == "2017-06"


# ------------------------------------------------------------- D. the studies


def test_replicate_fact_scales_rows_and_keeps_keys_distinct(fact: pd.DataFrame) -> None:
    """Repeating rows verbatim would make group-bys cheaper as data grew."""
    scaled = frag.replicate_fact(fact, 4)
    assert len(scaled) == 4 * len(fact)
    assert scaled["seller_id"].nunique() == 4 * fact["seller_id"].nunique()
    assert scaled["row_id"].is_unique


def test_replicate_order_products_preserves_basket_shapes() -> None:
    order_products = pd.DataFrame(
        {"order_id": ["o1", "o1", "o2"], "product_id": ["p1", "p2", "p3"]}
    )
    scaled = studies.replicate_order_products(order_products, 3)
    assert len(scaled) == 9
    assert scaled.groupby("order_id").size().max() == 2, "basket sizes must not change"
    assert scaled["order_id"].nunique() == 6


def test_crossover_point_interpolates_between_the_bracketing_samples() -> None:
    sweep = pd.DataFrame({"selectivity_pct": [10.0, 50.0, 90.0], "speedup": [3.0, 2.0, 0.0]})
    # The curve passes 1.0 halfway between the 50% and 90% samples.
    assert studies.crossover_point(sweep) == pytest.approx(70.0)


def test_crossover_point_is_none_when_the_curve_never_crosses() -> None:
    always_faster = pd.DataFrame({"selectivity_pct": [10.0, 90.0], "speedup": [3.0, 2.0]})
    assert studies.crossover_point(always_faster) is None


def test_fit_scaling_exponent_recovers_a_known_power_law() -> None:
    """A quadratic strategy must fit k near 2, or the scaling column is noise."""
    rows = [
        {"strategy": "quadratic", "input_rows": n, "seconds": (n / 1000) ** 2}
        for n in (1000, 2000, 4000, 8000)
    ]
    assert studies.fit_scaling_exponent(pd.DataFrame(rows), "quadratic") == pytest.approx(
        2.0, abs=0.01
    )


def test_fit_scaling_exponent_needs_two_points() -> None:
    one = pd.DataFrame([{"strategy": "x", "input_rows": 10, "seconds": 1.0}])
    assert studies.fit_scaling_exponent(one, "x") is None


# -------------------------------------------- E. the landed optimisation
# The fast reader is a performance switch only. If it changes a value, it is a
# variant and must not be offered as a flag.


def test_fast_reader_returns_exactly_what_the_pandas_reader_returns(tmp_path: Path) -> None:
    from ecom.storage.local import LocalStorage

    storage = LocalStorage(tmp_path / "raw", tmp_path / "processed")
    # An empty trailing field is the case that separates the two readers: Arrow
    # defaults to reading it as "" rather than null.
    storage.put_bytes(
        "raw/olist/t.csv",
        b"order_id,order_status,approved_at\no1,delivered,2017-05-01 10:00:00\no2,shipped,\n",
    )
    pandas_frame = storage.get_csv("raw/olist/t.csv", dtype="string", encoding="utf-8-sig")
    arrow_frame = storage.get_csv_arrow("raw/olist/t.csv")

    assert list(arrow_frame.columns) == list(pandas_frame.columns)
    assert outputs_match(pandas_frame, arrow_frame)
    assert arrow_frame["approved_at"].isna().sum() == 1, "the empty field must stay null"


def test_fast_reader_keeps_the_processed_layer_identical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The flag's whole claim is that it changes timing and nothing else."""
    pytest.importorskip("pyarrow")
    from ecom.cleaning.run_clean import _load_raw
    from ecom.contracts import ORDERS
    from ecom.storage.local import LocalStorage

    storage = LocalStorage(tmp_path / "raw", tmp_path / "processed")
    header = ",".join(["order_id", "customer_id", "order_status", "order_purchase_timestamp"])
    rows = "\n".join(f"o{i},c{i},delivered,2017-0{(i % 9) + 1}-01 08:00:00" for i in range(1, 20))
    storage.put_bytes("raw/olist/orders.csv", f"{header}\n{rows}\n".encode())

    baseline = _load_raw(storage, ORDERS, fast_reader=False)
    fast = _load_raw(storage, ORDERS, fast_reader=True)
    assert outputs_match(baseline, fast[baseline.columns])


def test_trim_whitespace_still_strips_arrow_backed_columns() -> None:
    """The fast reader produces string[pyarrow]; the trim must not silently skip it."""
    from ecom.cleaning.transforms import trim_whitespace

    frame = pd.DataFrame({"a": ["  x  ", "y"]}, dtype="string[pyarrow]")
    assert list(trim_whitespace(frame)["a"]) == ["x", "y"]


def test_shard_recommendation_respects_the_storage_budget() -> None:
    """The fastest layout tested is always the most-sharded and most expensive.

    A recommendation built on ``idxmax`` would name 4,096 shards and its 79.7%
    storage cost every time. The study instead takes the smallest shard count
    on the speedup plateau that also fits a declared storage budget.
    """
    sweep = pd.DataFrame(
        [
            {"shards": 1, "layout": "monolithic", "speedup": 1.0, "storage_overhead_pct": 0.0},
            {"shards": 4, "layout": "sharded_4", "speedup": 5.8, "storage_overhead_pct": -0.9},
            {"shards": 16, "layout": "sharded_16", "speedup": 13.9, "storage_overhead_pct": 1.6},
            {"shards": 64, "layout": "sharded_64", "speedup": 20.7, "storage_overhead_pct": 5.0},
            {"shards": 256, "layout": "sharded_256", "speedup": 23.2, "storage_overhead_pct": 9.8},
            {
                "shards": 1024,
                "layout": "sharded_1024",
                "speedup": 27.0,
                "storage_overhead_pct": 25.6,
            },
            {
                "shards": 4096,
                "layout": "sharded_4096",
                "speedup": 27.8,
                "storage_overhead_pct": 79.7,
            },
        ]
    )
    pick = studies.shard_recommendation(sweep)
    assert pick["recommended_shards"] == 64, "smallest count on the plateau, inside budget"
    assert pick["recommended_storage_overhead_pct"] <= studies.STORAGE_BUDGET_PCT
    assert pick["fastest_shards"] == 4096, "the argmax is reported, not recommended"
    assert pick["fastest_storage_overhead_pct"] > studies.STORAGE_BUDGET_PCT


def test_shard_recommendation_is_stable_against_timing_noise() -> None:
    """The recommendation must not move when a single speedup wobbles.

    This is why the storage budget replaced a derivative threshold: the gain
    between adjacent shard counts is a ratio of sub-10 ms timings, and one
    noisy point moved the old answer between 64 and 1,024 shards.
    """
    base = [
        {"shards": 1, "layout": "monolithic", "speedup": 1.0, "storage_overhead_pct": 0.0},
        {"shards": 64, "layout": "sharded_64", "speedup": 24.3, "storage_overhead_pct": 5.0},
        {"shards": 256, "layout": "sharded_256", "speedup": 24.2, "storage_overhead_pct": 9.8},
        {"shards": 1024, "layout": "sharded_1024", "speedup": 25.9, "storage_overhead_pct": 25.6},
    ]
    noisy = [dict(row) for row in base]
    noisy[2]["speedup"] = 20.1  # the 256-shard point measured slow this run
    first = studies.shard_recommendation(pd.DataFrame(base))
    second = studies.shard_recommendation(pd.DataFrame(noisy))
    assert first["recommended_shards"] == second["recommended_shards"] == 64
