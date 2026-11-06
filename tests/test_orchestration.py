"""Tests for the DAG plan and the gate steps it adds.

The plan is tested here rather than through Airflow, which lives in its own
environment; ``make airflow-test`` runs the real DAG end to end.
"""

from __future__ import annotations

import re
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from ecom.cli import build_parser
from ecom.config import Settings
from ecom.contracts import TableContract
from ecom.ingestion.ingest import IngestionError
from ecom.orchestration.plan import TASKS
from ecom.orchestration.steps import check_sources, reconcile_warehouse
from ecom.quality.checks import DataQualityError
from ecom.quality.reconcile import check_pairs_identical, check_sum_parity
from ecom.storage import LocalStorage

TRACKER_TASK_IDS = {
    "extract_olist",
    "store_raw",
    "spark_clean",
    "dbt_build",
    "validate_models",
    "build_cooccurrence",
    "build_graph",
    "refresh_inventory_metrics",
    "dashboard_ready",
}
"""Fixed by docs/CODING_STANDARDS.md section 9."""


def _upstream_closure(task_id: str) -> set[str]:
    by_id = {task.task_id: task for task in TASKS}
    seen: set[str] = set()
    stack = list(by_id[task_id].upstream)
    while stack:
        current = stack.pop()
        if current not in seen:
            seen.add(current)
            stack.extend(by_id[current].upstream)
    return seen


# ---------------------------------------------------------------- plan


def test_plan_uses_exactly_the_tracker_task_ids() -> None:
    assert {task.task_id for task in TASKS} == TRACKER_TASK_IDS
    assert len(TASKS) == len(TRACKER_TASK_IDS)


def test_plan_upstreams_exist_and_are_declared_first() -> None:
    """Declaring upstreams first proves the graph is acyclic."""
    declared: set[str] = set()
    for task in TASKS:
        assert set(task.upstream) <= declared, task.task_id
        declared.add(task.task_id)


def test_dashboard_ready_waits_for_every_other_task() -> None:
    assert _upstream_closure("dashboard_ready") == TRACKER_TASK_IDS - {"dashboard_ready"}


def test_validate_models_waits_for_both_sides_it_compares() -> None:
    assert {"dbt_build", "build_cooccurrence"} <= _upstream_closure("validate_models")


def test_plan_commands_name_real_cli_subcommands() -> None:
    """A renamed subcommand must fail here, not at 2 a.m. in the scheduler."""
    choices = next(action.choices for action in build_parser()._actions if action.dest == "command")
    used = {match for task in TASKS for match in re.findall(r"ecom\.cli (\S+)", task.command)}
    assert used
    assert used <= set(choices)


def test_plan_commands_use_only_known_placeholders() -> None:
    for task in TASKS:
        task.command.format(python="py", dbt="dbt")


# ---------------------------------------------------------------- reconcile checks


def test_pairs_identical_detects_a_changed_weight() -> None:
    warehouse = pd.DataFrame({"product_a": ["a"], "product_b": ["b"], "order_count": [2]})
    pipeline = pd.DataFrame({"product_a": ["a"], "product_b": ["b"], "order_count": [3]})
    result = check_pairs_identical(warehouse, pipeline)
    assert not result.passed
    assert result.offending_rows == 2


def test_sum_parity_tolerates_decimal_rounding_only() -> None:
    assert check_sum_parity("x", warehouse_sum=10.005, pipeline_sum=10.0).passed
    assert not check_sum_parity("x", warehouse_sum=10.02, pipeline_sum=10.0).passed


# ---------------------------------------------------------------- steps


def _contract(name: str, columns: tuple[str, ...]) -> TableContract:
    return TableContract(name=name, filename=f"{name}.csv", columns=columns, key=(columns[0],))


def test_check_sources_names_every_missing_file(tmp_path: Path) -> None:
    contracts = (_contract("a", ("id",)), _contract("b", ("id",)))
    with pytest.raises(IngestionError, match=r"a\.csv.*b\.csv"):
        check_sources(settings=Settings(source_dir=tmp_path), contracts=contracts)


def test_check_sources_rejects_a_missing_column_and_writes_nothing(tmp_path: Path) -> None:
    (tmp_path / "a.csv").write_text("id,name\n1,x\n")
    contract = _contract("a", ("id", "price"))
    before = sorted(tmp_path.iterdir())
    with pytest.raises(IngestionError, match="price"):
        check_sources(settings=Settings(source_dir=tmp_path), contracts=(contract,))
    assert sorted(tmp_path.iterdir()) == before


def test_check_sources_counts_rows(tmp_path: Path) -> None:
    (tmp_path / "a.csv").write_text("id\n1\n2\n")
    rows = check_sources(
        settings=Settings(source_dir=tmp_path), contracts=(_contract("a", ("id",)),)
    )
    assert rows == {"a": 2}


@pytest.fixture
def warehouse_and_storage(tmp_path: Path) -> tuple[Path, LocalStorage]:
    """A two-row pipeline layer and a DuckDB warehouse built to match it."""
    storage = LocalStorage(raw_root=tmp_path / "raw", processed_root=tmp_path / "processed")
    items = pd.DataFrame({"order_id": ["o1", "o1"], "price": [10.0, 5.5]})
    pairs = pd.DataFrame({"product_a": ["a"], "product_b": ["b"], "order_count": [1]})
    for name, frame in {
        "order_items": items,
        "products": pd.DataFrame({"product_id": ["a", "b"]}),
        "sellers": pd.DataFrame({"seller_id": ["s"]}),
        "product_cooccurrence": pairs,
    }.items():
        storage.put_parquet(storage.processed_key(name), frame)

    path = tmp_path / "dw.duckdb"
    with duckdb.connect(str(path)) as con:
        con.execute("CREATE TABLE fct_order_items AS SELECT * FROM items")
        con.execute("CREATE TABLE dim_products AS SELECT 'a' AS product_id UNION ALL SELECT 'b'")
        con.execute("CREATE TABLE dim_sellers AS SELECT 's' AS seller_id")
        con.execute("CREATE TABLE fct_product_cooccurrence AS SELECT * FROM pairs")
    return path, storage


def test_reconcile_warehouse_passes_when_both_sides_agree(warehouse_and_storage) -> None:
    path, storage = warehouse_and_storage
    results = reconcile_warehouse(storage=storage, settings=Settings(), warehouse_path=path)
    assert all(result.passed for result in results)
    assert len(results) == 5


def test_reconcile_warehouse_fails_on_a_dropped_pair(warehouse_and_storage) -> None:
    path, storage = warehouse_and_storage
    with duckdb.connect(str(path)) as con:
        con.execute("DELETE FROM fct_product_cooccurrence")
    with pytest.raises(DataQualityError):
        reconcile_warehouse(storage=storage, settings=Settings(), warehouse_path=path)


def test_reconcile_warehouse_requires_a_built_warehouse(tmp_path: Path) -> None:
    storage = LocalStorage(raw_root=tmp_path / "raw", processed_root=tmp_path / "processed")
    with pytest.raises(FileNotFoundError, match="dbt_build"):
        reconcile_warehouse(
            storage=storage, settings=Settings(), warehouse_path=tmp_path / "missing.duckdb"
        )


def test_reconcile_bigquery_requires_a_project(tmp_path: Path) -> None:
    """Without ECOM_GCP_PROJECT the BigQuery check refuses rather than guessing a project."""
    pytest.importorskip("google.cloud.bigquery")
    from ecom.orchestration.steps import reconcile_bigquery

    storage = LocalStorage(raw_root=tmp_path / "raw", processed_root=tmp_path / "processed")
    with pytest.raises(ValueError, match="ECOM_GCP_PROJECT"):
        reconcile_bigquery(storage=storage, settings=Settings(gcp_project=None))
