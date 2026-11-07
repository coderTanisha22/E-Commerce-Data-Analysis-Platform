"""Load the pipeline's processed layer into BigQuery as the warehouse's sources.

Writes the six tables dbt reads (models/sources.yml) into the `olist_cleaned`
dataset under their contract names, adding provenance columns. The local
DuckDB target reads the same files directly; this script is what makes the
BigQuery target see identical rows.

  BigQuery table                      read from
  olist_orders_dataset                <processed-dir>/orders.parquet
  olist_order_items_dataset           <processed-dir>/order_items.parquet
  olist_products_dataset              <processed-dir>/products.parquet
  olist_customers_dataset             <processed-dir>/customers.parquet
  olist_sellers_dataset               <processed-dir>/sellers.parquet
  product_category_name_translation   <raw-dir>/category_translation.csv

Each table is replaced with a load job (WRITE_TRUNCATE), not DML, so it works
in the BigQuery sandbox. Does not deduplicate.

Run from dbt_warehouse:
  python scripts/load_to_bigquery.py --project "$ECOM_GCP_PROJECT"
"""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path

import pandas as pd
from google.cloud import bigquery

# BigQuery source table -> (which directory argument, file name). The names on
# the left are the contract names in models/sources.yml; the files are the ones
# src/ecom/cleaning writes. Translation comes from raw because cleaning folds it
# into products rather than republishing it.
TABLES = {
    "olist_orders_dataset": ("processed", "orders.parquet"),
    "olist_order_items_dataset": ("processed", "order_items.parquet"),
    "olist_products_dataset": ("processed", "products.parquet"),
    "olist_customers_dataset": ("processed", "customers.parquet"),
    "olist_sellers_dataset": ("processed", "sellers.parquet"),
    "product_category_name_translation": ("raw", "category_translation.csv"),
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_source(path: Path) -> pd.DataFrame:
    if path.suffix == ".csv":
        # Strings throughout, as the local target's read_csv_auto would type them.
        return pd.read_csv(path, dtype=str)
    return pd.read_parquet(path)


def resolve_sources(processed_dir: Path, raw_dir: Path) -> dict:
    """Map every table to its file, failing once with the full list of missing files."""
    roots = {"processed": processed_dir, "raw": raw_dir}
    paths = {table: roots[root] / name for table, (root, name) in TABLES.items()}
    missing = [str(p) for p in paths.values() if not p.exists()]
    if missing:
        raise SystemExit(f"Missing pipeline outputs: {missing}. Run 'make pipeline' first.")
    return paths


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True, help="Google Cloud project ID")
    parser.add_argument("--run-date", default=dt.date.today().isoformat())
    parser.add_argument("--processed-dir", default="../data/processed")
    parser.add_argument("--raw-dir", default="../data/raw/olist")
    parser.add_argument("--dataset", default="olist_cleaned")
    parser.add_argument("--location", default="US")
    args = parser.parse_args()
    paths = resolve_sources(Path(args.processed_dir).resolve(), Path(args.raw_dir).resolve())

    client = bigquery.Client(project=args.project)
    dataset_id = f"{args.project}.{args.dataset}"
    dataset = bigquery.Dataset(dataset_id)
    dataset.location = args.location
    client.create_dataset(dataset, exists_ok=True)
    lineage = {"run_date": args.run_date, "project": args.project, "dataset": args.dataset, "tables": []}
    for table, path in paths.items():
        df = read_source(path)
        # Provenance columns are additive; business keys and source rows are unchanged.
        df["_run_date"] = args.run_date
        df["_source_hash"] = sha256(path)
        df["_loaded_at"] = dt.datetime.now(dt.timezone.utc)
        table_id = f"{dataset_id}.{table}"
        job_config = bigquery.LoadJobConfig(write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE)
        client.load_table_from_dataframe(df, table_id, job_config=job_config).result()
        loaded = client.get_table(table_id)
        if loaded.num_rows != len(df):
            raise SystemExit(f"{table_id}: loaded {loaded.num_rows} rows, expected {len(df)}")
        entry = {"table": table, "rows": loaded.num_rows, "source_file": str(path), "schema": [{"name": x.name, "type": x.field_type} for x in loaded.schema], "source_hash": df["_source_hash"].iloc[0]}
        lineage["tables"].append(entry)
        print(f"loaded {table_id}: {loaded.num_rows:,} rows")
    out = Path("docs")
    out.mkdir(exist_ok=True)
    dest = out / f"load_lineage_{args.run_date}.json"
    dest.write_text(json.dumps(lineage, indent=2, default=str), encoding="utf-8")
    print(f"Wrote load lineage: {dest}")


if __name__ == "__main__": main()
