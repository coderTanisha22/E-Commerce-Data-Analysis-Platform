# Coding Standards

These rules exist so the pipeline stays testable, reproducible and portable to a
different execution engine. They are enforced by `ruff` and `black` where a tool
can enforce them, and by review where it cannot.

This document **implements the Coding Standards table in the project tracker**.
Where the tracker states a rule, this document says how it is enforced and
records any accepted exception. If the two ever disagree, the tracker wins and
this file is the bug.

Run `make check` before every commit.

---

## 1. Language and tooling

| Concern | Decision |
|---|---|
| Python | 3.10+ (`match`, `X \| Y` unions allowed) |
| Formatter | `black`, line length **100** |
| Linter | `ruff` (pycodestyle, pyflakes, isort, naming, bugbear, pathlib, pandas-vet) |
| Tests | `pytest`; every transform has a unit test |
| Config | environment variables via `pydantic-settings`; **never** a hardcoded path |
| Logging | stdlib `logging` via `ecom.logging_setup`; **`print()` is banned** outside `cli.py` |

Line length is 100, not 79 — data code has long column expressions and wrapping
them hurts readability more than the extra width does.

## 2. The purity rule (most important rule here)

**A transform function takes a DataFrame and returns a DataFrame. It never does I/O.**

```python
# good - pure, testable, engine-agnostic
def derive_line_quantity(order_items: pd.DataFrame) -> pd.DataFrame: ...

# bad - reads a file, so it cannot be unit tested or ported
def derive_line_quantity(path: str) -> pd.DataFrame: ...
```

Reading and writing happen only in `storage/`, `ingestion/` and the `run_*`
orchestration modules. This is what makes the PySpark port a change of I/O calls
rather than a rewrite of business rules, and it is why every rule in
`cleaning/transforms.py` has a test that runs in milliseconds on a 5-row fixture.

## 3. Layout

```
src/ecom/
  config.py          settings, loaded from env, immutable
  contracts.py       declared schema + keys for every table
  logging_setup.py   one logging config for the whole project
  storage/           StorageBackend ABC + local and MinIO implementations
  ingestion/         source -> raw layer, with validation and a manifest
  cleaning/          pure transforms + the raw -> processed orchestrator
  quality/           assertions that gate the pipeline
  analysis/          profiling metrics and figure generation
  cli.py             the only place argparse and print() may appear
```

One module, one responsibility. If a module needs a second reason to change,
split it.

## 4. Function rules

| Rule | Priority | Enforcement |
|---|---|---|
| Single responsibility - one clear logical task | Mandatory | review |
| Target <= 50 lines; split larger into helpers | Recommended | `make loc` |
| Avoid excessive positional arguments | Recommended | keyword-only (`*`) in every public signature |
| Return explicit values; avoid hidden mutation | Mandatory | the purity rule above |

`make loc` reports functions over 50 lines. Two are knowingly over and stay that
way, because splitting them would hurt readability rather than help it:

| Function | Lines | Why it stays |
|---|---|---|
| `visualize.plot_graph_shape` | 53 | a flat sequence of declarative matplotlib calls with no branching to extract |
| `ingestion.ingest_table` | 51 | one linear read-validate-land-manifest path; helpers would only add indirection |

Anything new over 50 lines needs a line in this table or it gets split.

### TODOs

Use `TODO` only for a known future task, and always with a description:

```python
# TODO: add pagination once the catalogue endpoint returns > 1000 products
```

A bare `# TODO` is not allowed - it carries no information for whoever finds it.

## 5. Naming

| Thing | Convention | Example |
|---|---|---|
| Module, function, variable | `snake_case` | `derive_line_quantity` |
| Class | `PascalCase` | `LocalStorage` |
| Constant | `UPPER_SNAKE` | `DELIVERED_STATUS` |
| Private helper | leading underscore | `_coerce_timestamps` |
| Test | `test_<unit>_<behaviour>` | `test_derive_line_quantity_sums_repeats` |
| Boolean column | `is_` / `has_` prefix | `is_delivered`, `has_category` |
| Timestamp column | `_at` suffix | `purchased_at` |
| Date column | `_date` suffix | `last_restock_date` |
| Count column | `_count` suffix | `order_count` |
| Rate column | `_per_day` suffix | `units_per_day` |

Source column names are preserved verbatim in the **raw** layer and renamed to
project conventions only in **processed**. That boundary is deliberate: raw is
evidence, processed is ours.

**Accepted exceptions to "avoid single-letter names":** loop and comprehension
variables with a scope of one line (`for c in OLIST_CONTRACTS`), and `_` for a
deliberately unused value. The rule exists to stop single letters naming
anything that outlives one expression. `__init__.py` is likewise exempt from the
`snake_case` filename rule - it is a Python language convention, not a choice.

## 6. Data layer contract

| Layer | Format | Mutability | Purpose |
|---|---|---|---|
| `source` (`data/*.csv`) | CSV as downloaded | **read-only, never written by code** | evidence |
| `raw/` | byte-identical copy + manifest | append-only per run | reproducibility |
| `processed/` | Parquet, typed, renamed | overwritten per run | analysis input |

Rules:

1. **The source directory is never modified.** Ingestion copies out of it.
2. **Every table has an entry in `contracts.py`** declaring its columns, dtypes
   and key. A table with no contract cannot be ingested.
3. **Processed output is Parquet**, because CSV loses the dtypes Spark and
   BigQuery both need, and re-inferring them is how silent type bugs start.
4. **Runs are idempotent.** Re-running ingestion on unchanged input produces an
   identical manifest. The manifest records row counts and a SHA-256 of each file.

## 7. Fail loudly

Quality checks **raise**; they do not warn and continue.

```python
# good
raise DataQualityError(f"{n} order_items rows reference an unknown product_id")

# bad
logger.warning("some orphan rows, continuing anyway")
```

A pipeline that silently drops rows produces a dashboard nobody can trust. The
one exception is a check explicitly declared `severity="warn"` in
`quality/checks.py`, which is reserved for known, documented properties of the
Olist dataset (for example the 775 orders that legitimately carry no item rows).

## 8. Analytical constants are named, documented and centralised

Every threshold and window lives in `config.py` with a comment saying **why**.
No magic numbers in transforms.

```python
WINDOW_START = date(2017, 2, 1)  # Nov 2016 has 0 orders; Sep-Oct 2018 is 95% cancelled
```

This matters because our own data audit showed that an undefined "number of days
observed" silently changes every velocity figure in the project. Any number that
could change a result must be traceable to a named constant.

## 9. Airflow and API naming

Not yet built, but fixed now so the first commit in each layer is already correct.

| Rule | Priority | Example |
|---|---|---|
| Airflow DAG and task IDs lowercase `snake_case`, descriptive | Mandatory | `spark_clean`, `build_cooccurrence` |
| Task IDs name the action, not the tool | Mandatory | `build_graph`, not `run_networkx_script` |
| API endpoints lowercase and resource-oriented | Mandatory | `/products/{id}/recommendations` |
| No verbs in paths - the HTTP method is the verb | Mandatory | `GET /products/{id}`, not `/getProduct` |

The DAG task IDs are already fixed by the tracker: `extract_olist`, `store_raw`,
`spark_clean`, `dbt_build`, `validate_models`, `build_cooccurrence`,
`build_graph`, `refresh_inventory_metrics`, `dashboard_ready`. Note that
`spark_clean` names a tool rather than an action and is the one exception, kept
because the tracker and every design document already use it.

## 10. SQL and dbt

These apply to every dbt model and any hand-written BigQuery SQL.

| Rule | Priority | Example |
|---|---|---|
| Uppercase SQL keywords, one consistent indent style | Mandatory | `SELECT ... FROM ... WHERE ...` |
| No `SELECT *` in a transformation model | Mandatory | `SELECT order_id, product_id, quantity` |
| CTE names describe their purpose | Mandatory | `unique_order_products`, `product_pairs` |
| Join conditions explicit, and the join grain verified by a test | Mandatory | `JOIN dim_products p ON f.product_id = p.product_id` |
| Model names lowercase `snake_case` | Mandatory | `fct_orders`, `dim_products` |
| Column names lowercase `snake_case`, describing business meaning | Mandatory | `current_quantity`, `order_count` |

"Verify the join grain" is not optional politeness here. Our own profiling found
that `order_items` holds one row per **unit**, not per line, so a join written
without checking grain silently multiplies revenue. Every fact model gets a
uniqueness test on its declared grain.

## 11. Docstrings

Google style. Required on every public function. A one-line summary is enough
when the signature is self-evident; document the **why**, not the **what**.

```python
def exclude_zero_sales(df: pd.DataFrame) -> pd.DataFrame:
    """Drop seller-products with no sales in the window.

    Velocity is undefined for them, so a days_of_inventory division would
    produce inf rather than a usable restock priority.

    Args:
        df: One row per (seller_id, product_id) with a units_sold column.

    Returns:
        The subset with units_sold > 0.
    """
```

## 12. Commits

`<type>: <imperative summary>` with types `feat`, `fix`, `refactor`, `test`,
`docs`, `chore`. One logical change per commit. Never commit anything under
`data/raw/`, `data/processed/` or `.env`.

## 13. Review checklist

- [ ] `make check` passes (ruff, black, pytest)
- [ ] New transform is pure and has a unit test
- [ ] New table has a contract in `contracts.py`
- [ ] New threshold is a named constant with a comment explaining the value
- [ ] No `print()` outside `cli.py`
- [ ] Docstring states why, not what
- [ ] No function over 50 lines without a row in the exceptions table
- [ ] Every `TODO` carries a description
- [ ] SQL uses uppercase keywords, names its CTEs, and has no `SELECT *`
- [ ] Every new fact model has a uniqueness test on its declared grain
