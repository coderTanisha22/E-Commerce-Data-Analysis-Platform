"""The batch pipeline as a task graph: what runs, in which order, and how.

``dags/ecom_pipeline.py`` turns this plan into an Airflow DAG and adds nothing
else, so the plan can be tested without Airflow installed and the DAG cannot
drift from it. Task IDs are the ones fixed in docs/CODING_STANDARDS.md
section 9.

Every task is a shell command run with the pipeline's own interpreter. Airflow
lives in a separate environment because it pins its own versions of pydantic,
SQLAlchemy and friends, and so does dbt; keeping all three apart is what lets
each stay on a supported version. It also enforces the design rule that
Airflow only schedules and never transforms: no task imports ``ecom``.
"""

from __future__ import annotations

from dataclasses import dataclass

DAG_ID = "ecom_pipeline"


@dataclass(frozen=True)
class PlannedTask:
    """One task: its shell command and the tasks that must finish first.

    ``command`` is a template with ``{python}`` and ``{dbt}`` placeholders,
    filled with absolute executable paths when the DAG is built.
    """

    task_id: str
    command: str
    upstream: tuple[str, ...]
    doc: str


def _ecom(subcommand: str) -> str:
    return f"{{python}} -m ecom.cli {subcommand}"


TASKS: tuple[PlannedTask, ...] = (
    PlannedTask(
        "extract_olist",
        _ecom("extract"),
        (),
        "Check every source CSV exists and matches its contract. Writes nothing, so a "
        "bad download fails here while the previous raw layer is still intact.",
    ),
    PlannedTask(
        "store_raw",
        _ecom("ingest"),
        ("extract_olist",),
        "Copy the sources byte-for-byte into the raw layer and write the SHA-256 manifest.",
    ),
    PlannedTask(
        "spark_clean",
        _ecom("clean"),
        ("store_raw",),
        "Raw to processed Parquet behind the quality gates. Runs the pandas path; the "
        "ID keeps the tracker's name (CODING_STANDARDS section 9).",
    ),
    PlannedTask(
        "dbt_build",
        "cd dbt_warehouse && mkdir -p .duckdb"
        " && {dbt} deps --profiles-dir . && {dbt} run --profiles-dir .",
        ("spark_clean",),
        "Build the staging, intermediate and mart models on DuckDB.",
    ),
    PlannedTask(
        "build_cooccurrence",
        _ecom("analyse"),
        ("spark_clean",),
        "Count product pairs over orders that were really placed and write the profile.",
    ),
    PlannedTask(
        "validate_models",
        "cd dbt_warehouse && {dbt} test --profiles-dir . && cd .. && "
        + _ecom("reconcile-warehouse"),
        ("dbt_build", "build_cooccurrence"),
        "Run the dbt tests, then require the warehouse to match the pipeline row for row "
        "and pair for pair. Waits for build_cooccurrence because it compares against it.",
    ),
    PlannedTask(
        "build_graph",
        _ecom("visualize-graph"),
        ("build_cooccurrence",),
        "Load the co-occurrence graph and export the interactive network view.",
    ),
    PlannedTask(
        "refresh_inventory_metrics",
        _ecom("inventory"),
        ("spark_clean",),
        "Regenerate the synthetic inventory from real sales velocity (seeded, reproducible).",
    ),
    PlannedTask(
        "dashboard_ready",
        _ecom("ready"),
        ("validate_models", "build_graph", "refresh_inventory_metrics"),
        "Load the data exactly as the API does and check it against this run's manifests.",
    ),
)
