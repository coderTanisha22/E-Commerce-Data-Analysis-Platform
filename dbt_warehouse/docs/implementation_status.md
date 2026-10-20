# Implementation status

This folder contains the warehouse implementation code. The local DuckDB validation and BigQuery/dbt execution must be run in the target repository/environment before results are reported as verified. No cloud run is claimed by this package.

Expected checks: source/fact row count reconciliation, price sum reconciliation, unique order-item key, valid product pair ordering, dbt relationship tests, and model build success.
