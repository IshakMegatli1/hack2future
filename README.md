# Chrome & Oak Action Center

A dashboarding tool for Chrome & Oak Office Supply that watches the sales, returns, and invoice data, flags the situations that cost money, and drafts the action for the person who can fix it.

Built for the Business Track challenge (Option B: Sales & Finance), 4 hours, team of 2.

<!-- TODO: add a screenshot -->

---

## The problem

On paper, Chrome & Oak has never looked better: revenue is up 33% year over year (Jan–Sep). Underneath, the leadership team is describing symptoms that don't match the headline:

| Who | What they said | What the data says |
|---|---|---|
| CEO | "Revenue is up about a third. Atlantic punches above its weight." | Revenue is up 33%, but **margin is up only 21%**, and Atlantic's growth comes with the thinnest margins in the company. |
| CFO | "Revenue is growing but profit isn't keeping up, and I'm chasing unpaid invoices." | Margin fell from 29.9% to 27.2% of revenue. 92 invoices ($250K) are unpaid, 54 of them overdue ($135K). |
| Operations | "Returns are eating my warehouse team's time, especially the big items." | One product, the ErgoLift Standing Desk, is behind 79 of 103 damaged-in-transit returns. |
| Customer Success | "Long-time business customers have gone quiet." | Regular customers who received a damaged delivery are about 3x more likely to stop ordering. |

The problem we chose to solve first is **damage in transit**, because it is concentrated, measurable, and fixable by one team, and it shows up in the refunds, the warehouse workload, and the lost customers at once.

## What we found

1. **Revenue is growing faster than profit.** Jan–Sep 2026 vs 2025: revenue +33%, margin +21%.
2. **One rep drives the gap.** R07 (Atlantic)  is the top seller at $1.98M but discounts 23% on average, while every other rep sits at 8–11%. Margin is 16% against 31–34% for the rest, all 40 loss-making orders belong to R07. All 46 "Overstock / ordered in error" returns ($150K) trace back to R07 reseller orders.
3. **Damage is a desk problem in two regions.** ErgoLift Standing Desks are damaged in about 31% of BC orders and 30% of Prairies orders, against 5–9% in Ontario, Quebec, and Atlantic. Desks account for $248K of the $269K refunded for transit damage.
4. **Damage costs customers, not just refunds.** Among business customers with 5+ orders, 34% of those who received a damaged delivery have gone 90+ days without ordering, against 10% of those who didn't. This is a strong association, not proof of cause.
5. **Unpaid invoices are a big a time constraint problem** with 92 business invoices ($250K) that are unpaid, and 54 that are overdue ($135K). Only one customer is near its credit limit. The invoices take a lot of time to pursue, which our solution automates by having a button that allows executives to immediately be able to send an email in one click for each warning alert that comes in.

## What the app does

The Action Center follows the challenge flow:

```
DATA  →  DETECT  →  DECIDE  →  ACT
```

| Condition detected | Rule | Who is told | Action |
|---|---|---|---|
| **Damage spike** (primary automation) | A product/region pair has more than 10% of orders damaged in transit, with at least 20 orders | Operations Manager | Drafts a message with the numbers and the affected orders, waits for approval, sends it, and logs it |
| **Overdue or soon-due invoices** | Business invoice unpaid past its due date, or due within 5 days | Account rep and customer | Previews reminder messages, sends on approval, logs it |
| **Credit limit pressure** | Open invoices at 75% (warning) or 90% (urgent) of a customer's credit limit | Account rep | Flags the customer for review |
| **Rep pricing outlier** (shown as evidence) | Rep with average discount and quarter-end loading well above peers | Sales leadership | Evidence view, no automatic action |

**What if the alert is wrong?** Nothing is sent without a human approving it, the threshold is adjustable in the app, and every alert, approval, and dismissal is written to `alerts_log.csv` so false alarms can be traced and the rule tuned.

**Simulation:** change the damage threshold or the as-of date and watch which alerts appear and disappear.

## Screens

- **Action Center:** headline numbers and the open alerts, each with its next action.
- **Damage & returns:** heatmap of damage rate by product and region, with the orders behind each alert.
- **Invoices & credit:** open, due-soon, and overdue invoices and credit usage per customer.
- **Rep pricing:** discount versus margin per rep, and quarter-end loading.
- **Rules & thresholds:** the settings that drive every detection.

## Quick start

```bash
git clone <repo-url>
cd <repo-name>
pip install -r requirements.txt
streamlit run app.py
```

Requires Python 3.10+. Main libraries: `pandas`, `plotly`, `streamlit`.

## Repository layout

```
.
├── app.py                 # The web app (Action Center)
├── analysis.ipynb         # Clean up code
├── data/
│   ├── orders.csv         # Raw
│   ├── customers.csv      # Raw
│   ├── returns.csv        # Raw
│   └── orders_clean.csv   # Cleaned, one row per order
├── DATA.md                # Column dictionary and cleaning details
├── requirements.txt
└── README.md
```


## The data

Three raw files from Chrome & Oak's systems (Jan 2025 to Sep 2026, extracted 31 Oct 2026) were cleaned and joined into `orders_clean.csv`: **6,136 orders, one per row.** The full column dictionary is in [DATA.md](DATA.md).

| Issue in raw data | Fix |
|---|---|
| 25 exact duplicate orders | Removed |
| 8 orders with negative quantity | Removed (they produced negative revenue) |
| 122 dates in `MM/DD/YYYY` while the rest were `YYYY-MM-DD` | Parsed, none dropped |
| 181 discounts entered as percentages (`10.0`) instead of fractions (`0.10`) | Divided by 100 |
| Region written 14 ways, product written 22 ways | Standardised to 5 regions and 10 products |
| 92 missing unit costs | Filled with the product's median cost, flagged in `cost_was_missing` |

Added columns include `revenue`, `cost`, `margin`, `due_date`, `is_unpaid`, `days_late`, `days_overdue`, `quarter`, and `days_to_quarter_end`.

**Why it matters:** the first version of the date handling silently dropped 122 orders, and the percentage discounts produced negative revenue, so every total would have been wrong. Cleaning changed the numbers, not just the tidiness.

## Assumptions and limits

- Revenue is **gross**; refunds are subtracted separately.
- The 122 non-ISO dates were read as month-first. The samples checked had days above 12, but not every one was verified.
- Any discount above 1 was treated as a percentage.
- "As of" is fixed at **2026-10-31**, the extraction date, so overdue figures are measured against that day rather than today.
- Customers counted as "gone quiet" had no order in the 90 days before the last order date in the data.
- Median unit cost stands in for 92 missing costs, which slightly affects margin on those rows.
- Email sending is simulated: messages are drafted, shown, and logged, not delivered to real addresses.

## Team

Ishak Megatli · Amine Essif