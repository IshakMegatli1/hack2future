import importlib

pd = importlib.import_module("pandas")
px = importlib.import_module("plotly.express")

st = importlib.import_module("streamlit")

st.set_page_config(page_title="Sales Insights", layout="wide")


@st.cache_data
def load():
    return pd.read_csv("cleaned_data.csv", parse_dates=["date"])


df = load()

st.title("Do rain and holidays change our sales in Toronto?")
st.caption("Business question: how much revenue do we lose on rainy days, and what should we do about it?")

# Sidebar filters
st.sidebar.header("Filters")
date_range = st.sidebar.date_input(
    "Date range", [df["date"].min().date(), df["date"].max().date()]
)
if len(date_range) == 2:
    d1, d2 = date_range
    f = df[(df["date"] >= pd.to_datetime(d1)) & (df["date"] <= pd.to_datetime(d2))]
else:
    f = df

# KPI cards
rain_avg = f[f["rainy"]]["sales"].mean()
dry_avg = f[~f["rainy"]]["sales"].mean()
drop = dry_avg - rain_avg
c1, c2, c3 = st.columns(3)
c1.metric("Total sales", f"${f['sales'].sum():,.0f}")
c2.metric("Avg sales on dry days", f"${dry_avg:,.0f}")
c3.metric("Loss per rainy day", f"${drop:,.0f}")

# Charts
left, right = st.columns(2)
left.plotly_chart(
    px.box(f, x="rainy", y="sales",
           title=f"Rainy days cut average sales by about ${drop:,.0f}"),
    use_container_width=True,
)
right.plotly_chart(
    px.scatter(f, x="precip_mm", y="sales", trendline="ols",
               title="More rain, lower sales"),
    use_container_width=True,
)

monthly = (
    f.groupby(f["date"].dt.to_period("M").astype(str))["sales"].sum().reset_index()
)
st.plotly_chart(
    px.line(monthly, x="date", y="sales", title="Monthly sales"),
    use_container_width=True,
)

# What-if tool
st.subheader("What if we act on rainy days?")
recover = st.slider("Share of the rainy-day loss we could recover (%)", 0, 100, 30)
rainy_days = int(f["rainy"].sum())
st.success(
    f"Recovering {recover}% of the loss on {rainy_days} rainy days is worth about "
    f"${drop * rainy_days * recover / 100:,.0f}."
)

# Findings from the notebook
with st.expander("Report findings"):
    try:
        st.markdown(open("report.md").read())
    except FileNotFoundError:
        st.write("report.md not found.")
