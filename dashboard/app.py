import sys
import os
# Set working directory to project root regardless of where
# streamlit is launched from
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(PROJECT_ROOT)
sys.path.append(PROJECT_ROOT)

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime
from scripts.sheets.sheets_writer import get_sheet_client

# --- Page Config ---
st.set_page_config(
    page_title="Trading Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- Custom CSS ---
st.markdown("""
<style>
    .metric-card {
        background: #1e2130;
        border-radius: 10px;
        padding: 20px;
        margin: 5px;
    }
    .positive { color: #00c853; }
    .negative { color: #ff1744; }
    .neutral  { color: #ffffff; }
    .stMetric label { font-size: 0.85rem; color: #9e9e9e; }
    div[data-testid="stMetricValue"] { font-size: 1.8rem; }
    .signal-badge {
        padding: 3px 10px;
        border-radius: 12px;
        font-size: 0.78rem;
        font-weight: bold;
    }
</style>
""", unsafe_allow_html=True)


# --- Data Loading ---
@st.cache_data(ttl=300)   # refresh every 5 minutes
def load_sheet(tab_name):
    try:
        ws      = get_sheet_client(tab_name)
        records = ws.get_all_records()
        return pd.DataFrame(records)
    except Exception as e:
        st.error(f"Error loading {tab_name} sheet: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=300)
def load_stats_raw():
    try:
        ws   = get_sheet_client("Stats")
        return ws.get_all_values()
    except Exception as e:
        st.error(f"Error loading Stats sheet: {e}")
        return []


def load_all_data():
    signals = load_sheet("Signals")
    trades  = load_sheet("Trades")
    stats   = load_stats_raw()
    return signals, trades, stats


def parse_stats(stats_raw):
    """Parses the Stats sheet raw values into a dict."""
    result = {}
    for row in stats_raw:
        if len(row) >= 2 and row[0] and row[1]:
            result[row[0]] = row[1]
    return result


# --- Sidebar ---
def render_sidebar(stats_dict):
    st.sidebar.image(
        "https://upload.wikimedia.org/wikipedia/commons/"
        "thumb/8/8e/Nextdoor_logo.svg/1200px-Nextdoor_logo.svg.png",
        width=40
    )
    st.sidebar.title("Trading System")
    st.sidebar.markdown("---")

    # Capital info
    capital = stats_dict.get("Trading Capital (₹)", "—")
    risk    = stats_dict.get("Risk Amount per Trade", "—")
    st.sidebar.metric("Trading Capital", f"₹{capital}")
    st.sidebar.metric("Risk Per Trade",  f"₹{risk}")

    st.sidebar.markdown("---")

    # Universe refresh status
    status      = stats_dict.get("Status", "—")
    days_left   = stats_dict.get("Days Till Refresh", "—")
    next_refresh = stats_dict.get("Next Refresh Due", "—")

    st.sidebar.markdown("### 🌐 Universe Status")
    st.sidebar.markdown(f"**Status**: {status}")
    st.sidebar.markdown(f"**Days Till Refresh**: {days_left}")
    st.sidebar.markdown(f"**Next Due**: {next_refresh}")

    st.sidebar.markdown("---")
    st.sidebar.markdown(
        f"*Last updated: {datetime.now().strftime('%H:%M:%S')}*"
    )

    # Manual refresh button
    if st.sidebar.button("🔄 Refresh Data"):
        st.cache_data.clear()
        st.rerun()


# --- Performance Metrics Row ---
def render_metrics(trades_df, stats_dict):
    st.markdown("## 📊 Performance")

    closed = trades_df[trades_df["status"] == "CLOSED"] \
        if not trades_df.empty else pd.DataFrame()
    open_t = trades_df[trades_df["status"] == "OPEN"] \
        if not trades_df.empty else pd.DataFrame()

    total      = len(closed)
    wins       = len(closed[closed["r_multiple"].astype(float) > 0]) \
        if not closed.empty else 0
    losses     = total - wins
    win_rate   = round(wins / total * 100, 1) if total > 0 else 0
    avg_r      = round(closed["r_multiple"].astype(float).mean(), 2) \
        if not closed.empty else 0
    total_pnl  = round(closed["pnl_rupees"].astype(float).sum(), 2) \
        if not closed.empty else 0

    gross_win  = closed[closed["pnl_rupees"].astype(float) > 0][
        "pnl_rupees"].astype(float).sum() if not closed.empty else 0
    gross_loss = abs(closed[closed["pnl_rupees"].astype(float) < 0][
        "pnl_rupees"].astype(float).sum()) if not closed.empty else 0
    pf         = round(gross_win / gross_loss, 2) \
        if gross_loss > 0 else 0

    c1, c2, c3, c4, c5, c6 = st.columns(6)

    with c1:
        st.metric("Total Trades", total)
    with c2:
        st.metric("Win Rate",
                   f"{win_rate}%",
                   f"{wins}W / {losses}L")
    with c3:
        st.metric("Avg R", avg_r,
                   delta_color="normal" if avg_r >= 0 else "inverse")
    with c4:
        st.metric("Profit Factor", pf)
    with c5:
        st.metric("Total P&L",
                   f"₹{total_pnl:,.0f}",
                   delta_color="normal" if total_pnl >= 0 else "inverse")
    with c6:
        st.metric("Open Trades", len(open_t))


# --- Equity Curve ---
def render_equity_curve(trades_df):
    st.markdown("### 📈 Equity Curve")

    closed = trades_df[trades_df["status"] == "CLOSED"].copy() \
        if not trades_df.empty else pd.DataFrame()

    if closed.empty:
        st.info("No closed trades yet — equity curve will appear here.")
        return

    closed["pnl_rupees"] = closed["pnl_rupees"].astype(float)
    closed = closed.sort_values("exit_time")
    closed["cumulative_pnl"] = closed["pnl_rupees"].cumsum()

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=closed["exit_time"],
        y=closed["cumulative_pnl"],
        mode="lines+markers",
        line=dict(color="#00c853", width=2),
        fill="tozeroy",
        fillcolor="rgba(0, 200, 83, 0.1)",
        name="Cumulative P&L"
    ))
    fig.update_layout(
        template="plotly_dark",
        height=300,
        margin=dict(l=0, r=0, t=10, b=0),
        xaxis_title="Exit Date",
        yaxis_title="Cumulative P&L (₹)",
        showlegend=False
    )
    st.plotly_chart(fig, use_container_width=True)


# --- R Distribution ---
def render_r_distribution(trades_df):
    st.markdown("### 📊 R Distribution")

    closed = trades_df[trades_df["status"] == "CLOSED"].copy() \
        if not trades_df.empty else pd.DataFrame()

    if closed.empty:
        st.info("No closed trades yet.")
        return

    closed["r_multiple"] = closed["r_multiple"].astype(float)

    fig = px.histogram(
        closed,
        x="r_multiple",
        nbins=20,
        color_discrete_sequence=["#448aff"],
        template="plotly_dark"
    )
    fig.add_vline(x=0, line_color="red",    line_dash="dash")
    fig.add_vline(x=1.5, line_color="green", line_dash="dash",
                   annotation_text="TP (1.5R)")
    fig.update_layout(
        height=300,
        margin=dict(l=0, r=0, t=10, b=0),
        xaxis_title="R Multiple",
        yaxis_title="Count",
        showlegend=False
    )
    st.plotly_chart(fig, use_container_width=True)


# --- Sector Performance ---
def render_sector_performance(trades_df):
    st.markdown("### 🏭 Sector Performance")

    closed = trades_df[trades_df["status"] == "CLOSED"].copy() \
        if not trades_df.empty else pd.DataFrame()

    if closed.empty:
        st.info("No closed trades yet.")
        return

    closed["pnl_rupees"] = closed["pnl_rupees"].astype(float)
    sector_pnl = closed.groupby("sector")["pnl_rupees"].sum() \
                       .sort_values(ascending=True).reset_index()

    colors = [
        "#00c853" if x >= 0 else "#ff1744"
        for x in sector_pnl["pnl_rupees"]
    ]

    fig = go.Figure(go.Bar(
        x=sector_pnl["pnl_rupees"],
        y=sector_pnl["sector"],
        orientation="h",
        marker_color=colors
    ))
    fig.update_layout(
        template="plotly_dark",
        height=max(200, len(sector_pnl) * 30),
        margin=dict(l=0, r=0, t=10, b=0),
        xaxis_title="Total P&L (₹)",
        showlegend=False
    )
    st.plotly_chart(fig, use_container_width=True)


# --- Open Trades Table ---
def render_open_trades(trades_df):
    st.markdown("## 📂 Open Trades")

    open_t = trades_df[trades_df["status"] == "OPEN"].copy() \
        if not trades_df.empty else pd.DataFrame()
    pending = trades_df[trades_df["status"] == "PENDING"].copy() \
        if not trades_df.empty else pd.DataFrame()

    if open_t.empty and pending.empty:
        st.info("No open or pending trades.")
        return

    if not open_t.empty:
        st.markdown("**Confirmed Open:**")
        display_cols = [
            "symbol", "sector", "entry_time",
            "entry_price", "actual_entry_price",
            "sl", "tp", "quantity",
            "ema_exit_alert"
        ]
        cols = [c for c in display_cols if c in open_t.columns]
        st.dataframe(
            open_t[cols].reset_index(drop=True),
            use_container_width=True,
            hide_index=True
        )

    if not pending.empty:
        st.markdown("**Pending Confirmation (place CNC SL-M order):**")
        display_cols = [
            "symbol", "sector", "entry_time",
            "entry_price", "sl", "tp", "quantity"
        ]
        cols = [c for c in display_cols if c in pending.columns]
        st.dataframe(
            pending[cols].reset_index(drop=True),
            use_container_width=True,
            hide_index=True
        )


# --- Signals Table ---
def render_signals(signals_df):
    st.markdown("## 📋 Recent Signals")

    if signals_df.empty:
        st.info("No signals yet.")
        return

    # Filter controls
    col1, col2 = st.columns(2)
    with col1:
        event_filter = st.multiselect(
            "Event Type",
            options=signals_df["event_type"].unique().tolist(),
            default=signals_df["event_type"].unique().tolist()
        )
    with col2:
        symbol_filter = st.text_input("Filter by Symbol", "")

    filtered = signals_df[
        signals_df["event_type"].isin(event_filter)
    ]
    if symbol_filter:
        filtered = filtered[
            filtered["symbol"].str.contains(
                symbol_filter.upper(), na=False
            )
        ]

    display_cols = [
        "timestamp", "event_type", "symbol", "sector",
        "entry", "sl", "tp", "quantity", "rsi5",
        "support_zone_price", "notes"
    ]
    cols = [c for c in display_cols if c in filtered.columns]

    st.dataframe(
        filtered[cols].sort_values(
            "timestamp", ascending=False
        ).reset_index(drop=True),
        use_container_width=True,
        hide_index=True,
        height=400
    )


# --- Trade History Table ---
def render_trade_history(trades_df):
    st.markdown("## 📜 Trade History")

    closed = trades_df[trades_df["status"] == "CLOSED"].copy() \
        if not trades_df.empty else pd.DataFrame()

    if closed.empty:
        st.info("No closed trades yet.")
        return

    closed["pnl_rupees"]  = closed["pnl_rupees"].astype(float)
    closed["r_multiple"]  = closed["r_multiple"].astype(float)

    def color_pnl(val):
        try:
            v = float(val)
            color = "#00c853" if v > 0 else "#ff1744"
            return f"color: {color}"
        except Exception:
            return ""

    display_cols = [
        "symbol", "sector", "entry_time", "entry_price",
        "actual_entry_price", "sl", "tp", "quantity",
        "exit_time", "exit_price", "exit_reason",
        "pnl_rupees", "r_multiple", "holding_period"
    ]
    cols = [c for c in display_cols if c in closed.columns]

    styled = closed[cols].sort_values(
        "exit_time", ascending=False
    ).reset_index(drop=True).style.map(
        color_pnl, subset=["pnl_rupees", "r_multiple"]
    )
    st.dataframe(styled, use_container_width=True,
                  hide_index=True, height=400)


# --- Main App ---
def main():
    signals_df, trades_df, stats_raw = load_all_data()
    stats_dict = parse_stats(stats_raw)

    render_sidebar(stats_dict)

    st.title("📈 Nifty 500 Trading Dashboard")
    st.markdown("---")

    # Row 1: Performance metrics
    render_metrics(trades_df, stats_dict)
    st.markdown("---")

    # Row 2: Charts
    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        render_equity_curve(trades_df)
    with col2:
        render_r_distribution(trades_df)
    with col3:
        render_sector_performance(trades_df)

    st.markdown("---")

    # Row 3: Open trades
    render_open_trades(trades_df)
    st.markdown("---")

    # Row 4: Tabs for signals and history
    tab1, tab2 = st.tabs(["📋 Signals", "📜 Trade History"])
    with tab1:
        render_signals(signals_df)
    with tab2:
        render_trade_history(trades_df)


if __name__ == "__main__":
    main()