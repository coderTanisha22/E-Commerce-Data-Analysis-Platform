"""Data-quality checks run against a cleaned (but not yet filtered) DataFrame.

Validators measure and flag; they never drop rows themselves. Deciding what
to do with a flagged row (quarantine vs. keep) is clean_pipeline's job, so
the quarantine policy stays in one place.
"""

from pyspark.sql import functions as F


def check_required_columns_present(dataframe, required_columns):
    """Return the subset of required_columns missing from dataframe."""
    return [column for column in required_columns if column not in dataframe.columns]


def count_null_required_fields(dataframe, required_columns):
    """Return {column: null_count} for each required column present."""
    null_counts = {}
    for column in required_columns:
        if column in dataframe.columns:
            null_counts[column] = dataframe.filter(F.col(column).isNull()).count()
    return null_counts


def count_duplicate_keys(dataframe, key_columns):
    """Return how many rows share a key with at least one other row.

    An empty key_columns list means the table has no declared business key
    (olist_geolocation_dataset is a many-rows-per-zip lookup table by
    design), so duplication is not meaningful to measure.
    """
    if not key_columns:
        return 0
    grouped = dataframe.groupBy(*key_columns).count().filter(F.col("count") > 1)
    total = grouped.agg(F.sum("count")).collect()[0][0]
    return total or 0


def flag_invalid_numeric_values(dataframe, numeric_minimums):
    """Add `<column>_is_valid` flags for values below a declared minimum.

    Null is treated as valid here: missing-ness is already captured by
    count_null_required_fields, so this check is only about present values
    that are out of range (e.g. a negative price).
    """
    flagged = dataframe
    for column, minimum_value in numeric_minimums.items():
        if column in flagged.columns:
            flag_column = f"{column}_is_valid"
            flagged = flagged.withColumn(
                flag_column,
                F.col(column).isNull() | (F.col(column) >= minimum_value),
            )
    return flagged


def flag_out_of_range_values(dataframe, range_columns):
    """Add `<column>_is_valid` flags for columns with a declared (min, max)."""
    flagged = dataframe
    for column, bounds in range_columns.items():
        minimum_value, maximum_value = bounds
        if column in flagged.columns:
            flag_column = f"{column}_is_valid"
            flagged = flagged.withColumn(
                flag_column,
                F.col(column).isNull() | F.col(column).between(minimum_value, maximum_value),
            )
    return flagged


def determine_row_validity(dataframe, required_columns, flag_columns):
    """Add an overall is_valid_row column.

    A row is invalid if any required field is null or any individual
    quality flag computed earlier in the pipeline is False.
    """
    condition = F.lit(True)
    for column in required_columns:
        if column in dataframe.columns:
            condition = condition & F.col(column).isNotNull()
    for flag_column in flag_columns:
        if flag_column in dataframe.columns:
            condition = condition & F.col(flag_column)
    return dataframe.withColumn("is_valid_row", condition)
