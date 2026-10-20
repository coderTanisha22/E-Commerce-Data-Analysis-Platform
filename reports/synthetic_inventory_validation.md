# Synthetic Inventory: Validation Report

**Table:** `data/processed/synthetic_inventory.parquet` · **Rows:** 33,787 ·
**Seed:** 42 · **SHA-256:** `f0881d74ef39da3d8cff47272ffcf1cc83577066d3e06347bf1f2d830248cfa2`
**Generated:** 2026-09-27T20:40:34+00:00 · every row carries `is_synthetic = True`.

Olist records real sales but no stock levels. Without stock, `days_of_inventory`
cannot be computed and the restock rule has nothing to classify. This table supplies
the missing operational fields while keeping every sales-derived number real.

## 1. What is real and what is generated

| column | real or synthetic | how it is produced |
|---|---|---|
| seller_id | real | key from order_lines |
| product_id | real | key from order_lines |
| units_sold | real | SUM(quantity) over eligible lines in the window |
| first_sale_date | real | MIN(order_purchase_timestamp) per pair |
| active_days | real | max(30, AS_OF - first_sale_date) |
| daily_sales_rate | real | units_sold / active_days |
| evidence | real | 'sufficient' if units_sold >= 3 else 'insufficient' |
| lead_time_days | SYNTHETIC | one uniform integer 5-20 drawn per seller |
| reorder_point | derived | max(1, ceil(daily_sales_rate x (lead_time_days + 3))) |
| current_quantity | SYNTHETIC | round(reorder_point x uniform(0.2, 3.0)) |
| last_restock_date | SYNTHETIC | AS_OF - uniform integer 1-60 days |
| days_of_inventory | derived | current_quantity / daily_sales_rate |
| status | derived | Insufficient data / Urgent / Monitor / Healthy |
| is_synthetic | flag | True on every row |

Seven columns come from Olist and never change when the seed changes. Three are drawn
from a seeded generator. Three more are deterministic functions of the first two groups.

## 2. Reconciliation: why 33,787 rows and not 34,448

| filter step | rows |
|---|---|
| order_lines rows | 102,425 |
| distinct (seller_id, product_id) pairs, all data | 34,448 |
| lines joined to orders | 102,425 |
| after excluding ['canceled', 'unavailable'] | 101,953 |
| after window 2017-02-01 to 2018-08-31 | 100,819 |
| grain: (seller_id, product_id) pairs generated | 33,787 |
| of which evidence sufficient (units >= 3) | 8,951 |
| of which evidence insufficient | 24,836 |

The full dataset holds 34,448 seller-product pairs. Excluding cancelled and unavailable
orders removes 472 lines, and restricting to the analysis window removes a further 1,134.
The pairs that survive number **33,787** — 661 pairs sold *only* in cancelled orders
or outside the window, so they have no demand signal and are not given stock.

## 3. Validity checks

| group | check | result | evidence |
|---|---|---|---|
| A | Grain unique on (seller_id, product_id) | PASS | 33,787 rows, 0 duplicates |
| A | Every pair exists in order_lines (FK) | PASS | 0 invented pairs |
| A | No nulls in any column | PASS | 0 nulls |
| A | Quantities and rates non-negative | PASS | min rate 0.001736 |
| A | lead_time_days within [5, 20] | PASS | observed 5-20 |
| A | Exactly one lead time per seller | PASS | 3,010 sellers |
| A | reorder_point formula exact on every row | PASS | asserted row-wise |
| A | status rule exact on every row | PASS | asserted row-wise |
| A | Real inputs unchanged by generation | PASS | order_lines unchanged, orders unchanged |
| B | Same seed -> identical SHA-256 | PASS | f0881d74ef39da3d... |
| B | Different seed -> different SHA-256 | PASS | 0590bd2f4631cccb... |
| B | Seed changes only synthetic columns | PASS | real columns identical across seeds |
| C | units_sold recomputed independently matches | PASS | exact equality |
| C | daily_sales_rate = units_sold / active_days | PASS | rtol 1e-12 |
| C | Cancelled / out-of-window orders excluded | PASS | asserted on fixture |

All tests/test_synthetic_inventory.py: tests in `tests/test_synthetic_inventory.py` pass: `......................                                                   [100%]`

## 4. Seed stability (seeds 1–30)

| status | mean_pct | std_pct | min_pct | max_pct |
|---|---|---|---|---|
| Urgent | 2.944 | 0.0952 | 2.788 | 3.099 |
| Monitor | 0.757 | 0.032 | 0.696 | 0.82 |
| Healthy | 22.792 | 0.0909 | 22.63 | 22.959 |
| Insufficient data | 73.508 | 0.0 | 73.508 | 73.508 |

Status shares move by well under one percentage point across 30 seeds. The conclusion
"a small minority of seller-products need urgent restocking" does not depend on one
lucky draw. `Insufficient data` has a standard deviation of exactly 0 because the
evidence rule uses only real sales and is untouched by the generator.

![Seed stability](figures/inv_03_seed_stability.png)

## 5. Sensitivity analysis

| parameter | value | Urgent | Monitor | Healthy | Insufficient data | median_reorder_point | median_days_of_inventory |
|---|---|---|---|---|---|---|---|
| safety_days | 0 | 2.969 | 0.918 | 22.606 | 73.508 | 1.0 | 164.0 |
| safety_days | 3 | 2.859 | 0.737 | 22.896 | 73.508 | 1.0 | 164.0 |
| safety_days | 7 | 2.673 | 0.482 | 23.337 | 73.508 | 1.0 | 164.0 |
| stock_factor_range | (0.2, 3.0) | 2.859 | 0.737 | 22.896 | 73.508 | 1.0 | 164.0 |
| stock_factor_range | (0.5, 2.0) | 0.337 | 1.356 | 24.799 | 73.508 | 1.0 | 153.0 |
| stock_factor_range | (0.1, 4.0) | 2.72 | 0.521 | 23.252 | 73.508 | 1.0 | 205.0 |
| lead_time_range | (3, 10) | 2.693 | 0.728 | 23.071 | 73.508 | 1.0 | 164.0 |
| lead_time_range | (5, 20) | 2.859 | 0.737 | 22.896 | 73.508 | 1.0 | 164.0 |
| lead_time_range | (10, 30) | 3.016 | 0.846 | 22.63 | 73.508 | 1.0 | 164.3 |

The rule responds in the expected direction. Raising the lead-time range from (3,10) to
(10,30) raises the Urgent share, because a longer wait for resupply means a given stock
level covers proportionally less of it. Narrowing the stock factor from (0.1,4.0) to
(0.5,2.0) cuts the extremes at both ends. Adding safety days raises the reorder point
and pushes borderline rows from Healthy toward Monitor.

## 6. Sanity against the real data

![Distributions](figures/inv_01_distributions.png)

The real sales rate is extremely skewed: the median seller-product sells
0.0080 units per day. The synthetic stock inherits that
skew because it is computed from the reorder point, which is computed from the rate.

![Stock scales with speed](figures/inv_02_stock_vs_speed.png)

The mean reorder point rises monotonically across the real sales-rate deciles
(Spearman rho = 0.545 against the rate), so the synthetic layer is anchored to real
demand rather than drawn independently of it.

**This relationship is weaker than it first looks, and we state that plainly.** The
reorder point is an integer floored at 1, and 88.3% of sufficient-evidence rows sit
exactly at that floor. Scaling is therefore only visible in the top two deciles; deciles
1 to 8 are flat at 1.0. Because `current_quantity` is a random multiple of the reorder
point, it inherits the flooring and is **not** monotonic across deciles — it wobbles
around 1.6 units for every decile where the reorder point is 1 (Spearman rho = 0.204
overall, rising to 0.362 on the 1,045 rows where the reorder point reaches 2 or more).
The chart plots the mean per decile; the median would be 1 for nine deciles out of ten
and would hide the effect entirely.

## 7. Limitations

- **Stock is simulated.** `current_quantity`, `lead_time_days` and `last_restock_date`
  are invented. Restock flags demonstrate that the pipeline and the rule logic work;
  they are not statements about any real seller's warehouse.
- **Most reorder points are 1.** 96.4% of all rows, and 88.3% of
  sufficient-evidence rows, have `reorder_point = 1`, because
  Olist velocity is very low — the median pair sells about one unit every
  126 days. The integer ceiling floors at 1, so the
  reorder point carries little information for slow movers. The practical consequence is
  that stock scales with demand only in the fastest two deciles; below that the synthetic
  stock is effectively noise around 1.6 units, and `current_quantity` is not monotonic in
  the sales rate. A non-integer reorder point, or a units-per-month rather than
  units-per-day rate, would remove this artefact.
- **Only 8,951 of 33,787 rows (26.5%) have
  sufficient evidence.** The rest are labelled `Insufficient data` rather than scored,
  because a rate built on one or two sales is noise.
- **No seasonality.** The rate is a flat average over the window; it does not model
  demand that rises before a holiday.
- **Lead time is drawn uniformly**, which no real supplier population follows. A
  log-normal draw would be more realistic but adds a parameter we cannot calibrate.

## 8. How to reproduce

```
make pipeline                       # ingest -> clean
.venv/bin/python -m ecom.cli inventory
.venv/bin/pytest tests/test_synthetic_inventory.py -q
```

Re-running with seed 42 must reproduce SHA-256 `f0881d74ef39da3d8cff47272ffcf1cc...`.
