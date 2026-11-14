"""Chrome & Oak - detection and action dashboard.

Run:  streamlit run app.py      (orders_clean.csv must be in the same folder)

HOW THIS FILE IS ORGANISED
  1. Settings and data loading
  2. DETECTIONS   - one function per detection. Each returns a table of alerts.
  3. AUTOMATIONS  - one function per automation. Each acts on the alerts.
  4. REGISTRY     - the list of every detection and automation, built or not.
  5. PAGE         - sidebar, tabs and charts.

TO ADD A DETECTION: fill in one of the "SLOT" functions in section 2 and switch
its status to "active" in section 4. Nothing else needs to change.
"""
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import plotly.express as px
import streamlit as st

# ----------------------------------------------------------------------------
# 1. SETTINGS AND DATA
# ----------------------------------------------------------------------------
DATA_FILE = "orders_clean.csv"
LOG_FILE = "alerts_log.csv"

# The data has no customer email addresses, so reminders use this placeholder.
# Replace it with the real address column when one exists.
CUSTOMER_EMAIL = "{customer_id}@example.com"

# Chrome & Oak theme: pale background, oak brown and steel blue for the charts.
OAK, STEEL, GREY = "#b06a24", "#2f72ad", "#aab3bc"
INK, PAPER, PANEL, LINE = "#2b2622", "#faf7f2", "#ffffff", "#e2dacd"
CHART, SMALL_CHART, WIDGET_ROW = 290, 225, 72   # chart heights in pixels; lower them on a small screen
LEVEL_COLORS = {"OK": GREY, "Warning": "#fab219", "Urgent": "#ec835a", "Critical": "#d03b3b"}
LEVEL_ORDER = ["Critical", "Urgent", "Warning"]
ALERT_COLUMNS = ["detection", "level", "subject", "detail", "amount", "action", "notify"]

st.set_page_config(page_title="Chrome & Oak - Detect & Act", layout="wide")
st.markdown(f"""
<style>
.stApp {{ background: {PAPER}; color: {INK}; }}
[data-testid="stSidebar"] {{ background: #f1ebe2; }}
.block-container {{ padding-top: 2.4rem; padding-bottom: 1rem; }}
.brand {{ font-size: 1.5rem; font-weight: 700; letter-spacing: 0.06em; margin-bottom: 0.2rem; }}
.brand-chrome {{ color: #6f7b87; }} .brand-amp {{ color: {INK}; font-weight: 400; }}
.brand-oak {{ color: #8a4f17; }}
.brand-sub {{ font-size: 0.85rem; font-weight: 400; letter-spacing: 0; color: #6b635b; margin-left: 0.8rem; }}
[data-testid="stVerticalBlockBorderWrapper"] {{ background: {PANEL}; border-color: {LINE}; }}
[data-testid="stMetric"] {{ background: {PAPER}; border: 1px solid {LINE}; border-left: 4px solid {OAK};
                            border-radius: 6px; padding: 6px 12px; }}
[data-testid="stMetricValue"] {{ font-size: 1.35rem; }}
[data-testid="stAlert"] {{ padding: 0.5rem 0.8rem; }}
.section-title {{ font-weight: 700; color: #8a4f17; border-bottom: 2px solid {LINE};
                  padding-bottom: 2px; margin-bottom: 6px; }}
</style>
""", unsafe_allow_html=True)


def section(title):
    """A bordered box with a title. Use it as:  with section("Charts"): ..."""
    box = st.container(border=True)
    box.markdown(f"<div class='section-title'>{title}</div>", unsafe_allow_html=True)
    return box


def show(fig, where=None, height=CHART, key=None):
    """Draw a chart with the house style and a fixed height, so a tab's charts fit one screen."""
    fig.update_layout(
        height=height, margin={"l": 8, "r": 8, "t": 46, "b": 8},
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font={"color": INK, "size": 12}, title_font_size=14,
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.0, "xanchor": "right", "x": 1, "title_text": ""},
    )
    (where or st).plotly_chart(fig, use_container_width=True, key=key)


@st.cache_data
def load_data():
    return pd.read_csv(
        DATA_FILE, parse_dates=["order_date", "payment_date", "due_date", "return_date"]
    )


def no_alerts():
    """Empty alert table. Every detection returns this shape."""
    return pd.DataFrame(columns=ALERT_COLUMNS)


def make_alerts(rows):
    return pd.DataFrame(rows, columns=ALERT_COLUMNS) if rows else no_alerts()


def show_flagged(part, what, none_message, limit=3):
    """Show the most serious flagged items as colored boxes in one row, so the
    reader sees what needs attention before any chart."""
    if part.empty:
        st.success(none_message)
        return
    ranked = part.assign(rank=part["level"].map({"Critical": 0, "Urgent": 1, "Warning": 2}))
    ranked = ranked.sort_values(["rank", "amount"], ascending=[True, False])
    more = f", showing the {limit} most serious" if len(ranked) > limit else ""
    st.markdown(f"**{len(part)} {what}**{more}")
    for col, r in zip(st.columns(limit), ranked.head(limit).itertuples()):
        box = {"Critical": col.error, "Urgent": col.warning, "Warning": col.info}[r.level]
        box(f"**{r.subject}**  \n{r.level}: {r.detail} - ${r.amount:,.0f}")


def open_invoices(df, as_of):
    """Business invoices ordered by `as_of` and not yet paid on that day."""
    biz = df[df["segment"] != "Consumer"]
    is_open = (biz["order_date"] <= as_of) & (biz["payment_date"].isna() | (biz["payment_date"] > as_of))
    inv = biz[is_open].copy()
    inv["days_until_due"] = (inv["due_date"] - as_of).dt.days
    return inv


# ----------------------------------------------------------------------------
# 2. DETECTIONS
#    Each function returns a table with the columns in ALERT_COLUMNS:
#    detection | level | subject | detail | amount | action | notify
# ----------------------------------------------------------------------------

# --- D1. TRANSIT DAMAGE WATCH (active) --------------------------------------
def damage_table(df, min_orders):
    d = df.assign(
        damaged=df["return_reason"] == "Damaged in transit",
        damage_refund=df["refund_amount"].where(df["return_reason"] == "Damaged in transit", 0),
    )
    t = d.groupby(["product", "region"]).agg(
        orders=("order_id", "count"), damaged=("damaged", "sum"), refunds=("damage_refund", "sum")
    )
    t["damage_rate"] = t["damaged"] / t["orders"]
    t["enough_orders"] = t["orders"] >= min_orders
    return t.reset_index()


def detect_transit_damage(df, threshold, min_orders):
    """Alert when the share of orders damaged in transit, for one product in one
    region, is above the threshold."""
    t = damage_table(df, min_orders)
    hits = t[(t["damage_rate"] > threshold) & t["enough_orders"]]
    rows = []
    for r in hits.itertuples():
        rows.append([
            "Transit Damage Watch",
            "Critical" if r.damage_rate > 2 * threshold else "Urgent",
            f"{r.product} to {r.region}",
            f"{r.damage_rate:.0%} of orders damaged",
            r.refunds,
            "Review the carrier and packaging on this route",
            "Operations Manager",
        ])
    return make_alerts(rows)


def quiet_after_damage(df, as_of, quiet_days, min_orders=5):
    """One row per regular business customer: did they get a damaged delivery,
    and have they stopped ordering (no order in the last `quiet_days` days)?"""
    biz = df[df["segment"] != "Consumer"]
    dmg = biz[biz["return_reason"] == "Damaged in transit"]
    c = biz.groupby("customer_id").agg(
        segment=("segment", "first"), region=("region", "first"), rep=("account_rep", "first"),
        orders=("order_id", "count"), revenue=("revenue", "sum"), last_order=("order_date", "max"))
    c["damaged_deliveries"] = dmg.groupby("customer_id").size()
    c["damaged_deliveries"] = c["damaged_deliveries"].fillna(0).astype(int)
    c["last_damaged_order"] = dmg.groupby("customer_id")["order_date"].max()
    c["days_quiet"] = (as_of - c["last_order"]).dt.days
    c["quiet"] = c["days_quiet"] > quiet_days
    c["group"] = ["Had a damaged delivery" if n > 0 else "No damaged delivery" for n in c["damaged_deliveries"]]
    return c[c["orders"] >= min_orders].reset_index()


# --- D2. CREDIT LIMIT GUARD (paused) ----------------------------------------
def credit_table(inv):
    t = inv.groupby("customer_id").agg(
        owed=("revenue", "sum"), open_invoices=("order_id", "count"),
        credit_limit=("credit_limit", "first"), segment=("segment", "first"),
        payment_terms=("payment_terms", "first"), rep=("account_rep", "first"),
    )
    t["used"] = t["owed"] / t["credit_limit"]
    return t.reset_index()


def credit_level(used, warn, urgent):
    if used >= 1:
        return "Critical"
    if used >= urgent:
        return "Urgent"
    if used >= warn:
        return "Warning"
    return "OK"


def detect_credit_limit(inv, warn, urgent):
    """Alert when a customer's unpaid invoices reach a share of its credit limit."""
    t = credit_table(inv)
    rows = []
    for r in t[t["used"] >= warn].itertuples():
        level = credit_level(r.used, warn, urgent)
        rows.append([
            "Credit Limit Guard", level, r.customer_id,
            f"{r.segment}, owes ${r.owed:,.0f} of a ${r.credit_limit:,.0f} limit ({r.used:.0%})",
            r.owed,
            "Block new credit orders until a payment arrives" if level == "Critical"
            else "Call the customer before accepting the next order",
            f"CFO and rep {r.rep}",
        ])
    return make_alerts(rows)


# --- D3. DUE DATE RADAR (active) --------------------------------------------
def detect_due_dates(inv, due_soon_days):
    """Alert when an invoice is due within N days, or is already overdue."""
    rows = []
    for r in inv[inv["days_until_due"] <= due_soon_days].itertuples():
        if r.days_until_due >= 0:
            when = "due today" if r.days_until_due == 0 else f"due in {r.days_until_due} days"
            level, detail = "Warning", f"{r.payment_terms}, {when}"
            action = "Send a friendly payment reminder"
        elif r.days_until_due >= -30:
            level, detail = "Urgent", f"{r.payment_terms}, {-r.days_until_due} days overdue"
            action = "Send an overdue notice"
        else:
            level, detail = "Critical", f"{r.payment_terms}, {-r.days_until_due} days overdue"
            action = "Phone the customer and pause new credit orders"
        rows.append(["Due Date Radar", level, f"{r.order_id} ({r.customer_id})", detail,
                     r.revenue, action, f"Accounts receivable and rep {r.account_rep}"])
    return make_alerts(rows)


# --- D8. REP DISCOUNT WATCH (active) ----------------------------------------
def rep_table(df):
    """One row per sales rep: region, discount, margin, quarter-end share."""
    biz = df[df["segment"] != "Consumer"]
    t = biz.groupby("sales_rep").agg(
        region=("region", lambda s: ", ".join(sorted(s.unique()))),
        customers=("customer_id", "nunique"), orders=("order_id", "count"),
        revenue=("revenue", "sum"), margin=("margin", "sum"),
        avg_discount=("discount", "mean"),
        loss_orders=("margin", lambda m: int((m < 0).sum())),
    )
    t["margin_pct"] = t["margin"] / t["revenue"]
    last_week = biz[biz["days_to_quarter_end"] < 7].groupby("sales_rep")["revenue"].sum()
    t["quarter_end_share"] = (last_week / t["revenue"]).fillna(0)
    overstock = biz[biz["return_reason"] == "Overstock / ordered in error"]
    t["overstock_refunds"] = overstock.groupby("sales_rep")["refund_amount"].sum()
    t["overstock_refunds"] = t["overstock_refunds"].fillna(0)
    t["overstock_returns"] = overstock.groupby("sales_rep").size()
    t["overstock_returns"] = t["overstock_returns"].fillna(0).astype(int)
    t["loss_amount"] = -biz[biz["margin"] < 0].groupby("sales_rep")["margin"].sum()
    t["loss_amount"] = t["loss_amount"].fillna(0)
    # Margin the other reps earn on the same amount of revenue.
    others_margin = t["margin"].sum() - t["margin"]
    others_revenue = t["revenue"].sum() - t["revenue"]
    t["peer_margin_pct"] = others_margin / others_revenue
    t["margin_given_up"] = (t["revenue"] * (t["peer_margin_pct"] - t["margin_pct"])).clip(lower=0)
    return t.reset_index()


def detect_rep_discount(df, threshold):
    """Alert when a rep's average discount on business orders is above the threshold."""
    t = rep_table(df)
    typical = t["avg_discount"].median()
    rows = []
    for r in t[t["avg_discount"] > threshold].itertuples():
        rows.append([
            "Rep Discount Watch",
            "Critical" if r.avg_discount > 2 * typical else "Urgent",
            f"{r.sales_rep} ({r.region})",
            f"{r.avg_discount:.0%} average discount, {r.margin_pct:.0%} margin",
            r.margin_given_up,
            "Review this rep's discounts and require approval for large ones",
            "CFO and Head of Sales",
        ])
    return make_alerts(rows)


# --- D4. DISCOUNT GATE (SLOT - not built yet) -------------------------------
def detect_discount_gate(df):
    """IDEA: alert on any business order with a discount above 25%.
    Useful columns: discount, segment, sales_rep, margin, revenue."""
    # TODO: write the rule here, then return make_alerts(rows)
    return no_alerts()


# --- D5. QUARTER-END LOADING CHECK (SLOT - not built yet) -------------------
def detect_quarter_end_loading(df):
    """IDEA: alert on reseller orders placed in the last 7 days of a quarter
    with a high discount. Useful columns: days_to_quarter_end, segment, discount."""
    # TODO
    return no_alerts()


# --- D6. QUIET CUSTOMER ALARM (SLOT - not built yet) ------------------------
def detect_quiet_customers(df, as_of):
    """IDEA: alert when a regular business customer has not ordered for 3 times
    its usual gap between orders. Useful columns: customer_id, order_date."""
    # TODO
    return no_alerts()


# --- D7. CHRONIC LATE PAYER FLAG (SLOT - not built yet) ---------------------
def detect_chronic_late_payers(df):
    """IDEA: alert when a customer is on average more than 10 days late over at
    least 5 paid invoices. Useful columns: customer_id, days_late."""
    # TODO
    return no_alerts()


# ----------------------------------------------------------------------------
# 3. AUTOMATIONS
#    Each function receives the alert table and does something with it.
# ----------------------------------------------------------------------------

# --- A1. ALERT LOG (active) -------------------------------------------------
def automation_alert_log(alerts, as_of):
    """Every new alert is written to a log automatically, once, with the time,
    the recommended action and who is notified. Nobody has to click anything."""
    if "log" not in st.session_state:
        try:
            st.session_state["log"] = pd.read_csv(LOG_FILE)
        except (FileNotFoundError, pd.errors.EmptyDataError):
            st.session_state["log"] = pd.DataFrame(columns=["key", "logged_at", "as_of", *ALERT_COLUMNS])
    log = st.session_state["log"]

    new = alerts.copy()
    new["as_of"] = str(as_of.date())
    new["key"] = new["as_of"] + "|" + new["detection"] + "|" + new["subject"]
    new = new[~new["key"].isin(log["key"])]
    if len(new):
        new["logged_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log = pd.concat([log, new[log.columns]], ignore_index=True)
        st.session_state["log"] = log
        try:
            log.to_csv(Path(LOG_FILE), index=False)
        except OSError:
            pass  # read-only folder: the log still lives in this session
    return log, len(new)


# --- A2. PAYMENT REMINDER DRAFTS (active) -----------------------------------
def automation_payment_reminders(alerts):
    """Every Due Date Radar alert gets a reminder message drafted automatically."""
    due = alerts[alerts["detection"] == "Due Date Radar"]
    drafts = []
    for r in due.itertuples():
        invoice, customer = r.subject.split(" (")
        customer = customer.rstrip(")")
        tone = "A quick reminder that" if r.level == "Warning" else "Our records show that"
        status = r.detail.split(", ")[1]
        subject = f"Chrome & Oak invoice {invoice}: {status}"
        message = (f"Hello,\n\n{tone} invoice {invoice} for ${r.amount:,.2f} is {status}. "
                   f"Please let us know if anything is blocking payment.\n\n"
                   f"Thank you,\nChrome & Oak Accounts Receivable")
        email = CUSTOMER_EMAIL.format(customer_id=customer)
        drafts.append({
            "to": customer, "email": email, "invoice": invoice, "level": r.level,
            "amount": r.amount, "subject": subject, "message": message,
            # Opens the computer's default mail app (Outlook desktop if it is the default).
            "outlook_desktop": f"mailto:{email}?subject={quote(subject)}&body={quote(message)}",
            # Opens a new message in Outlook on the web.
            "outlook_web": ("https://outlook.office.com/mail/deeplink/compose"
                            f"?to={quote(email)}&subject={quote(subject)}&body={quote(message)}"),
        })
    return pd.DataFrame(drafts, columns=["to", "email", "invoice", "level", "amount", "subject",
                                         "message", "outlook_desktop", "outlook_web"])


# --- A3. CARRIER REVIEW TICKET (SLOT - not built yet) -----------------------
def automation_carrier_ticket(alerts):
    """IDEA: for each Transit Damage Watch alert, open a ticket for Operations
    listing the damaged orders on that route."""
    # TODO
    return None


# --- A4. ORDER APPROVAL HOLD (SLOT - not built yet) -------------------------
def automation_order_hold(alerts):
    """IDEA: for each Discount Gate alert, mark the order 'on hold' until a
    manager approves it."""
    # TODO
    return None


# --- A5. WIN-BACK TASK (SLOT - not built yet) -------------------------------
def automation_win_back_task(alerts):
    """IDEA: for each Quiet Customer Alarm alert, create a follow-up task for
    Customer Success with the customer's last order and any damaged delivery."""
    # TODO
    return None


# ----------------------------------------------------------------------------
# 4. REGISTRY - every detection and automation, built or not
# ----------------------------------------------------------------------------
DETECTIONS = [
    ("D1", "Transit Damage Watch", "active", "Damage rate per product and region above a threshold"),
    ("D2", "Credit Limit Guard", "paused", "Customer at 75% / 90% / 100% of its credit limit"),
    ("D3", "Due Date Radar", "active", "Invoice due within N days, or already overdue"),
    ("D4", "Discount Gate", "slot", "Business order with a discount above 25%"),
    ("D5", "Quarter-End Loading Check", "slot", "Discounted reseller order in the last week of a quarter"),
    ("D6", "Quiet Customer Alarm", "slot", "Regular customer silent for 3x its usual gap"),
    ("D7", "Chronic Late Payer Flag", "slot", "Customer who pays late on almost every invoice"),
    ("D8", "Rep Discount Watch", "active", "Sales rep whose average discount is above a threshold"),
]
AUTOMATIONS = [
    ("A1", "Alert Log", "active", "Writes every new alert to a log with action and owner"),
    ("A2", "Payment Reminder Drafts", "active", "Drafts a reminder for each invoice due soon or overdue"),
    ("A3", "Carrier Review Ticket", "slot", "Opens a ticket for Operations on a damaged route"),
    ("A4", "Order Approval Hold", "slot", "Holds a heavily discounted order for approval"),
    ("A5", "Win-Back Task", "slot", "Creates a follow-up task for Customer Success"),
]

# ----------------------------------------------------------------------------
# 5. PAGE
# ----------------------------------------------------------------------------
df_all = load_data()

st.sidebar.header("Settings")
first_day = df_all["order_date"].min().date()
last_day = df_all["order_date"].max().date()   # no orders after this date
start_date, end_date = st.sidebar.slider(
    "Period (start date to end date)",
    min_value=first_day, max_value=last_day, value=(first_day, last_day), format="YYYY-MM-DD",
)
start_date, as_of = pd.Timestamp(start_date), pd.Timestamp(end_date)
st.sidebar.caption("Charts use orders inside the period. Invoices are judged as of the end date.")
regions = st.sidebar.multiselect("Regions", sorted(df_all["region"].unique()),
                                 default=sorted(df_all["region"].unique()))
st.sidebar.subheader("Thresholds")
damage_threshold = st.sidebar.slider("Damage rate alert (%)", min_value=2, max_value=40, value=10) / 100
min_orders = st.sidebar.slider("Minimum orders to judge a route", min_value=5, max_value=50, value=20)
rep_discount_threshold = st.sidebar.slider("Rep average discount alert (%)", min_value=5, max_value=30, value=15) / 100
due_soon_days = st.sidebar.slider("Remind this many days before due date", min_value=1, max_value=15, value=5)

in_regions = df_all[df_all["region"].isin(regions)]
df = in_regions[in_regions["order_date"].between(start_date, as_of)]
if df.empty:
    st.warning("No orders for this period and these regions.")
    st.stop()
# Invoices: every invoice still open on the end date counts, even one ordered
# before the start date. Otherwise old unpaid invoices would disappear.
inv = open_invoices(in_regions, as_of)

# Run every detection (slots return an empty table until you fill them in).
alerts = pd.concat([
    detect_transit_damage(df, damage_threshold, min_orders),   # D1
    # detect_credit_limit(inv, 0.75, 0.90),                    # D2 paused: not our focus
    detect_due_dates(inv, due_soon_days),                      # D3
    detect_discount_gate(df),                                  # D4 slot
    detect_quarter_end_loading(df),                            # D5 slot
    detect_quiet_customers(df, as_of),                         # D6 slot
    detect_chronic_late_payers(df),                            # D7 slot
    detect_rep_discount(df, rep_discount_threshold),           # D8
], ignore_index=True)

# Run every automation.
log, newly_logged = automation_alert_log(alerts, as_of)        # A1
reminders = automation_payment_reminders(alerts)               # A2
automation_carrier_ticket(alerts)                              # A3 slot
automation_order_hold(alerts)                                  # A4 slot
automation_win_back_task(alerts)                               # A5 slot

st.markdown(
    f"<div class='brand'><span class='brand-chrome'>CHROME</span> <span class='brand-amp'>&amp;</span> "
    f"<span class='brand-oak'>OAK</span> <span class='brand-sub'>Detect &amp; Act &nbsp;|&nbsp; orders "
    f"{start_date.date()} to {as_of.date()}</span></div>", unsafe_allow_html=True)

tab_overview, tab_reps, tab_damage, tab_invoices, tab_actions, tab_slots = st.tabs(
    ["Overview", "Sales reps", "Transit damage", "Overdue invoices", "Alerts & actions", "Detection slots"]
)

# Each tab is laid out the same way: flagged list and cards, then every chart
# in one screen, then the tables (scroll down for those).

# ---- Overview ---------------------------------------------------------------
with tab_overview:
    with section("Key figures"):
        overdue_amount = inv.loc[inv["days_until_due"] < 0, "revenue"].sum()
        k1, k2, k3, k4, k5 = st.columns(5)
        k1.metric("Revenue", f"${df['revenue'].sum():,.0f}")
        k2.metric("Margin", f"{df['margin'].sum() / df['revenue'].sum():.1%}")
        k3.metric("Refunds", f"${df['refund_amount'].sum():,.0f}")
        k4.metric("Overdue invoices", f"${overdue_amount:,.0f}")
        k5.metric("Active alerts", f"{len(alerts)}")

    with section("Most serious alerts"):
        show_flagged(alerts, "alerts in total", "No alerts with the current settings.")

    with section("Revenue and margin"):
        by_q = df.groupby("quarter").agg(revenue=("revenue", "sum"), margin=("margin", "sum")).reset_index()
        by_q["margin_pct"] = by_q["margin"] / by_q["revenue"]
        left, right = st.columns(2)
        fig = px.bar(by_q, x="quarter", y="revenue", title="Revenue by quarter",
                     labels={"quarter": "", "revenue": "Revenue ($)"}, color_discrete_sequence=[OAK])
        fig.update_layout(yaxis_tickformat="$,.0f")
        show(fig, left)
        fig = px.line(by_q, x="quarter", y="margin_pct", markers=True, title="Margin % by quarter",
                      labels={"quarter": "", "margin_pct": "Margin %"}, color_discrete_sequence=[OAK])
        fig.update_layout(yaxis_tickformat=".0%", yaxis_rangemode="tozero")
        show(fig, right)

    with section("Table: alerts by detection"):
        if len(alerts):
            counts = alerts.groupby(["detection", "level"]).size().unstack(fill_value=0)
            st.dataframe(counts[[c for c in LEVEL_ORDER if c in counts.columns]], use_container_width=True)

# ---- D8 Sales reps ----------------------------------------------------------
with tab_reps:
    reps = rep_table(df)
    reps["status"] = ["Above threshold" if d > rep_discount_threshold else "Within threshold"
                      for d in reps["avg_discount"]]
    flagged_reps = reps.loc[reps["status"] == "Above threshold", "sales_rep"].tolist()
    status_colors = {"Above threshold": LEVEL_COLORS["Critical"], "Within threshold": GREY}
    d8 = alerts[alerts["detection"] == "Rep Discount Watch"]
    rest = df[~df["sales_rep"].isin(flagged_reps)]

    with section("D8. Rep Discount Watch"):
        show_flagged(d8, f"sales reps above a {rep_discount_threshold:.0%} average discount (amount = margin given up)",
                     f"No sales rep gives an average discount above {rep_discount_threshold:.0%}.")
        company_margin = df["margin"].sum() / df["revenue"].sum()
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Company margin", f"{company_margin:.1%}")
        if flagged_reps:
            rest_margin = rest["margin"].sum() / rest["revenue"].sum()
            m2.metric(f"Without {', '.join(flagged_reps)}", f"{rest_margin:.1%}",
                      delta=f"{(rest_margin - company_margin) * 100:+.1f} points")
            m3.metric("Margin given up", f"${d8['amount'].sum():,.0f}")
        m4.metric("Loss-making orders", int(reps["loss_orders"].sum()),
                  f"${reps['loss_amount'].sum():,.0f} lost", delta_color="off")
        m5.metric("Overstock returns", int(reps["overstock_returns"].sum()),
                  f"${reps['overstock_refunds'].sum():,.0f} refunded", delta_color="off")

    with section("Charts"):
        c1, c2, c3 = st.columns(3)
        fig = px.bar(reps.sort_values("revenue"), x="revenue", y="sales_rep", orientation="h",
                     color="status", color_discrete_map=status_colors,
                     hover_data={"region": True, "customers": True, "orders": True},
                     title="Revenue by rep", labels={"revenue": "Revenue ($)", "sales_rep": "", "status": ""})
        fig.update_layout(xaxis_tickformat="$,.0f", yaxis={"categoryorder": "total ascending"})
        show(fig, c1, SMALL_CHART)

        fig = px.bar(reps.sort_values("avg_discount"), x="avg_discount", y="sales_rep", orientation="h",
                     color="status", color_discrete_map=status_colors, text_auto=".0%",
                     hover_data={"region": True, "revenue": ":,.0f", "orders": True},
                     title="Average discount by rep",
                     labels={"avg_discount": "Average discount", "sales_rep": "", "status": ""})
        fig.add_vline(x=rep_discount_threshold, line_dash="dash")
        fig.update_layout(xaxis_tickformat=".0%", yaxis={"categoryorder": "total ascending"})
        show(fig, c2, SMALL_CHART)

        fig = px.bar(reps.sort_values("margin_pct", ascending=False), x="margin_pct", y="sales_rep",
                     orientation="h", color="status", color_discrete_map=status_colors, text_auto=".0%",
                     hover_data={"region": True, "margin": ":,.0f", "loss_orders": True},
                     title="Margin % by rep", labels={"margin_pct": "Margin %", "sales_rep": "", "status": ""})
        fig.update_layout(xaxis_tickformat=".0%", yaxis={"categoryorder": "total descending"})
        show(fig, c3, SMALL_CHART)

        c4, c5 = st.columns(2)
        if flagged_reps:
            all_q = df.groupby("quarter").agg(revenue=("revenue", "sum"), margin=("margin", "sum"))
            rest_q = rest.groupby("quarter").agg(revenue=("revenue", "sum"), margin=("margin", "sum"))
            trend = pd.concat([
                (all_q["margin"] / all_q["revenue"]).rename("margin_pct").reset_index().assign(group="All reps"),
                (rest_q["margin"] / rest_q["revenue"]).rename("margin_pct").reset_index()
                .assign(group=f"Without {', '.join(flagged_reps)}"),
            ])
            fig = px.line(trend, x="quarter", y="margin_pct", color="group", markers=True,
                          color_discrete_sequence=[OAK, STEEL],
                          title="Company margin %, with and without the flagged reps",
                          labels={"quarter": "", "margin_pct": "Margin %", "group": ""})
            fig.update_layout(yaxis_tickformat=".0%", yaxis_rangemode="tozero")
            show(fig, c4, SMALL_CHART)

        problems = pd.concat([
            reps.assign(kind="Orders sold at a loss", count=reps["loss_orders"], dollars=reps["loss_amount"]),
            reps.assign(kind="Overstock / ordered in error returns", count=reps["overstock_returns"],
                        dollars=reps["overstock_refunds"]),
        ])[["sales_rep", "region", "kind", "count", "dollars"]]
        fig = px.bar(problems, x="sales_rep", y="count", color="kind", barmode="group", text="count",
                     color_discrete_sequence=[OAK, STEEL], hover_data={"region": True, "dollars": ":,.0f"},
                     category_orders={"sales_rep": sorted(reps["sales_rep"])},
                     title="Loss-making orders and overstock returns by rep",
                     labels={"sales_rep": "", "count": "Orders", "kind": "", "dollars": "Amount ($)"})
        show(fig, c5, SMALL_CHART)

    with section("Table: all sales reps"):
        table = reps[["sales_rep", "region", "customers", "orders", "revenue", "avg_discount", "margin_pct",
                      "loss_orders", "quarter_end_share", "overstock_refunds", "status"]].copy()
        for col in ["avg_discount", "margin_pct", "quarter_end_share"]:
            table[col] = (table[col] * 100).round(1)
        table[["revenue", "overstock_refunds"]] = table[["revenue", "overstock_refunds"]].round(0)
        table = table.rename(columns={
            "sales_rep": "rep", "avg_discount": "avg discount %", "margin_pct": "margin %",
            "loss_orders": "orders sold at a loss", "quarter_end_share": "% revenue in last week of quarter",
            "overstock_refunds": "overstock refunds $"})
        st.dataframe(table.sort_values("avg discount %", ascending=False), use_container_width=True, hide_index=True)

# ---- D1 Transit damage ------------------------------------------------------
with tab_damage:
    t = damage_table(df, min_orders)
    d1 = alerts[alerts["detection"] == "Transit Damage Watch"]

    with section("D1. Transit Damage Watch"):
        show_flagged(d1, f"product and region pairs above {damage_threshold:.0%} damage (amount = refunds)",
                     f"No product and region is above the {damage_threshold:.0%} damage threshold.", limit=4)
        cost = (t.groupby("product").agg(refunds=("refunds", "sum"), damaged=("damaged", "sum"))
                .sort_values("refunds", ascending=False))
        cost = cost[cost["refunds"] > 0]
        cards = st.columns(4)
        cards[0].metric("Damage refunds, all products", f"${cost['refunds'].sum():,.0f}",
                        f"{int(cost['damaged'].sum())} damaged orders", delta_color="off")
        for card, (name, row) in zip(cards[1:], cost.head(3).iterrows()):
            card.metric(name, f"${row['refunds']:,.0f}",
                        f"{int(row['damaged'])} orders, {row['refunds'] / cost['refunds'].sum():.0%} of total",
                        delta_color="off")

    with section("Charts"):
        c1, c2, c3 = st.columns(3)
        products = sorted(t["product"].unique())
        product = c2.selectbox("Product", products, index=products.index("ErgoLift Standing Desk")
                               if "ErgoLift Standing Desk" in products else 0)
        quiet_days = c3.slider("Days without an order = stopped ordering",
                               min_value=30, max_value=180, value=90, step=15)

        grid = t.pivot(index="product", columns="region", values="damage_rate")
        fig = px.imshow(grid, text_auto=".0%", aspect="auto", zmin=0, zmax=max(0.30, damage_threshold),
                        color_continuous_scale=[[0, "#f7efe4"], [1, "#5c3310"]],
                        title="Damage rate by product and region",
                        labels={"x": "", "y": "", "color": "Damage rate"})
        fig.update_layout(coloraxis_showscale=False)
        show(fig, c1, CHART + WIDGET_ROW)

        one = t[t["product"] == product].sort_values("damage_rate")
        fig = px.bar(one, x="damage_rate", y="region", orientation="h", text_auto=".0%",
                     hover_data={"orders": True, "damaged": True, "refunds": ":,.0f"},
                     title=f"{product}: damage rate by region",
                     labels={"damage_rate": "Orders damaged", "region": ""}, color_discrete_sequence=[OAK])
        fig.add_vline(x=damage_threshold, line_dash="dash", annotation_text="Alert")
        fig.update_layout(xaxis_tickformat=".0%")
        show(fig, c2)

        q = quiet_after_damage(df, as_of, quiet_days)
        link = q.groupby("group").agg(customers=("customer_id", "count"), stopped=("quiet", "sum"),
                                      share=("quiet", "mean")).reset_index()
        hit = q[q["damaged_deliveries"] > 0]
        lost = hit[hit["quiet"]]
        comparable = len(hit) > 0 and len(link) == 2
        if comparable:
            fig = px.bar(link, x="group", y="share", text_auto=".0%", color_discrete_sequence=[OAK],
                         hover_data={"customers": True, "stopped": True},
                         category_orders={"group": ["Had a damaged delivery", "No damaged delivery"]},
                         title="Customers who stopped ordering",
                         labels={"group": "", "share": "Stopped ordering"})
            fig.update_layout(yaxis_tickformat=".0%")
            show(fig, c3)
        else:
            c3.info("Not enough customers in this period to compare.")

    with section("Table: customers who stopped ordering after a damaged delivery"):
        if comparable:
            rates = link.set_index("group")["share"]
            s1, s2, s3 = st.columns(3)
            s1.metric("Stopped after a damaged delivery", f"{len(lost)} of {len(hit)} customers",
                      f"{rates['Had a damaged delivery']:.0%}", delta_color="off")
            s2.metric("Stopped, no damaged delivery", f"{rates['No damaged delivery']:.0%}")
            s3.metric("Revenue those customers had brought", f"${lost['revenue'].sum():,.0f}")
            shown_lost = lost[["customer_id", "segment", "region", "rep", "damaged_deliveries",
                               "last_damaged_order", "last_order", "days_quiet", "revenue"]].copy()
            for col in ["last_damaged_order", "last_order"]:
                shown_lost[col] = shown_lost[col].dt.date
            shown_lost["revenue"] = shown_lost["revenue"].round(0)
            st.dataframe(shown_lost.sort_values("revenue", ascending=False), use_container_width=True, hide_index=True)
            st.caption("Regular business customers only (5 or more orders in the period). "
                       "This shows a link, not proof that the damage caused it.")

    with section("Table: flagged routes"):
        st.dataframe(d1[["level", "subject", "detail", "amount"]], use_container_width=True, hide_index=True)

# ---- D3 Overdue invoices ---------------------------------------------------
with tab_invoices:
    d3 = alerts[alerts["detection"] == "Due Date Radar"]
    overdue = inv[inv["days_until_due"] < 0].copy()
    overdue["days_overdue"] = -overdue["days_until_due"]
    due_soon = inv[inv["days_until_due"].between(0, due_soon_days)]
    terms_colors = {"Net 30": OAK, "Net 60": STEEL}

    with section("D3. Due Date Radar: overdue invoices (Net 30 and Net 60)"):
        show_flagged(d3[d3["level"] != "Warning"], "overdue invoices", "No invoice is overdue.")
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Overdue amount", f"${overdue['revenue'].sum():,.0f}", f"{len(overdue)} invoices", delta_color="off")
        for box, terms in [(k2, "Net 30"), (k3, "Net 60")]:
            part = overdue[overdue["payment_terms"] == terms]
            box.metric(f"{terms} overdue", f"${part['revenue'].sum():,.0f}", f"{len(part)} invoices", delta_color="off")
        k4.metric(f"Due within {due_soon_days} days", f"${due_soon['revenue'].sum():,.0f}",
                  f"{len(due_soon)} invoices", delta_color="off")

    with section("Charts"):
        c1, c2, c3 = st.columns(3)
        names = ["Overdue 60+ days", "Overdue 31-60 days", "Overdue 1-30 days",
                 f"Due within {due_soon_days} days", "Not due yet"]
        inv["aging"] = pd.cut(inv["days_until_due"], [-10_000, -61, -31, -1, due_soon_days, 10_000],
                              labels=names).astype(str)
        aging = inv[inv["aging"] != "Not due yet"].groupby(["aging", "payment_terms"]).agg(
            amount=("revenue", "sum"), invoices=("order_id", "count")).reset_index()
        if len(aging):
            fig = px.bar(aging, x="aging", y="amount", color="payment_terms", barmode="group", text="invoices",
                         category_orders={"aging": names[3::-1], "payment_terms": ["Net 30", "Net 60"]},
                         color_discrete_map=terms_colors, title="How late? (labels = invoices)",
                         labels={"aging": "", "amount": "Amount owed ($)", "payment_terms": ""})
            fig.update_layout(yaxis_tickformat="$,.0f")
            show(fig, c1)

        by_customer = overdue.groupby("customer_id").agg(
            amount=("revenue", "sum"), invoices=("order_id", "count"),
            oldest=("days_overdue", "max"), payment_terms=("payment_terms", "first"),
            segment=("segment", "first"), rep=("account_rep", "first")).reset_index()
        if len(by_customer):
            top = by_customer.sort_values("amount", ascending=False).head(10)
            fig = px.bar(top.sort_values("amount"), x="amount", y="customer_id", orientation="h",
                         color="payment_terms", color_discrete_map=terms_colors,
                         category_orders={"payment_terms": ["Net 30", "Net 60"]},
                         hover_data={"invoices": True, "oldest": True, "segment": True, "rep": True},
                         title="Top 10 customers by overdue amount",
                         labels={"amount": "Overdue ($)", "customer_id": "", "payment_terms": ""})
            fig.update_layout(xaxis_tickformat="$,.0f", yaxis_type="category")
            show(fig, c2)

        c = credit_table(inv)
        if len(c):
            buckets = ["Under 25%", "25-50%", "50-75%", "75-90%", "90-100%", "Over limit"]
            c["bucket"] = pd.cut(c["used"], [0, 0.25, 0.5, 0.75, 0.9, 1, float("inf")], labels=buckets, right=False)
            c["zone"] = ["75% or more" if u >= 0.75 else "Below 75%" for u in c["used"]]
            by_bucket = c.groupby(["bucket", "zone"], observed=True).agg(customers=("customer_id", "count")).reset_index()
            by_bucket["bucket"] = by_bucket["bucket"].astype(str)
            near = int((c["used"] >= 0.75).sum())
            fig = px.bar(by_bucket, x="bucket", y="customers", color="zone", text="customers",
                         category_orders={"bucket": buckets, "zone": ["Below 75%", "75% or more"]},
                         color_discrete_map={"Below 75%": GREY, "75% or more": LEVEL_COLORS["Critical"]},
                         title=f"Credit limit used: {near} of {len(c)} customers at 75%+",
                         labels={"bucket": "Share of credit limit used", "customers": "Customers", "zone": ""})
            show(fig, c3)

    with section("Table: overdue invoices"):
        terms_choice = st.radio("Terms", ["All", "Net 30", "Net 60"], horizontal=True)
        listed = overdue if terms_choice == "All" else overdue[overdue["payment_terms"] == terms_choice]
        listed = listed[["order_id", "customer_id", "segment", "payment_terms", "account_rep",
                         "due_date", "days_overdue", "revenue"]].copy()
        listed["due_date"] = listed["due_date"].dt.date
        listed["revenue"] = listed["revenue"].round(0)
        st.dataframe(listed.rename(columns={"revenue": "amount owed $", "account_rep": "rep"})
                     .sort_values("days_overdue", ascending=False), use_container_width=True, hide_index=True)

    with section("A2. Payment Reminder Drafts"):
        st.write(f"{len(reminders)} reminders drafted automatically from the Due Date Radar alerts. "
                 "The button opens the draft in Outlook; the employee reviews it and clicks Send.")
        o1, o2, o3 = st.columns(3)
        mail_app = o1.radio("Open drafts in", ["Outlook desktop", "Outlook on the web"], horizontal=True)
        draft_levels = o2.multiselect("Show", LEVEL_ORDER, default=LEVEL_ORDER, key="draft_levels")
        per_page = 10
        drafts = reminders[reminders["level"].isin(draft_levels)].sort_values("amount", ascending=False)
        pages = max(1, -(-len(drafts) // per_page))
        page = o3.number_input(f"Page (of {pages})", min_value=1, max_value=pages, value=1)
        link_column = "outlook_desktop" if mail_app == "Outlook desktop" else "outlook_web"
        for r in drafts.iloc[(page - 1) * per_page: page * per_page].itertuples():
            info, button = st.columns([5, 1])
            info.markdown(f"**{r.invoice}** to {r.to} ({r.email}) - {r.level} - ${r.amount:,.0f}")
            info.caption(r.message.replace("\n", " "))
            button.link_button("Send in Outlook", getattr(r, link_column), use_container_width=True)
        st.download_button("Download all reminders (CSV)",
                           reminders.drop(columns=["outlook_desktop", "outlook_web"]).to_csv(index=False),
                           "payment_reminders.csv", "text/csv")

# ---- Automations ------------------------------------------------------------
with tab_actions:
    with section("A1. Alert Log"):
        if newly_logged:
            st.success(f"{newly_logged} new alerts were logged automatically just now.")
        else:
            st.info("No new alerts since the last run. Change a threshold or the period to trigger some.")
        f1, f2, f3, f4 = st.columns([2, 2, 1, 1])
        level_filter = f1.multiselect("Level", LEVEL_ORDER, default=LEVEL_ORDER)
        full_history = f2.checkbox("Show the full history (every end date tried)", value=False)
        if f3.button("Clear the log"):
            st.session_state["log"] = log.iloc[0:0]
            Path(LOG_FILE).unlink(missing_ok=True)
            st.rerun()
        f4.download_button("Download (CSV)", log.to_csv(index=False), "alerts_log.csv", "text/csv")
        shown = log[log["level"].isin(level_filter)]
        if not full_history:
            shown = shown[shown["as_of"] == str(as_of.date())]

    active = [(i, n) for i, n, status, _ in DETECTIONS if status == "active"]

    # One chart per detection, side by side.
    with section("Charts: one per detection"):
        for col, (det_id, det_name) in zip(st.columns(len(active)), active):
            part = shown[shown["detection"] == det_name]
            latest = part.drop_duplicates("subject", keep="last")
            if latest.empty:
                col.caption(f"{det_id}. {det_name}: no alerts.")
                continue
            title = f"{det_id}. {det_name}: {len(latest)} alerts, ${latest['amount'].sum():,.0f}"
            if len(latest) <= 15:
                fig = px.bar(latest.sort_values("amount"), x="amount", y="subject", orientation="h",
                             color="level", color_discrete_map=LEVEL_COLORS,
                             category_orders={"level": LEVEL_ORDER}, hover_data={"detail": True},
                             title=title, labels={"amount": "Amount ($)", "subject": "", "level": ""})
                fig.update_layout(xaxis_tickformat="$,.0f", yaxis_type="category")
            else:
                by_level = latest.groupby("level").agg(amount=("amount", "sum"), alerts=("subject", "count")).reset_index()
                by_level["label"] = by_level["alerts"].astype(str) + " alerts"
                fig = px.bar(by_level, x="level", y="amount", color="level", text="label",
                             color_discrete_map=LEVEL_COLORS, category_orders={"level": LEVEL_ORDER},
                             title=title, labels={"amount": "Amount ($)", "level": ""})
                fig.update_layout(yaxis_tickformat="$,.0f", showlegend=False)
            show(fig, col, key=f"log_chart_{det_id}")

    # One table per detection.
    for det_id, det_name in active:
        part = shown[shown["detection"] == det_name]
        with section(f"Table: {det_id}. {det_name} ({len(part)} alerts)"):
            st.dataframe(part.drop(columns=["key", "detection"]).sort_values("amount", ascending=False),
                         use_container_width=True, hide_index=True)

# ---- Slots ------------------------------------------------------------------
with tab_slots:
    with section("Detections"):
        st.dataframe(pd.DataFrame(DETECTIONS, columns=["id", "name", "status", "what it checks"]),
                     use_container_width=True, hide_index=True)
    with section("Automations"):
        st.dataframe(pd.DataFrame(AUTOMATIONS, columns=["id", "name", "status", "what it does"]),
                     use_container_width=True, hide_index=True)
    st.caption("Status 'slot' = named and wired in, but the rule is not written yet. 'paused' = written but "
               "switched off. Fill in the matching function in app.py and change the status to 'active'.")
