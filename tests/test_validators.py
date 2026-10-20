"""Tests for spark.validators."""

from pyspark.sql.types import DoubleType, StructField, StructType

from spark.validators import (
    check_required_columns_present,
    count_duplicate_keys,
    count_null_required_fields,
    determine_row_validity,
    flag_invalid_numeric_values,
    flag_out_of_range_values,
)


def test_check_required_columns_present_reports_missing(spark):
    df = spark.createDataFrame([("1",)], ["order_id"])
    missing = check_required_columns_present(df, ["order_id", "customer_id"])
    assert missing == ["customer_id"]


def test_count_null_required_fields_counts_nulls(spark):
    df = spark.createDataFrame([("c1",), (None,), (None,)], ["customer_id"])
    counts = count_null_required_fields(df, ["customer_id"])
    assert counts == {"customer_id": 2}


def test_count_duplicate_keys_counts_rows_sharing_a_key(spark):
    df = spark.createDataFrame([("o1", "p1"), ("o1", "p1"), ("o2", "p2")], ["order_id", "product_id"])
    duplicate_count = count_duplicate_keys(df, ["order_id", "product_id"])
    assert duplicate_count == 2


def test_count_duplicate_keys_returns_zero_without_a_declared_key(spark):
    df = spark.createDataFrame([("1",), ("1",)], ["zip"])
    assert count_duplicate_keys(df, []) == 0


def test_flag_invalid_numeric_values_flags_below_minimum(spark):
    schema = StructType([StructField("price", DoubleType(), True)])
    df = spark.createDataFrame([(58.9,), (-5.0,), (None,)], schema)
    flagged = flag_invalid_numeric_values(df, {"price": 0})
    results = [row["price_is_valid"] for row in flagged.orderBy("price").collect()]
    assert sorted(results) == [False, True, True]


def test_flag_out_of_range_values_flags_outside_bounds(spark):
    schema = StructType([StructField("review_score", DoubleType(), True)])
    df = spark.createDataFrame([(5.0,), (7.0,)], schema)
    flagged = flag_out_of_range_values(df, {"review_score": (1, 5)})
    results = {row["review_score"]: row["review_score_is_valid"] for row in flagged.collect()}
    assert results[5.0] is True
    assert results[7.0] is False


def test_determine_row_validity_combines_required_and_flag_checks(spark):
    df = spark.createDataFrame(
        [("o1", True), (None, True), ("o2", False)], ["order_id", "price_is_valid"]
    )
    result = determine_row_validity(df, ["order_id"], ["price_is_valid"])
    rows = {row["order_id"]: row["is_valid_row"] for row in result.collect()}
    assert rows["o1"] is True
    assert rows["o2"] is False
