"""Shared pytest fixtures for the ingestion and Spark cleaning test suites."""

import pytest
from pyspark.sql import SparkSession


@pytest.fixture(scope="session")
def spark():
    """A local SparkSession reused across the whole test session.

    local[2] keeps tests fast without needing a real cluster; session scope
    avoids the startup cost per test.
    """
    session = (
        SparkSession.builder.master("local[2]")
        .appName("olist_tests")
        .config("spark.ui.enabled", "false")
        .getOrCreate()
    )
    yield session
    session.stop()
