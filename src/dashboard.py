"""
Warehouse Outboard Reporting — web dashboard.

Run (click-to-run launcher: "Start Dashboard.command"):
    streamlit run src/dashboard.py

Surfaces the consolidated carton dataset (PRD section 10) as:
  * KPIs + a "Refresh now" button (re-runs the whole pipeline)
  * Master charts (10.3): total cartons by Client; by Client x month
  * Living pivot (10.1): cartons by Client x month, plus the CALENDAR PIVOT —
    rows = Client > end customer, columns = month > date > day-of-week
    (NOTE: "Client" is the user-facing name for the rnd_customer column.)
    (mirrors the manual Excel "Calendar Pivot" tabs)
  * Per-customer drill-down (10.2): by month, by month broken down by retailer,
    and a month x day-of-week heatmap
  * Ask (10.4): natural-language Q&A (Claude over the dataset)
  * Data-quality tab (flagged rows, month corrections)
"""
from __future__ import annotations

import os
import sys

import altair as alt
import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pipeline  # noqa: E402
import transform as T  # noqa: E402
import qa  # noqa: E402
import gmail_fetch  # noqa: E402

MONTH_ORDER = ["January", "February", "March", "April", "May", "June", "July",
               "August", "September", "October", "November", "December", "(blank)"]
DOW_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
             "Saturday", "Sunday", "(blank)"]

# User-facing label for the rnd_customer column. The data/SQL keep the
# `rnd_customer` name; everything the user SEES says "Client".
CLIENT_LABEL = "Client"
# Friendly column names for any raw table we display to the user.
DISPLAY_RENAME = {
    "rnd_customer": "Client",
    "end_customer": "End customer",
    "driving_date": "Date",
    "day_of_week": "Day of week",
    "review_flag": "Review flag",
}

st.set_page_config(page_title="Warehouse Carton Reporting", layout="wide")


def _check_share_password() -> None:
    """Optional access gate for a shared/public link. Active only when the
    SHARE_PASSWORD env var is set — local use (no env var) is never gated."""
    pw = os.environ.get("SHARE_PASSWORD")
    if not pw or st.session_state.get("_authed"):
        return
    st.title("📦 Warehouse Carton Reporting")
    st.caption("This dashboard is shared for review. Please enter the access password.")
    entered = st.text_input("Access password", type="password")
    if entered and entered == pw:
        st.session_state["_authed"] = True
        st.rerun()
    elif entered:
        st.error("Incorrect password.")
    st.stop()


_check_share_password()


def month_sort(values) -> list:
    present = [m for m in MONTH_ORDER if m in set(values)]
    return present


def fmt_pivot(p: pd.DataFrame, decimals: int = 0) -> pd.DataFrame:
    """Render a numeric pivot as display strings: blank for missing, thousands
    separators otherwise. (Streamlit's grid shows raw NaN as 'None', and the
    manual Excel pivots leave empty cells blank — so we format to strings.)"""
    fmt = f"{{:,.{decimals}f}}"
    return p.apply(lambda col: col.map(
        lambda v: "" if pd.isna(v) else fmt.format(v)))


@st.cache_data(show_spinner=False)
def get_data(_cache_key: str) -> pd.DataFrame:
    return pipeline.load_latest()


def _humanize_age(delta) -> str:
    secs = max(delta.total_seconds(), 0)
    if secs < 3600:
        return f"{int(secs // 60)}m ago"
    if secs < 86400:
        return f"{int(secs // 3600)}h ago"
    return f"{int(secs // 86400)}d ago"


def threshold_defaults() -> dict:
    g = T.load_config().get("globals", {}).get("thresholds", {}) or {}
    return {
        "Daily": int(g.get("daily_cartons", 12000)),
        "Weekly": int(g.get("weekly_cartons", 65000)),
        "Monthly": int(g.get("monthly_cartons", 320000)),
    }


def volume_breaches(data: pd.DataFrame, limits: dict | None = None) -> tuple[pd.DataFrame, dict]:
    """Return (detail_df, limits) of periods whose TOTAL cartons exceed the
    thresholds. `limits` overrides the config defaults (used by the sidebar
    controls). Aggregates over whatever `data` is passed (e.g. filtered view)."""
    limits = limits or threshold_defaults()
    d = data.dropna(subset=["driving_date"]).copy()
    if d.empty:
        return pd.DataFrame(), limits
    d["driving_date"] = pd.to_datetime(d["driving_date"])
    rows = []
    daily = d.groupby(d["driving_date"].dt.normalize())["cartons"].sum()
    for when, v in daily[daily > limits["Daily"]].sort_values(ascending=False).items():
        rows.append(["Daily", when.strftime("%a %b %-d, %Y"), v, limits["Daily"]])
    weekly = d.groupby(d["driving_date"].dt.to_period("W"))["cartons"].sum()
    for when, v in weekly[weekly > limits["Weekly"]].sort_values(ascending=False).items():
        rows.append(["Weekly", "week of " + when.start_time.strftime("%b %-d, %Y"),
                     v, limits["Weekly"]])
    monthly = d.groupby(d["driving_date"].dt.to_period("M"))["cartons"].sum()
    for when, v in monthly[monthly > limits["Monthly"]].sort_values(ascending=False).items():
        rows.append(["Monthly", when.strftime("%B %Y"), v, limits["Monthly"]])
    return pd.DataFrame(rows, columns=["Level", "Period", "Cartons", "Threshold"]), limits


def source_status_table() -> pd.DataFrame | None:
    """Per-source 'last updated' provenance written by the pipeline."""
    path = os.path.join(T.OUT_DIR, "source_status.json")
    if not os.path.exists(path):
        return None
    import json
    with open(path) as fh:
        status = json.load(fh)
    if not status:
        return None
    now = pd.Timestamp.now()
    rows = []
    for _src, s in status.items():
        ts = pd.to_datetime(s["last_updated"])
        age = now - ts
        stale = age > pd.Timedelta(days=2)
        rows.append({
            "Source": s.get("display", _src),
            "Last updated": ts.strftime("%b %-d, %-I:%M %p"),
            "Age": ("⚠️ " if stale else "") + _humanize_age(age),
            "From": s.get("origin", ""),
        })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# header + refresh
# --------------------------------------------------------------------------- #
st.title("📦 Warehouse — Carton Volume")

meta = pipeline.last_run_meta()
cache_key = meta["run_tag"] if meta else "none"

top = st.columns([4, 1])
with top[0]:
    if meta:
        st.caption(f"Last refreshed: **{meta['timestamp']}**  ·  "
                   f"{int(meta['rows']):,} rows  ·  {meta['sources']} sources  ·  "
                   f"{meta['rnd_customers']} clients")
    else:
        st.caption("No data yet — click **Refresh now** to pull the reports.")
with top[1]:
    if st.button("🔄 Refresh now", type="primary", use_container_width=True,
                 help="Pulls the latest Catalyst/MLG/Novo reports from Gmail (in "
                      "memory — nothing saved to your laptop) and reads "
                      "Americhine/RDG from your drop folder, then rebuilds."):
        with st.spinner("Pulling the latest reports from Gmail and rebuilding…"):
            try:
                res = gmail_fetch.fetch_and_run()
                get_data.clear()
                msg = (f"Refreshed: pulled {', '.join(res['fetched'])} from Gmail; "
                       f"{int(res['pipeline']['rows']):,} rows total.")
                if res["missing"]:
                    msg += f" (Not in Gmail today: {', '.join(res['missing'])}.)"
                st.success(msg)
                st.rerun()
            except gmail_fetch.GmailFetchError as e:
                st.error(f"{e}")
            except Exception as e:  # noqa: BLE001
                st.error(f"Refresh failed: {e}")

df = get_data(cache_key)
if df.empty:
    st.warning("No consolidated data found. Click **Refresh now** above.")
    st.stop()

df["cartons"] = pd.to_numeric(df["cartons"], errors="coerce").fillna(0.0)

# --------------------------------------------------------------------------- #
# sidebar filters (defined first so the banner below can respect them)
# --------------------------------------------------------------------------- #
st.sidebar.header("Filters")
_dates = pd.to_datetime(df["driving_date"], errors="coerce")

sources = st.sidebar.multiselect("Source", sorted(df["source"].unique()),
                                 default=sorted(df["source"].unique()))
customers = st.sidebar.multiselect(CLIENT_LABEL, sorted(df["rnd_customer"].unique()),
                                   default=sorted(df["rnd_customer"].unique()))
end_opts = sorted(df[df["rnd_customer"].isin(customers)]["end_customer"].unique())
end_customers = st.sidebar.multiselect("End customer (retailer)", end_opts,
                                       default=end_opts)
all_years = sorted(int(y) for y in _dates.dt.year.dropna().unique())
years = st.sidebar.multiselect("Year", all_years, default=all_years)
months = st.sidebar.multiselect("Month", month_sort(df["month"].unique()),
                                default=month_sort(df["month"].unique()))

# Build the filter mask. Year and Date range only NARROW when changed from their
# full defaults, so at defaults the no-date "(blank)" rows are not silently dropped.
mask = (df["source"].isin(sources) & df["rnd_customer"].isin(customers)
        & df["end_customer"].isin(end_customers) & df["month"].isin(months))
if set(years) != set(all_years):
    mask &= _dates.dt.year.isin(years)

if all_years:
    min_d, max_d = _dates.min().date(), _dates.max().date()
    dr = st.sidebar.date_input("Date range", value=(min_d, max_d),
                               min_value=min_d, max_value=max_d,
                               help="Narrow to specific dates, e.g. Jun 1–30, 2026. "
                                    "Rows with no date are excluded while a range is set.")
    if isinstance(dr, (tuple, list)) and len(dr) == 2 and (dr[0] != min_d or dr[1] != max_d):
        # dates are normalized to midnight, so inclusive between() covers the end day
        mask &= _dates.between(pd.Timestamp(dr[0]), pd.Timestamp(dr[1]))

f = df[mask].copy()

# --------------------------------------------------------------------------- #
# sidebar: adjustable volume thresholds (Armando can set his own numbers)
# --------------------------------------------------------------------------- #
st.sidebar.header("Critical volume thresholds")
st.sidebar.caption("Flag periods above these (uses the current filters).")
_dfl = threshold_defaults()
_limits = {
    "Daily": st.sidebar.number_input("Daily limit (cartons)", min_value=0,
                                     value=_dfl["Daily"], step=1000),
    "Weekly": st.sidebar.number_input("Weekly limit (cartons)", min_value=0,
                                      value=_dfl["Weekly"], step=1000),
    "Monthly": st.sidebar.number_input("Monthly limit (cartons)", min_value=0,
                                       value=_dfl["Monthly"], step=5000),
}

# --------------------------------------------------------------------------- #
# CRITICAL volume-threshold banner (top of dashboard) — respects filters + limits
# --------------------------------------------------------------------------- #
_breaches, _used = volume_breaches(f, _limits)
_scope = "selection" if len(f) < len(df) else "all sources"
if not _breaches.empty:
    counts = _breaches["Level"].value_counts()
    parts = []
    for lvl, lim in _used.items():
        n = int(counts.get(lvl, 0))
        if n:
            worst = _breaches[_breaches["Level"] == lvl].iloc[0]
            parts.append(f"- 🚨 **{n} {lvl.lower()} period(s)** over {lim:,} cartons — "
                         f"highest: **{worst['Period']} = {worst['Cartons']:,.0f}**")
    st.error(f"### 🚨 CRITICAL — carton volume thresholds exceeded ({_scope})\n"
             + "\n".join(parts))
    with st.expander("See all threshold breaches"):
        show = _breaches.copy()
        show["Cartons"] = show["Cartons"].map("{:,.0f}".format)
        show["Threshold"] = show["Threshold"].map("{:,.0f}".format)
        st.dataframe(show, use_container_width=True, hide_index=True)
else:
    st.success(f"✅ No volume-threshold breaches in the current {_scope}.")

# Per-source freshness — collapsed one-line summary; click the arrow for the table.
# (⚠️ = older than 2 days, e.g. a portal export you forgot to update.)
_status = source_status_table()
if _status is not None:
    _stale = int(_status["Age"].str.contains("⚠️").sum())
    _summary = (f"📋 Source freshness — ⚠️ {_stale} source(s) not updated in 2+ days"
                if _stale else "📋 Source freshness — all sources up to date")
    with st.expander(_summary, expanded=False):
        st.dataframe(_status, use_container_width=True, hide_index=True)

# --------------------------------------------------------------------------- #
# KPIs
# --------------------------------------------------------------------------- #
this_month = pd.Timestamp.today().strftime("%B")
month_total = f.loc[f["month"] == this_month, "cartons"].sum()
k = st.columns(2)
k[0].metric("Total cartons", f"{f['cartons'].sum():,.0f}")
k[1].metric("Total cartons this month", f"{month_total:,.0f}",
            help=f"Cartons with a driving date in {this_month} "
                 f"{pd.Timestamp.today():%Y} (the current calendar month).")

tab_master, tab_cust, tab_ask, tab_quality, tab_data = st.tabs(
    ["Master charts", "Per-customer", "Ask (Q&A)", "Data quality", "Raw data"])

# --------------------------------------------------------------------------- #
# master
# --------------------------------------------------------------------------- #
with tab_master:
    st.subheader("Cartons by Client × month")
    bcm = f.groupby(["rnd_customer", "month"], as_index=False)["cartons"].sum()
    bcm["cartons"] = bcm["cartons"].round(0)
    m_order = month_sort(bcm["month"].unique())
    month_totals = bcm.groupby("month", as_index=False)["cartons"].sum()
    bars = alt.Chart(bcm).mark_bar().encode(
        x=alt.X("month:N", sort=m_order, title=None),
        y=alt.Y("cartons:Q", title="Cartons", stack="zero"),
        color=alt.Color("rnd_customer:N", title=CLIENT_LABEL),
        tooltip=[alt.Tooltip("rnd_customer:N", title=CLIENT_LABEL), "month",
                 alt.Tooltip("cartons:Q", format=",.0f")],
    )
    # Total cartons label above each month's bar.
    totals_lbl = alt.Chart(month_totals).mark_text(
        dy=-6, fontWeight="bold", color="#333", baseline="bottom").encode(
        x=alt.X("month:N", sort=m_order),
        y=alt.Y("cartons:Q"),
        text=alt.Text("cartons:Q", format=",.0f"),
    )
    st.altair_chart((bars + totals_lbl).properties(height=400),
                    use_container_width=True)

    st.subheader("Total cartons by Client")
    by_cust = (f.groupby("rnd_customer", as_index=False)["cartons"].sum()
               .sort_values("cartons", ascending=False))
    by_cust["cartons"] = by_cust["cartons"].round(0)
    st.altair_chart(
        alt.Chart(by_cust).mark_bar().encode(
            x=alt.X("cartons:Q", title="Cartons"),
            y=alt.Y("rnd_customer:N", sort="-x", title=None),
            tooltip=[alt.Tooltip("rnd_customer:N", title=CLIENT_LABEL),
                     alt.Tooltip("cartons:Q", format=",.0f")],
        ).properties(height=320), use_container_width=True)

    st.subheader("Living pivot — cartons by Client × month")
    pivot = pd.pivot_table(f, index="rnd_customer", columns="month",
                           values="cartons", aggfunc="sum", margins=True,
                           margins_name="Total")
    ordered = [m for m in MONTH_ORDER if m in pivot.columns] + \
              (["Total"] if "Total" in pivot.columns else [])
    pivot = pivot[ordered]
    pivot.index.name = CLIENT_LABEL
    st.dataframe(fmt_pivot(pivot), use_container_width=True)

    st.subheader("Calendar pivot — Client › end customer × month › date › day")
    st.caption("Mirrors the manual Excel Calendar Pivot: each client with its "
               "end retailers underneath, one column per ship/start date. Scroll "
               "horizontally; use the sidebar filters to narrow it down.")
    cal_src = f.dropna(subset=["driving_date"]).copy()
    if cal_src.empty:
        st.caption("No dated rows in the current filter.")
    else:
        cal_src["driving_date"] = pd.to_datetime(cal_src["driving_date"])
        cal_src["date_label"] = (cal_src["driving_date"].dt.strftime("%m/%d/%y") + "\n"
                                 + cal_src["day_of_week"])
        calp = pd.pivot_table(cal_src, index=["rnd_customer", "end_customer"],
                              columns=["month", "date_label"],
                              values="cartons", aggfunc="sum")
        # order columns chronologically (month name alone would sort alphabetically)
        col_order = (cal_src[["month", "date_label", "driving_date"]]
                     .drop_duplicates(["month", "date_label"])
                     .sort_values("driving_date"))
        calp = calp.reindex(columns=pd.MultiIndex.from_frame(
            col_order[["month", "date_label"]]))
        calp["", "Grand Total"] = calp.sum(axis=1)
        total_row = calp.sum(axis=0).to_frame().T
        total_row.index = pd.MultiIndex.from_tuples([("Grand Total", "")])
        calp = pd.concat([calp, total_row])
        calp.index.names = [CLIENT_LABEL, "End customer"]
        st.dataframe(fmt_pivot(calp), use_container_width=True, height=420)

# --------------------------------------------------------------------------- #
# per-customer
# --------------------------------------------------------------------------- #
with tab_cust:
    cust = st.selectbox(CLIENT_LABEL, sorted(f["rnd_customer"].unique()))
    g = f[f["rnd_customer"] == cust]

    st.subheader(f"{cust} — cartons by month")
    bym = g.groupby("month", as_index=False)["cartons"].sum()
    bym["cartons"] = bym["cartons"].round(0)
    st.altair_chart(
        alt.Chart(bym).mark_bar().encode(
            x=alt.X("month:N", sort=month_sort(bym["month"].unique()), title=None),
            y=alt.Y("cartons:Q", title="Cartons"),
            tooltip=["month", alt.Tooltip("cartons:Q", format=",.0f")],
        ).properties(height=320), use_container_width=True)

    st.subheader(f"{cust} — cartons by month, broken down by end customer")
    bce = g.groupby(["month", "end_customer"], as_index=False)["cartons"].sum()
    bce["cartons"] = bce["cartons"].round(0)
    st.altair_chart(
        alt.Chart(bce).mark_bar().encode(
            x=alt.X("month:N", sort=month_sort(bce["month"].unique()), title=None),
            y=alt.Y("cartons:Q", title="Cartons", stack="zero"),
            color=alt.Color("end_customer:N", title="End customer"),
            tooltip=["end_customer", "month", alt.Tooltip("cartons:Q", format=",.0f")],
        ).properties(height=360), use_container_width=True)

    st.subheader(f"{cust} — calendar: month × day of week")
    cal = g.groupby(["month", "day_of_week"], as_index=False)["cartons"].sum()
    cal["cartons"] = cal["cartons"].round(0)
    st.altair_chart(
        alt.Chart(cal).mark_rect().encode(
            x=alt.X("month:N", sort=month_sort(cal["month"].unique()), title=None),
            y=alt.Y("day_of_week:N", sort=DOW_ORDER, title=None),
            color=alt.Color("cartons:Q", title="Cartons", scale=alt.Scale(scheme="blues")),
            tooltip=["month", "day_of_week", alt.Tooltip("cartons:Q", format=",.0f")],
        ).properties(height=300), use_container_width=True)

    st.subheader(f"{cust} — by end customer × month")
    ec = pd.pivot_table(g, index="end_customer", columns="month",
                        values="cartons", aggfunc="sum")
    ec = ec[[m for m in MONTH_ORDER if m in ec.columns]]
    st.dataframe(fmt_pivot(ec), use_container_width=True)

# --------------------------------------------------------------------------- #
# ask (natural-language Q&A)
# --------------------------------------------------------------------------- #
with tab_ask:
    st.subheader("Ask a question about the data")
    st.caption("Plain English, e.g. “How many cartons is RDG sending in August "
               "by week?” or “Which customer has the most cartons in June?”")

    has_key = bool(os.environ.get("ANTHROPIC_API_KEY")
                   or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
    if not has_key:
        st.info("Q&A needs an Anthropic API key. Put it in `config/secrets.env` "
                "(one line: `export ANTHROPIC_API_KEY=sk-ant-...`) and relaunch via "
                "**Start Dashboard.command** — the launcher loads it automatically.")
    else:
        q = st.text_input("Your question", key="qa_q",
                          placeholder="How many cartons is RDG sending in August by week?")
        if st.button("Ask", type="primary") and q.strip():
            with st.spinner("Thinking…"):
                try:
                    # Q&A runs over the full dataset, not the sidebar filter.
                    res = qa.answer_question(q.strip(), df)
                except qa.QAError as e:
                    st.error(str(e))
                    res = None
                except Exception as e:  # API/network errors
                    st.error(f"Q&A failed: {e}")
                    res = None
            if res:
                st.markdown(res["answer"])
                rdf = res.get("result_df")
                if rdf is not None and len(rdf):
                    # Auto-chart when the result is a label + single numeric column.
                    num = rdf.select_dtypes("number").columns.tolist()
                    cats = [c for c in rdf.columns if c not in num]
                    if len(rdf) > 1 and len(num) == 1 and len(cats) >= 1:
                        st.altair_chart(
                            alt.Chart(rdf).mark_bar().encode(
                                x=alt.X(f"{cats[0]}:N", sort=None, title=None),
                                y=alt.Y(f"{num[0]}:Q"),
                                tooltip=list(rdf.columns),
                            ).properties(height=320), use_container_width=True)
                    st.dataframe(rdf.rename(columns=DISPLAY_RENAME),
                                 use_container_width=True)
                if res.get("sql"):
                    with st.expander("SQL used"):
                        st.code(res["sql"], language="sql")


# --------------------------------------------------------------------------- #
# data quality
# --------------------------------------------------------------------------- #
with tab_quality:
    st.subheader("Rows flagged for spot-check")
    st.caption("Computed values are kept as-is (no rounding floor). "
               "`sub1_carton` = line computes to less than one carton; "
               "`missing_carton` = the source cell was blank/non-numeric and "
               "counts as 0.")
    flagged = f[f["review_flag"] != ""][
        ["source", "rnd_customer", "end_customer", "driving_date",
         "month", "day_of_week", "units", "cartons", "review_flag"]]
    st.dataframe(flagged.rename(columns=DISPLAY_RENAME),
                 use_container_width=True, height=280)

    mc = os.path.join(T.LOG_DIR, "month_corrections.csv")
    st.subheader("Month corrections (computed vs source-typed)")
    if os.path.exists(mc):
        st.dataframe(pd.read_csv(mc), use_container_width=True, height=200)
    else:
        st.caption("None — raw feeds carry no typed month, so nothing to correct.")

# --------------------------------------------------------------------------- #
# raw data
# --------------------------------------------------------------------------- #
with tab_data:
    st.dataframe(f.rename(columns=DISPLAY_RENAME), use_container_width=True, height=460)
    st.download_button("Download filtered CSV", f.to_csv(index=False),
                       "carton_data.csv", "text/csv")
