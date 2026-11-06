"""Airflow DAG for the Olist batch pipeline.

The task graph, commands and dependencies live in ``ecom.orchestration.plan``;
this file only turns them into operators. Each task shells out to the
pipeline's own interpreter, so Airflow schedules the work and never performs
it, and Airflow's dependency pins never meet the pipeline's or dbt's.

Configuration, read from the environment of the Airflow processes:

* ``ECOM_REPO_ROOT`` - the repository; defaults to the parent of this folder.
* ``ECOM_PYTHON`` - the pipeline interpreter; defaults to ``.venv/bin/python``.
* ``ECOM_DBT`` - the dbt executable; defaults to ``.venv/bin/dbt``.

Any other ``ECOM_*`` variable (storage backend, MinIO credentials) is passed
through to the tasks unchanged.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG

REPO_ROOT = Path(os.environ.get("ECOM_REPO_ROOT", Path(__file__).resolve().parents[1]))
PYTHON = os.environ.get("ECOM_PYTHON", str(REPO_ROOT / ".venv" / "bin" / "python"))
DBT = os.environ.get("ECOM_DBT", str(REPO_ROOT / ".venv" / "bin" / "dbt"))

# The plan has no third-party imports, so it loads in Airflow's environment.
sys.path.insert(0, str(REPO_ROOT / "src"))
from ecom.orchestration.plan import DAG_ID, TASKS  # noqa: E402

DEFAULT_ARGS = {
    "owner": "group9",
    # One retry covers a transient failure such as MinIO restarting. A failed
    # quality gate fails again identically, so more retries only delay the alert.
    "retries": 1,
    "retry_delay": timedelta(minutes=2),
    # The whole pipeline takes about 30 s locally; 20 minutes per task means a
    # hung task is caught well before the next daily run.
    "execution_timeout": timedelta(minutes=20),
}

with DAG(
    dag_id=DAG_ID,
    description="Olist CSVs -> raw -> processed -> warehouse, graph and inventory -> dashboard",
    doc_md=__doc__,
    schedule="@daily",
    start_date=datetime(2026, 11, 1, tzinfo=timezone.utc),
    # The pipeline rebuilds from the full source each run, so a missed day needs
    # one run, not one per missed day.
    catchup=False,
    # Runs overwrite the same processed layer and warehouse file; two at once would race.
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["ecom", "batch"],
) as dag:
    operators = {
        task.task_id: BashOperator(
            task_id=task.task_id,
            bash_command=task.command.format(python=PYTHON, dbt=DBT),
            cwd=str(REPO_ROOT),
            append_env=True,
            doc_md=task.doc,
        )
        for task in TASKS
    }
    for task in TASKS:
        for upstream in task.upstream:
            operators[upstream] >> operators[task.task_id]
