"""Spark-based cleaning stage.

An alternative to the pandas path in :mod:`ecom.cleaning`, kept deliberately
so the two engines can be benchmarked against each other on the same input.
PySpark is an optional dependency: importing this package does not import
PySpark, so the rest of the pipeline runs without it installed.
"""
