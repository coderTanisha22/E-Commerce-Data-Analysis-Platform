# Synthetic Inventory: Validation Report

**Table:** `data/processed/synthetic_inventory.parquet` · **Rows:** 33,787 ·
**Seed:** 42 · **SHA-256:** `8afabc716a0ea56be42555a942ec21c2071a03ef31b67ab935ef7c189a326a35`
**Generated:** 2026-11-02T16:59:45+00:00 · every row carries `is_synthetic = True`.

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
| reorder_point | derived | round(daily_sales_rate x (lead_time_days + 3), 2), fractional units |
| current_quantity | SYNTHETIC | max(1, round(daily_sales_rate x (lead_time_days + 3) x uniform(0.2, 3.0))) |
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
| A | Quantities and rates non-negative | PASS | min rate 0.001733 |
| A | lead_time_days within [5, 20] | PASS | observed 5-20 |
| A | Exactly one lead time per seller | PASS | 3,010 sellers |
| A | reorder_point formula exact on every row | PASS | asserted row-wise |
| A | Stock never rounds to zero | PASS | 0 rows with current_quantity = 0 |
| A | At or below the reorder point is never Healthy | PASS | 0 of 8,951 scored rows (was 2,776) |
| A | status rule exact on every row | PASS | asserted row-wise |
| A | Real inputs unchanged by generation | PASS | order_lines unchanged, orders unchanged |
| B | Same seed -> identical SHA-256 | PASS | 8afabc716a0ea56b... |
| B | Different seed -> different SHA-256 | PASS | 4f770bfcfb2cbeaa... (seed 7) |
| B | Seed changes only synthetic columns | PASS | real columns identical across seeds |
| C | units_sold recomputed independently matches | PASS | exact equality |
| C | daily_sales_rate = units_sold / active_days | PASS | rtol 1e-12 |
| C | Cancelled / out-of-window orders excluded | PASS | asserted on fixture |

All 25 tests in `tests/test_synthetic_inventory.py` pass.

## 4. Seed stability (seeds 1–30)

| status | mean_pct | std_pct | min_pct | max_pct |
|---|---|---|---|---|
| Urgent | 0.579 | 0.0396 | 0.515 | 0.687 |
| Monitor | 1.181 | 0.0431 | 1.119 | 1.341 |
| Healthy | 24.733 | 0.0452 | 24.637 | 24.817 |
| Insufficient data | 73.508 | 0.0 | 73.508 | 73.508 |

Status shares move by well under one percentage point across 30 seeds. The conclusion
"a small minority of seller-products need urgent restocking" does not depend on one
lucky draw. `Insufficient data` has a standard deviation of exactly 0 because the
evidence rule uses only real sales and is untouched by the generator.

![Seed stability](figures/inv_03_seed_stability.png)

## 5. Sensitivity analysis

| parameter | value | Urgent | Monitor | Healthy | Insufficient data | median_reorder_point | median_days_of_inventory |
|---|---|---|---|---|---|---|---|
| safety_days | 0 | 0.775 | 1.512 | 24.205 | 73.508 | 0.09 | 125.7 |
| safety_days | 3 | 0.610 | 1.131 | 24.752 | 73.508 | 0.12 | 125.7 |
| safety_days | 7 | 0.444 | 0.879 | 25.169 | 73.508 | 0.15 | 125.7 |
| stock_factor_range | (0.2, 3.0) | 0.610 | 1.131 | 24.752 | 73.508 | 0.12 | 125.7 |
| stock_factor_range | (0.5, 2.0) | 0.648 | 1.838 | 24.006 | 73.508 | 0.12 | 125.7 |
| stock_factor_range | (0.1, 4.0) | 0.494 | 0.873 | 25.125 | 73.508 | 0.12 | 125.7 |
| lead_time_range | (3, 10) | 0.151 | 1.151 | 25.190 | 73.508 | 0.07 | 125.7 |
| lead_time_range | (5, 20) | 0.610 | 1.131 | 24.752 | 73.508 | 0.12 | 125.7 |
| lead_time_range | (10, 30) | 1.190 | 1.205 | 24.098 | 73.508 | 0.18 | 125.7 |

The rule responds in the expected direction, and now does so strongly. Raising the
lead-time range from (3,10) to (10,30) raises the Urgent share eightfold (0.15% to
1.19%), because a longer wait for resupply means a given stock level covers
proportionally less of it. Before the fix the same sweep moved Urgent only from 2.69% to
3.02%: most Urgent rows were rounding artefacts that no parameter could reach. Adding
safety days raises both the reorder point and the stock drawn from it, so fewer rows
fall short. The median days of inventory no longer moves with the stock factor because
the median row is a slow seller holding its one-unit floor.

## 6. Sanity against the real data

![Distributions](figures/inv_01_distributions.png)

The real sales rate is extremely skewed: the median seller-product sells
0.0080 units per day. The synthetic stock inherits that
skew because it is computed from demand over the cover period, which is computed from the rate.

![Stock scales with speed](figures/inv_02_stock_vs_speed.png)

The reorder point now rises across every sales-rate decile, from 0.10 units in the
slowest to 2.43 in the fastest (Spearman rho = 0.929 against the rate, up from 0.545
when it was rounded up to whole units). Stock follows the rate at rho = 0.540, up from 0.204.

| decile | mean rate / day | mean reorder point | mean stock |
|---|---|---|---|
| D1 (slowest) | 0.006 | 0.10 | 1.00 |
| D5 | 0.017 | 0.26 | 1.00 |
| D7 | 0.027 | 0.42 | 1.04 |
| D9 | 0.056 | 0.86 | 1.54 |
| D10 (fastest) | 0.156 | 2.43 | 3.87 |

Stock is exactly one unit for 86.6% of scored rows, and that is intended: a seller
listing a product that sells once every few months holds one of it, and one unit is
months of cover, so the row is correctly Healthy. Stock only exceeds one unit where
demand over the cover period does, which is the fastest three deciles.

### What changed on 2 November 2026, and why

The first version computed stock as `round(reorder_point x factor)` with the reorder
point rounded up to a whole unit, at least 1. Measured on this table, that produced:

| | before | after |
|---|---|---|
| Urgent rows | 966 | 206 |
| Urgent rows that are urgent only because stock rounded to 0 | 85.3% | 0% |
| Median sales rate, Urgent vs Healthy | 1.1x | **5.7x** |
| Scored rows at or below their reorder point yet Healthy | 2,776 of 8,951 | 0 |
| Spearman, stock vs rate | 0.204 | 0.540 |
| Urgent share across 30 seeds | 2.944% +/- 0.095 | 0.579% +/- 0.040 |

When the random factor fell below 0.5, a reorder point of 1 rounded to zero stock,
which read as a stock-out, so whether a slow seller was Urgent came down to a coin flip.
Simply dropping the integer ceiling makes this worse, not better: computing stock from
the fractional reorder point rounds 96.6% of Urgent rows to zero and makes Urgent rows
sell *slower* than Healthy ones (0.4x). The fix needed both parts: a fractional reorder
point, so it agrees with the status rule, and a one-unit floor on stock, so rounding
cannot invent a stock-out. The Urgent rows that remain are genuine: median 10.8 days of
cover against a median 14.5-day lead time.

## 7. Limitations

- **Stock is simulated.** `current_quantity`, `lead_time_days` and `last_restock_date`
  are invented. Restock flags demonstrate that the pipeline and the rule logic work;
  they are not statements about any real seller's warehouse.
- **Stock-outs are not modelled.** The one-unit floor means no row starts at zero
  stock. Real sellers do run out, but the share that do is not something Olist lets us
  calibrate, so it is left out rather than guessed. Urgent therefore means "will run out
  before a reorder arrives", never "has already run out".
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

Re-running with seed 42 must reproduce SHA-256 `8afabc716a0ea56be42555a942ec21c2...`,
through either the pandas reader or `ECOM_FAST_READER=1`.
