# Contract alignment decisions

This implementation follows the main repository's `docs/contracts.md`:

- BigQuery input dataset: `olist_cleaned`.
- Source tables use their exact contracted names, e.g. `olist_orders_dataset` and `olist_order_items_dataset`.
- The item fact grain is (`order_id`, `order_item_id`) and retains every source item row. It does not invent a `quantity` column or group away the item key.
- All order statuses remain available in staging and `fct_order_items`; only delivered orders feed `int_order_products`, `product_sales_summary`, and `fct_product_cooccurrence`.
- Category translation is a left join to `product_category_name_translation`.
- Loader does not deduplicate source rows and records source file names, hashes, row counts, and BigQuery schema in its lineage output.

Open integration dependency: Person A's exact local Parquet directory layout must be confirmed before the BigQuery load. The loader supports `<table>.parquet` and `<table>/**/*.parquet` under the processed directory.
