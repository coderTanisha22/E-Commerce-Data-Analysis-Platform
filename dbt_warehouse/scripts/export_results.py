"""Export warehouse QA summaries after a successful dbt build."""
import argparse
import json
from pathlib import Path
from google.cloud import bigquery

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("project")
    parser.add_argument("--dataset", default="olist_analytics_dev")
    parser.add_argument("--output", default="docs/results.json")
    args = parser.parse_args()
    client = bigquery.Client(project=args.project)
    ds = f"{args.project}.{args.dataset}"
    queries = {
      "fact_rows": f"SELECT COUNT(*) AS n FROM `{ds}.fct_order_items`",
      "source_item_rows": f"SELECT COUNT(*) AS n FROM `{args.project}.olist_cleaned.olist_order_items_dataset`",
      "fact_price_sum": f"SELECT ROUND(SUM(price), 2) AS amount FROM `{ds}.fct_order_items`",
      "source_price_sum": f"SELECT ROUND(SUM(SAFE_CAST(price AS NUMERIC)), 2) AS amount FROM `{args.project}.olist_cleaned.olist_order_items_dataset`",
      "cooccurrence_pairs": f"SELECT COUNT(*) AS n FROM `{ds}.fct_product_cooccurrence`",
      "products_in_pairs": f"SELECT COUNT(DISTINCT product_id) AS n FROM (SELECT product_a AS product_id FROM `{ds}.fct_product_cooccurrence` UNION ALL SELECT product_b AS product_id FROM `{ds}.fct_product_cooccurrence`)"
    }
    results = {name: [dict(row.items()) for row in client.query(sql).result()] for name, sql in queries.items()}
    path = Path(args.output); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(json.dumps(results, indent=2, default=str))
    print(f"Wrote {path}")
if __name__ == "__main__": main()
