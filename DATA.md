# Orders Dataset (Cleaned)

One cleaned, analysis-ready table of sales orders, joined with customer and return details.

| | |
|---|---|
| **File** | `orders_clean.csv` |
| **Grain** | One row per order (`order_id` is unique) |
| **Rows / columns** | 6,136 rows × 35 columns |
| **Order dates** | 2025-01-01 to 2026-09-30 |
| **Customers** | 1,204 distinct `customer_id` values |
| **Sources** | `orders.csv`, `customers.csv`, `returns.csv` (raw) |

Snapshot figures in this README (totals, counts) were measured on this exact file. They do not update if the file changes.

---

## Quick start

```python
import pandas as pd

date_cols = ['order_date', 'payment_date', 'signup_date', 'due_date', 'return_date']
df = pd.read_csv('orders_clean.csv', parse_dates=date_cols)

df['revenue'].sum()                                   # gross revenue (before refunds)
df['revenue'].sum() - df['refund_amount'].sum()       # net of refunds (refund_amount is blank when no return)
df.groupby('region')['margin'].sum()
```

Dates are saved as plain `YYYY-MM-DD` text, so pass `parse_dates` when loading.

---

## What was cleaned

Raw `orders.csv` had 6,169 rows; the final file has 6,136.

| Issue in raw data | Fix |
|---|---|
| 25 exact duplicate order rows | Removed |
| 8 orders with a negative quantity | Removed (they produced negative revenue) |
| 122 order dates in `MM/DD/YYYY` instead of `YYYY-MM-DD` | Parsed into real dates; none lost |
| 181 discounts entered as percentages (e.g. `10.0`) instead of fractions (`0.10`) | Divided by 100; discount now always between 0 and 0.5 |
| Region written 14 different ways (`ON`, `ontario`, `Québec`, `B.C.` …) | Standardised to 5 values |
| Product written 22 different ways (`Mech Keyboard`, `24in Monitor` …) | Standardised to 10 products |
| 92 orders with a missing `unit_cost` | Filled with the median unit cost of that product; flagged in `cost_was_missing` |
| Payment, signup, return dates stored as text | Converted to dates |

Then joined on keys, with no rows added or lost: orders ← customers (on `customer_id`), orders ← returns (on `order_id`, at most one return per order).

---

## Column dictionary

### Order

| Column | Description |
|---|---|
| `order_id` | Unique order ID (`SO-000001`…) |
| `order_date` | Date the order was placed |
| `customer_id` | Customer ID (`C0001`…) |
| `region` | Atlantic, BC, Ontario, Prairies, Quebec |
| `product` | One of 10 products |
| `category` | Accessories, Displays, Furniture |
| `quantity` | Units ordered (always ≥ 1) |
| `unit_price` | List price per unit |
| `discount` | Discount as a fraction (0.10 = 10%) |
| `unit_cost` | Cost per unit (see `cost_was_missing`) |
| `sales_channel` | Direct Sales, Online, Partner |
| `sales_rep` | Rep ID (`R01`–`R11`); blank for Online orders |
| `payment_date` | Date payment was received; blank if unpaid |
| `cost_was_missing` | `True` if `unit_cost` was blank in the raw data and was filled with the product median (92 rows) |

### Customer

| Column | Description |
|---|---|
| `segment` | Consumer, SMB, Enterprise, Reseller |
| `signup_date` | Date the customer signed up |
| `account_rep` | Assigned account rep; blank for Consumers. Identical to `sales_rep` in every row |
| `payment_terms` | Prepaid, Net 30, Net 60 |
| `credit_limit` | Customer credit limit (0 for Consumers) |

### Calculated money columns

| Column | Formula |
|---|---|
| `revenue` | `quantity × unit_price × (1 − discount)`. This is **gross**: refunds are not subtracted |
| `cost` | `quantity × unit_cost` |
| `margin` | `revenue − cost` |

### Calculated payment columns

| Column | Description |
|---|---|
| `terms_days` | Days allowed to pay: Prepaid = 0, Net 30 = 30, Net 60 = 60 |
| `due_date` | `order_date + terms_days` |
| `is_unpaid` | `True` when there is no `payment_date` (92 orders) |
| `days_to_pay` | `payment_date − order_date` (blank if unpaid) |
| `days_late` | `payment_date − due_date`; negative means paid early (blank if unpaid) |
| `days_overdue` | Unpaid orders only: **2026-10-31** minus `due_date`. Negative means not yet due as of that date. Blank for paid orders |

### Time columns

| Column | Description |
|---|---|
| `quarter` | Calendar quarter of the order, e.g. `2025Q1` |
| `days_to_quarter_end` | Days from `order_date` to the end of that quarter |

### Return columns (blank when the order had no return)

| Column | Description |
|---|---|
| `was_returned` | `True` if the order has a return (275 orders) |
| `return_date` | Date of the return |
| `quantity_returned` | Units returned (never more than ordered) |
| `return_reason` | Damaged in transit, Changed mind, Overstock / ordered in error, Defective, Wrong item shipped |
| `refund_amount` | Amount refunded |

---

## Snapshot figures

| Metric | Value |
|---|---|
| Gross revenue (`revenue`) | $7,973,577 |
| Total cost (`cost`) | $5,703,750 |
| Margin | $2,269,827 |
| Refunds | $551,404 |
| Orders with a return | 275 (4.5% of orders) |
| Unpaid orders | 92 (about $250,004 in revenue) |
| Unpaid orders past due as of 2026-10-31 | 54 |

---

## Things to know before analysing

- **Revenue is gross.** For net revenue subtract `refund_amount`, filling blanks with 0 first (`df['refund_amount'].fillna(0)`).
- **Blank does not always mean missing.** `sales_rep` and `account_rep` are blank for all 1,747 Online/Consumer orders. Return columns are blank for the 5,861 orders with no return. `payment_date` is blank for the 92 unpaid orders.
- **Some columns are redundant.** Consumer = Online = Prepaid (1,747 orders each); Reseller = Partner (725); Net 60 = Enterprise (862); Net 30 = SMB + Reseller. Don't treat `segment`, `sales_channel` and `payment_terms` as independent signals. `sales_rep` and `account_rep` are the same column.
- **Imputed costs.** 92 rows use a product-median `unit_cost`. Filter on `cost_was_missing` if you need strictly observed margin.
- **40 orders have negative margin.** Their discount pushes the price below cost. They are real data, not errors.
- **The overdue date is fixed.** `days_overdue` is measured against 2026-10-31, not today's date. Recompute it from `due_date` if you want a different as-of date.
- **Removed negative-quantity orders may be refunds or entry errors.** They were dropped rather than corrected, so check the raw file if you need to account for them.

---

## Assumptions made during cleaning

- All 122 non-ISO order dates were read as month-first (`MM/DD/YYYY`). Samples checked had days above 12, so none could be day-first, but every one was not verified.
- Any discount above 1 was treated as a percentage and divided by 100.
- Median unit cost per product is a reasonable stand-in for the 92 missing costs.