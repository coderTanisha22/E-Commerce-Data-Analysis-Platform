"""Local sanity check of the warehouse transformation rules using pandas.
Checks row grain, revenue preservation and product pairs without cloud access.

Independent of dbt on purpose: it reads the original Olist CSVs with pandas, so
agreement with the warehouse is evidence rather than a tautology. The order
status rule it applies must match ecom.config.EXCLUDED_STATUSES, or the two
will disagree for a reason that has nothing to do with correctness.
Run from dbt_warehouse: python scripts/local_validate.py --data-dir ../data
"""
import argparse, json
from collections import Counter
from itertools import combinations
from pathlib import Path
import pandas as pd

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--data-dir', default='../data')
    p.add_argument('--output', default='docs/local_validation_results.json')
    a = p.parse_args(); data = Path(a.data_dir).resolve()
    order_file = data / 'olist_orders_dataset.csv'
    item_file = data / 'olist_order_items_dataset.csv'
    required = [order_file, item_file, data / 'olist_products_dataset.csv', data / 'product_category_name_translation.csv']
    missing = [str(x) for x in required if not x.exists()]
    if missing: raise SystemExit(f'Missing input CSVs: {missing}')
    # Read identifiers as strings so pandas cannot silently change key types.
    orders = pd.read_csv(order_file, dtype=str)
    items = pd.read_csv(item_file, dtype=str)
    items['price_num'] = pd.to_numeric(items['price'], errors='coerce')
    source_rows = len(items)
    fact = items.merge(orders[['order_id','customer_id','order_status','order_purchase_timestamp']], on='order_id', how='inner', validate='many_to_one')
    source_price = float(round(items['price_num'].sum(), 2))
    fact_price = float(round(fact['price_num'].sum(), 2))
    duplicate_keys = int(fact.duplicated(['order_id','order_item_id']).sum())
    # Same rule as ecom.config.EXCLUDED_STATUSES: only genuine failures are
    # excluded. 'shipped', 'invoiced' and 'processing' are orders really placed
    # and still in flight, and a basket is a basket as soon as it is ordered.
    excluded = ('canceled', 'unavailable')
    countable = fact[~fact['order_status'].str.lower().isin(excluded)][['order_id','product_id']].drop_duplicates()
    pair_counts = Counter()
    for _, group in countable.groupby('order_id', sort=False):
        products = sorted(group['product_id'].dropna().unique())
        pair_counts.update(combinations(products, 2))
    bad_pairs = sum(1 for x,y in pair_counts if x >= y)
    result = {
      'input_data_dir': str(data), 'source_order_item_rows': int(source_rows),
      'fact_order_item_rows_after_order_join': int(len(fact)),
      'source_price_sum': source_price, 'fact_price_sum': fact_price,
      'price_sum_matches': bool(abs(source_price-fact_price) < 0.011),
      'unmatched_item_rows_dropped_by_order_join': int(source_rows-len(fact)),
      'duplicate_order_item_keys': duplicate_keys,
      'countable_orders_with_products': int(countable['order_id'].nunique()),
      'excluded_statuses': list(excluded),
      'cooccurrence_pair_rows': len(pair_counts),
      'products_in_pairs': len(set(x for pair in pair_counts for x in pair)),
      'invalid_self_or_reverse_pairs': int(bad_pairs),
      'checks_passed': bool(source_rows == len(fact) and abs(source_price-fact_price) < 0.011 and duplicate_keys == 0 and bad_pairs == 0)
    }
    out=Path(a.output); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))
    if not result['checks_passed']: raise SystemExit(1)
if __name__ == '__main__': main()
