"""Orchestrates Spark cleaning for every contracted table, for one run_date.

Reads from the raw zone (data_ingestion's output), writes cleaned rows to
the processed zone as Parquet, quarantines invalid rows as CSV (for easy
manual inspection), and writes a data-quality report. See docs/contracts.md
for why Parquet was chosen for the processed zone.
"""

import sys
from datetime import date

from pyspark.sql import SparkSession

from ecom.spark.cleaning_utils import (
    cast_numeric_columns,
    normalize_column_names,
    parse_timestamp_columns,
    trim_string_columns,
)
from ecom.spark.quality_report import (
    build_run_report,
    build_table_quality_summary,
    write_quality_report,
)
from ecom.spark.schema_contracts import get_contracted_tables, get_table_contract
from ecom.spark.validators import (
    check_required_columns_present,
    count_duplicate_keys,
    count_null_required_fields,
    determine_row_validity,
    flag_invalid_numeric_values,
    flag_out_of_range_values,
)
from ecom.spark.zones import PROCESSED_ZONE_DIR, QUARANTINE_ZONE_DIR, RAW_ZONE_DIR, REPORTS_DIR


def get_spark_session(app_name="olist_spark_cleaning"):
    """Build (or reuse) a local SparkSession for the cleaning run."""
    return SparkSession.builder.master("local[*]").appName(app_name).getOrCreate()


def read_raw_table(spark, table_name, run_date):
    """Read one table's raw-zone CSV for a given run_date.

    All columns are read as strings deliberately: casting is an explicit,
    auditable step in clean_table rather than something Spark infers
    silently.

    multiLine is required here, not optional: olist_order_reviews_dataset
    has review comments containing real newline characters inside quoted
    fields. Spark's CSV reader defaults to one-record-per-physical-line and
    silently shifts columns across split records without this option -
    that bug, not genuine data-quality issues, was the original cause of a
    large chunk of "invalid" review rows during testing.
    """
    raw_path = RAW_ZONE_DIR / table_name / f"run_date={run_date}"
    return (
        spark.read.option("header", True)
        .option("inferSchema", False)
        .option("multiLine", True)
        .option("quote", '"')
        .option("escape", '"')
        .csv(str(raw_path))
    )


def clean_table(dataframe, contract):
    """Apply the full cleaning and validation pipeline to one raw DataFrame.

    Returns (clean_rows, quarantined_rows) so run_spark_cleaning can write
    outputs and build the report without repeating this logic.
    """
    working = normalize_column_names(dataframe)
    working = trim_string_columns(working, contract["trim_columns"])
    working = parse_timestamp_columns(working, contract["date_columns"])

    # Both numeric_columns and range_columns hold numeric values and must be
    # cast before any numeric comparison runs against them - comparing a
    # still-string column with between()/>= fails under Spark's ANSI mode
    # instead of silently coercing, so casting is not optional here.
    columns_needing_numeric_cast = list(
        dict.fromkeys(
            list(contract["numeric_columns"].keys()) + list(contract["range_columns"].keys())
        )
    )
    working = cast_numeric_columns(working, columns_needing_numeric_cast)

    working = flag_invalid_numeric_values(working, contract["numeric_columns"])
    working = flag_out_of_range_values(working, contract["range_columns"])

    flag_columns = [
        column for column in working.columns if column.endswith(("_is_valid", "_cast_ok"))
    ]
    working = determine_row_validity(working, contract["required_columns"], flag_columns)

    clean_rows = working.filter("is_valid_row").drop(*flag_columns, "is_valid_row")
    quarantined_rows = working.filter("NOT is_valid_row")

    return clean_rows, quarantined_rows


def clean_one_table(spark, table_name, run_date):
    """Read, clean, write outputs for, and summarize one table."""
    contract = get_table_contract(table_name)
    raw_df = read_raw_table(spark, table_name, run_date)

    missing_columns = check_required_columns_present(raw_df, contract["required_columns"])
    if missing_columns:
        return {
            "table_name": table_name,
            "status": "fail_missing_columns",
            "missing_columns": missing_columns,
        }

    input_row_count = raw_df.count()
    clean_rows, quarantined_rows = clean_table(raw_df, contract)
    output_row_count = clean_rows.count()
    quarantined_row_count = quarantined_rows.count()

    clean_rows.write.mode("overwrite").parquet(
        str(PROCESSED_ZONE_DIR / table_name / f"run_date={run_date}")
    )
    if quarantined_row_count:
        quarantined_rows.write.mode("overwrite").option("header", True).csv(
            str(QUARANTINE_ZONE_DIR / table_name / f"run_date={run_date}")
        )

    null_counts = count_null_required_fields(raw_df, contract["required_columns"])
    duplicate_key_count = count_duplicate_keys(raw_df, contract["key_columns"])
    return build_table_quality_summary(
        table_name=table_name,
        input_row_count=input_row_count,
        output_row_count=output_row_count,
        quarantined_row_count=quarantined_row_count,
        null_counts=null_counts,
        duplicate_key_count=duplicate_key_count,
    )


def run_spark_cleaning(run_date):
    """Clean every contracted table for one run_date and write all outputs."""
    spark = get_spark_session()
    run_id = f"{run_date}_clean"

    table_summaries = [
        clean_one_table(spark, table_name, run_date) for table_name in get_contracted_tables()
    ]

    report = build_run_report(run_date, run_id, table_summaries)
    write_quality_report(report, REPORTS_DIR / f"data_quality_report_{run_date}.json")
    spark.stop()
    return report


def main():
    run_date = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    report = run_spark_cleaning(run_date)

    failed_tables = [
        table for table in report["tables"] if table.get("status", "").startswith("fail")
    ]
    if failed_tables:
        print(f"{len(failed_tables)} table(s) failed cleaning.", file=sys.stderr)
        sys.exit(1)

    print(
        f"Cleaning complete for run_date={run_date}. "
        f"Report: {REPORTS_DIR}/data_quality_report_{run_date}.json"
    )


if __name__ == "__main__":
    main()
