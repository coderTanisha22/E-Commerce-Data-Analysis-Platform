"""Pure DataFrame transformations used while cleaning a raw Olist table.

Each function does one normalization step so clean_pipeline.clean_table can
compose them in a readable order and tests can check each step in
isolation.
"""

from pyspark.sql import functions as F


def normalize_column_names(dataframe):
    """Lower-case and strip whitespace from every column name."""
    renamed = dataframe
    for column in dataframe.columns:
        normalized = column.strip().lower()
        if normalized != column:
            renamed = renamed.withColumnRenamed(column, normalized)
    return renamed


def trim_string_columns(dataframe, columns):
    """Strip leading/trailing whitespace from the given string columns."""
    trimmed = dataframe
    for column in columns:
        if column in trimmed.columns:
            trimmed = trimmed.withColumn(column, F.trim(F.col(column)))
    return trimmed


def parse_timestamp_columns(dataframe, columns, source_format="yyyy-MM-dd HH:mm:ss"):
    """Cast string timestamp columns to Spark's timestamp type.

    Uses try_to_timestamp rather than to_timestamp on purpose: Spark 4's
    default ANSI SQL mode makes to_timestamp raise on unparseable input
    instead of returning null, which would crash the whole cleaning run on
    a single bad date. try_to_timestamp keeps the "malformed value becomes
    a flagged null" behavior this pipeline relies on, regardless of the
    team's eventual Spark version/ANSI setting.

    Also adds a `<column>_is_valid` flag, computed before the column is
    overwritten: True unless the raw value was non-blank but failed to
    parse (a genuinely malformed date, as opposed to a legitimately
    missing one).
    """
    parsed = dataframe
    for column in columns:
        if column not in parsed.columns:
            continue
        raw_value = F.col(column)
        parsed_value = F.try_to_timestamp(raw_value, F.lit(source_format))
        is_valid = parsed_value.isNotNull() | raw_value.isNull() | (F.trim(raw_value) == "")
        parsed = parsed.withColumn(f"{column}_is_valid", is_valid)
        parsed = parsed.withColumn(column, parsed_value)
    return parsed


def cast_numeric_columns(dataframe, columns, cast_type="double"):
    """Cast the given columns to a numeric Spark type.

    Uses try_cast rather than cast for the same reason parse_timestamp_columns
    uses try_to_timestamp: under ANSI mode, a plain cast() raises on invalid
    input instead of returning null, which would crash cleaning on a single
    bad value. try_cast keeps "unparseable value becomes a flagged null".

    Also adds a `<column>_cast_ok` flag, computed before the column is
    overwritten: False when a non-blank raw value could not be parsed as a
    number (e.g. stray text in a numeric column).
    """
    casted = dataframe
    for column in columns:
        if column not in casted.columns:
            continue
        raw_value = F.col(column)
        cast_value = raw_value.try_cast(cast_type)
        cast_ok = cast_value.isNotNull() | raw_value.isNull() | (F.trim(raw_value) == "")
        casted = casted.withColumn(f"{column}_cast_ok", cast_ok)
        casted = casted.withColumn(column, cast_value)
    return casted
