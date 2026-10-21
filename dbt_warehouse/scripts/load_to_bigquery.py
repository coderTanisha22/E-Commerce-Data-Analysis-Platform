"""Load Person A's processed Parquet outputs to BigQuery with provenance metadata.

Expected default layout (all supported):
  storage/processed/olist/<table_name>/**/*.parquet
  storage/processed/olist/<table_name>.parquet
Table names are the exact names from docs/contracts.md. Does not deduplicate.
"""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
from google.cloud import bigquery
import pandas as pd

TABLES = [
    "olist_customers_dataset", "olist_geolocation_dataset", "olist_orders_dataset",
    "olist_order_items_dataset", "olist_order_payments_dataset", "olist_order_reviews_dataset",
    "olist_products_dataset", "olist_sellers_dataset", "product_category_name_translation",
]

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def find_parquet_files(base: Path, table: str):
    candidates = list((base / table).rglob("*.parquet")) if (base / table).exists() else []
    direct = base / f"{table}.parquet"
    if direct.exists(): candidates.append(direct)
    # Avoid duplicate paths if direct path was also matched through recursive glob.
    return sorted(set(p.resolve() for p in candidates))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True, help="Google Cloud project ID")
    parser.add_argument("--run-date", default=dt.date.today().isoformat())
    parser.add_argument("--processed-dir", default="../storage/processed/olist")
    parser.add_argument("--dataset", default="olist_cleaned")
    parser.add_argument("--location", default="US")
    args = parser.parse_args()
    processed_dir = Path(args.processed_dir).resolve()
    if not processed_dir.exists():
        raise SystemExit(f"Processed directory not found: {processed_dir}. Run Person A's cleaning pipeline first.")
    client = bigquery.Client(project=args.project)
    dataset_id = f"{args.project}.{args.dataset}"
    dataset = bigquery.Dataset(dataset_id)
    dataset.location = args.location
    client.create_dataset(dataset, exists_ok=True)
    lineage = {"run_date": args.run_date, "project": args.project, "dataset": args.dataset, "tables": []}
    for table in TABLES:
        files = find_parquet_files(processed_dir, table)
        if not files:
            raise SystemExit(f"No Parquet files found for {table} under {processed_dir}. Check Person A's output layout.")
        frames = [pd.read_parquet(p) for p in files]
        df = pd.concat(frames, ignore_index=True)
        # Provenance columns are additive; business keys and source rows are unchanged.
        df["_run_date"] = args.run_date
        df["_source_hash"] = sha256(files[0]) if len(files) == 1 else hashlib.sha256("".join(sha256(p) for p in files).encode()).hexdigest()
        df["_loaded_at"] = dt.datetime.now(dt.timezone.utc)
        table_id = f"{dataset_id}.{table}"
        job_config = bigquery.LoadJobConfig(write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE)
        job = client.load_table_from_dataframe(df, table_id, job_config=job_config)
        job.result()
        loaded = client.get_table(table_id)
        entry = {"table": table, "rows": loaded.num_rows, "source_files": [str(p) for p in files], "schema": [{"name": x.name, "type": x.field_type} for x in loaded.schema], "source_hash": df["_source_hash"].iloc[0]}
        lineage["tables"].append(entry)
        print(f"loaded {table_id}: {loaded.num_rows:,} rows")
    out = Path("docs")
    out.mkdir(exist_ok=True)
    dest = out / f"load_lineage_{args.run_date}.json"
    dest.write_text(json.dumps(lineage, indent=2, default=str), encoding="utf-8")
    print(f"Wrote load lineage: {dest}")

if __name__ == "__main__": main()
