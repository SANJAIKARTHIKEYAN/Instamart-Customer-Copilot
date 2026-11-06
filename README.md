# Instamart Customer Intelligence & Support Copilot

## Overview

A reproducible, offline capstone using synthetic data to build a trusted analytical database, customer segments and lapse predictions, guarded support-ticket triage, and a policy-grounded refund agent. All monetary amounts are in INR. The supplied `generate_data.py` and `mock_llm.py` are used without modification; no API key or hosted model is required.

## Reproduce

Run these commands from the repository root with Python 3.11 or newer. SQLite is bundled with Python.

1. `python -m venv .venv`
2. Windows PowerShell: `.venv\Scripts\Activate.ps1` (Windows cmd: `.venv\Scripts\activate.bat`; macOS/Linux: `source .venv/bin/activate`)
3. `python -m pip install --upgrade pip`
4. `python -m pip install -r requirements.txt`
5. `python generate_data.py`
6. `python run_part_a.py`
7. `python -m src.part_a.analyze_sql`
8. `python -m src.part_a.validate_data`

The generator's final line must be exactly `generated: customers=1200 products=40 orders_raw=13084 tickets=164`. The pipeline creates clean CSVs, the SQLite database, and `outputs/raw_audit.json`. The analysis script executes all seven SQL queries and saves `outputs/part_a_analysis.json`. After Parts B–D are implemented, their commands will be added here in execution order.

## Part A

### Raw-data audit

Raw shapes and dtypes:

| Table | Shape (rows × columns) | Column dtypes |
|---|---:|---|
| customers | 1,200 × 5 | `customer_id` object; `city` object; `signup_date` object; `age` float64; `gender` object |
| products | 40 × 4 | `product_id` object; `product_name` object; `category` object; `price_inr` int64 |
| orders | 13,084 × 9 | `order_id` object; `customer_id` object; `product_id` object; `quantity` int64; `order_ts` object; `status` object; `discount_pct` int64; `order_amount` object; `delivery_minutes` float64 |
| tickets | 164 × 5 | all five columns object; `keep_default_na=False` preserves empty ticket text as an empty string |

Raw missing values (count and percentage for every column):

| Table | Column | Missing count | Missing % |
|---|---|---:|---:|
| customers | customer_id | 0 | 0.00% |
| customers | city | 0 | 0.00% |
| customers | signup_date | 0 | 0.00% |
| customers | age | 61 | 5.08% |
| customers | gender | 30 | 2.50% |
| products | product_id | 0 | 0.00% |
| products | product_name | 0 | 0.00% |
| products | category | 0 | 0.00% |
| products | price_inr | 0 | 0.00% |
| orders | order_id | 0 | 0.00% |
| orders | customer_id | 0 | 0.00% |
| orders | product_id | 0 | 0.00% |
| orders | quantity | 0 | 0.00% |
| orders | order_ts | 0 | 0.00% |
| orders | status | 0 | 0.00% |
| orders | discount_pct | 0 | 0.00% |
| orders | order_amount | 53 | 0.41% |
| orders | delivery_minutes | 2,541 | 19.42% |
| tickets | ticket_id | 0 | 0.00% |
| tickets | customer_id | 0 | 0.00% |
| tickets | order_id | 0 | 0.00% |
| tickets | text | 0 | 0.00% |
| tickets | true_category | 0 | 0.00% |

The order amount audit also identifies 120 values that cannot be parsed as numbers; this count includes values represented as blank/NA by pandas as well as text such as `N/A` and `error`.

| Audit measure | Observed value |
|---|---:|
| Raw order rows | 13,084 |
| Exact duplicate rows | 119 |
| Pending rows | 656 |
| Distinct order IDs | 12,309 |
| Unparseable order amounts | 120 |
| Negative delivery durations | 106 |
| Blank delivery durations | 2,541 |
| Blank ages | 61 |
| Ages outside 10–100 | 6 |
| Distinct raw city spellings | 24 |
| Distinct nonblank raw gender spellings | 10 |
| Blank genders | 30 |

### Cleaning rules and results

**Customers**

1. Strip city whitespace and apply title case; this normalizes 24 raw spellings to six cities.
2. Map all gender spellings case-insensitively to `male` or `female`; blank and unrecognized values become `unknown`.
3. Treat ages outside 10–100 as missing (6 invalid ages), then fill missing ages (61 originally blank plus 6 invalid) with the median age for that city using `groupby(...).transform('median')`.
4. Parse `signup_date` as a datetime.

| Cleaned city | Customers | Cleaned gender | Customers |
|---|---:|---|---:|
| Pune | 227 | female | 610 |
| Delhi | 210 | male | 560 |
| Bengaluru | 197 | unknown | 30 |
| Chennai | 191 | | |
| Hyderabad | 191 | | |
| Mumbai | 184 | | |

All 1,200 ages are populated and fall between 18 and 60. City counts and gender counts match the reference checkpoints.

**Orders**

1. Parse `order_ts` as a datetime.
2. Remove 119 exact duplicate rows.
3. Sort by `order_id` and timestamp, then retain the latest row for each order ID. This resolves the earlier pending records; final data has one row per order ID and no pending statuses.
4. Convert `order_amount` to numeric and fill all 120 unparseable values using `round(price_inr × quantity × (1 − discount_pct / 100), 2)` from the product catalogue.
5. Replace negative delivery durations with missing values. For completed orders only, impute missing delivery duration with the median for the product category among completed orders. Leave cancelled-order delivery durations missing because no delivery occurred.

The cleaning sequence removes 775 rows in total (119 exact duplicates and 656 pending records after exact-deduplication), leaving 12,309 orders: 11,110 completed and 1,199 cancelled. There are no missing order amounts, no missing delivery durations among completed orders, and 1,199 missing delivery durations among cancelled orders. Completed-order revenue is **INR 2,998,668.80**.

### Store and validate

Clean tables are written to `data/clean/customers.csv`, `data/clean/products.csv`, and `data/clean/orders.csv`; the SQLite database `data/instamart.db` contains tables `customers`, `products`, and `orders`. The validation script checks more than eight reference checkpoints and prints `ALL CHECKPOINTS PASSED` only when the assertions pass.

### SQL analysis

All seven queries are stored in `sql/queries.sql` and executed with `pandas.read_sql_query` against the SQLite database.

| Query | Result |
|---|---|
| Q1 — `WHERE` and `HAVING` | 30 customers |
| Q2 — three-table join | 30 city/category rows; total revenue INR 2,998,668.80; largest cell Bengaluru / Electronics at INR 233,909.45 |
| Q3 — scalar subquery | 11 products priced above catalogue average |
| Q4 — `LEFT JOIN` | 25 customers with no completed order |
| Q5 — CTEs | 550 customers above the mean completed spend; average customer spend INR 2,552.06 |
| Q6 — ranking windows | Top customers: Bengaluru C0082 (INR 12,856.20); Chennai C0930 (INR 10,151.40); Delhi C0291 (INR 13,742.60); Hyderabad C0743 (INR 12,730.05); Mumbai C0693 (INR 14,766.55); Pune C0426 (INR 10,377.10). Eight rows have `RANK()` different from `ROW_NUMBER()`. |
| Q7 — running total | 183 daily rows; final cumulative revenue INR 2,998,668.80 |

`RANK()` leaves gaps after tied values, while `ROW_NUMBER()` assigns a unique sequential number to every row, so ties can make the two rankings differ.

### Pandas cross-check and exploratory analysis

The `pivot_table(..., margins=True)` grand total is INR 2,998,668.80, matching SQL Q2. City aggregates for completed orders:

| City | Sum (INR) | Mean (INR) | Orders |
|---|---:|---:|---:|
| Bengaluru | 523,643.40 | 276.47 | 1,894 |
| Chennai | 463,629.15 | 272.72 | 1,700 |
| Delhi | 502,829.80 | 243.62 | 2,064 |
| Hyderabad | 528,589.90 | 284.95 | 1,855 |
| Mumbai | 479,058.50 | 297.00 | 1,613 |
| Pune | 500,918.05 | 252.48 | 1,984 |

Completed order amount has mean INR 269.91, median INR 135.00, skewness 4.61, Q1 INR 64.80 and Q3 INR 297.00. The 1.5×IQR fences are −INR 283.50 and INR 645.30; there are zero values below the lower fence and 897 above the upper fence.

The data describes synthetic completed purchases across six cities and five product categories. Order amounts are strongly right-skewed: the mean is much higher than the median, and 897 orders exceed the upper outlier fence, plausibly reflecting larger quantities or expensive electronics. The largest absolute pairwise correlation is between order amount and discount percentage (about −0.095); order amount and quantity is about +0.087. Both relationships are weak, and correlation of this size does not establish causation.

### Part A verification status

Verified in the current runtime: raw audit counts match the brief; customer city/gender distributions match; cleaned order counts and completed revenue match; the SQLite tables exist; all seven SQL queries return the reference counts/totals; and pandas cross-checks match. `outputs/raw_audit.json` and `outputs/part_a_analysis.json` preserve the measured results.

## Part B

Not implemented yet. This section will be completed after Part A is frozen and verified.

## Part C

Not implemented yet. This section will be completed after Part B is frozen and verified.

## Part D

Not implemented yet. This section will be completed after Part C is frozen and verified.

## Limitations and Next Steps

The data and policy documents are synthetic and fictional. No real customer records, live payment systems, hosted LLMs, or API keys are used. Next, implement Parts B–D in dependency order, record actual metrics and outputs, then rerun the complete reproduction sequence from a clean clone. The Premium-segment retention list in Part B is a post-hoc whole-window label and must be described as illustrative, not a leakage-free evaluation.
