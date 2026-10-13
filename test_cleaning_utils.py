"""Tests for spark.cleaning_utils."""

from pyspark.sql.types import StringType, StructField, StructType

from spark.cleaning_utils import (
    cast_numeric_columns,
    normalize_column_names,
    parse_timestamp_columns,
    trim_string_columns,
)


def test_normalize_column_names_lowercases_and_strips(spark):
    df = spark.createDataFrame([(1,)], [" Order_ID "])
    normalized = normalize_column_names(df)
    assert normalized.columns == ["order_id"]


def test_trim_string_columns_removes_surrounding_whitespace(spark):
    df = spark.createDataFrame([("  Pune  ",)], ["city"])
    trimmed = trim_string_columns(df, ["city"])
    assert trimmed.collect()[0]["city"] == "Pune"


def test_parse_timestamp_columns_parses_valid_dates(spark):
    df = spark.createDataFrame([("2017-10-02 10:56:33",)], ["order_purchase_timestamp"])
    parsed = parse_timestamp_columns(df, ["order_purchase_timestamp"])
    row = parsed.collect()[0]
    assert row["order_purchase_timestamp"] is not None
    assert row["order_purchase_timestamp_is_valid"] is True


def test_parse_timestamp_columns_flags_malformed_dates(spark):
    df = spark.createDataFrame([("not-a-date",)], ["order_purchase_timestamp"])
    parsed = parse_timestamp_columns(df, ["order_purchase_timestamp"])
    row = parsed.collect()[0]
    assert row["order_purchase_timestamp"] is None
    assert row["order_purchase_timestamp_is_valid"] is False


def test_parse_timestamp_columns_treats_blank_as_valid(spark):
    schema = StructType([StructField("order_approved_at", StringType(), True)])
    df = spark.createDataFrame([(None,)], schema)
    parsed = parse_timestamp_columns(df, ["order_approved_at"])
    row = parsed.collect()[0]
    assert row["order_approved_at_is_valid"] is True


def test_cast_numeric_columns_casts_valid_numbers(spark):
    df = spark.createDataFrame([("58.90",)], ["price"])
    casted = cast_numeric_columns(df, ["price"])
    row = casted.collect()[0]
    assert row["price"] == 58.90
    assert row["price_cast_ok"] is True


def test_cast_numeric_columns_flags_non_numeric_garbage(spark):
    df = spark.createDataFrame([("not-a-number",)], ["price"])
    casted = cast_numeric_columns(df, ["price"])
    row = casted.collect()[0]
    assert row["price"] is None
    assert row["price_cast_ok"] is False
