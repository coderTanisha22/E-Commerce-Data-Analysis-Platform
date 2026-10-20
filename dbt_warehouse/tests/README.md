# dbt tests

`dbt build` runs the schema tests and singular SQL tests in this folder. They enforce source-key grain, product-pair ordering, and revenue preservation. A local DuckDB sanity check is also available via `python scripts/local_validate.py --data-dir ../data`; it is useful before cloud setup but does not replace dbt/BigQuery execution.
