import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
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
    page_title="Nifty 500 Trading Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- Custom CSS ---
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }
    .stMetric label {
        font-size: 0.78rem;
        color: #9e9e9e;
        font-weight: 500;
        letter-spacing: 0.05em;
        text-transform: uppercase;
    }
    div[data-testid="stMetricValue"] {
        font-size: 1.7rem;
        font-weight: 600;
    }
    div[data-testid="stMetricDelta"] {
        font-size: 0.82rem;
    }
    h1 {
        font-weight: 700;
        letter-spacing: -0.5px;
    }
    h2, h3 {
        font-weight: 600;
        letter-spacing: -0.3px;
    }
    .section-header {
        font-size: 0.72rem;
        font-weight: 600;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: #9e9e9e;
        margin-bottom: 0.5rem;
    }
    div[data-testid="stDataFrame"] {
        border-radius: 8px;
    }
</style>
""", unsafe_allow_html=True)


# --- Data Loading ---
@st.cache_data(ttl=300)
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
        ws = get_sheet_client("Stats")
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
    result = {}
    for row in stats_raw:
        if len(row) >= 2 and row[0] and row[1]:
            result[row[0]] = row[1]
    return result


# --- Sidebar ---
def render_sidebar(stats_dict):
    st.sidebar.markdown("## 📈 Trading System")
    st.sidebar.markdown("---")

    capital = stats_dict.get("Trading Capital (₹)", "—")
    risk    = stats_dict.get("Risk Amount per Trade", "—")
    st.sidebar.metric("Trading Capital", f"₹{capital}")
    st.sidebar.metric("Risk Per Trade",  f"₹{risk}")

    st.sidebar.markdown("---")

    status       = stats_dict.get("Status", "—")
    days_left    = stats_dict.get("Days Till Refresh", "—")
    next_refresh = stats_dict.get("Next Refresh Due", "—")

    st.sidebar.markdown("### 🌐 Universe Status")
    st.sidebar.markdown(f"**Status**: {status}")
    st.sidebar.markdown(f"**Days Till Refresh**: {days_left}")
    st.sidebar.markdown(f"**Next Due**: {next_refresh}")

    st.sidebar.markdown("---")
    st.sidebar.caption(
        f"Last updated: {datetime.now().strftime('%H:%M:%S')}"
    )

    if st.sidebar.button("🔄 Refresh Data"):
        st.cache_data.clear()
        st.rerun()


# --- Performance Metrics ---
def render_metrics(trades_df):
    st.markdown("## 📊 Performance")

    closed = trades_df[trades_df["status"] == "CLOSED"].copy() \
        if not trades_df.empty else pd.DataFrame()
    open_t = trades_df[trades_df["status"] == "OPEN"].copy() \
        if not trades_df.empty else pd.DataFrame()
    pending = trades_df[trades_df["status"] == "PENDING"].copy() \
        if not trades_df.empty else pd.DataFrame()

    total     = len(closed)
    wins      = len(closed[closed["r_multiple"].astype(float) > 0]) \
        if not closed.empty else 0
    losses    = total - wins
    win_rate  = round(wins / total * 100, 1) if total > 0 else 0
    avg_r     = round(closed["r_multiple"].astype(float).mean(), 2) \
        if not closed.empty else 0
    total_pnl = round(closed["pnl_rupees"].astype(float).sum(), 2) \
        if not closed.empty else 0

    gross_win  = closed[closed["pnl_rupees"].astype(float) > 0][
        "pnl_rupees"].astype(float).sum() \
        if not closed.empty else 0
    gross_loss = abs(closed[closed["pnl_rupees"].astype(float) < 0][
        "pnl_rupees"].astype(float).sum()) \
        if not closed.empty else 0
    pf = round(gross_win / gross_loss, 2) if gross_loss > 0 else 0

    c1, c2, c3, c4, c5, c6, c7 = st.columns(7)
    with c1:
        st.metric("Total Trades", total)
    with c2:
        st.metric("Win Rate", f"{win_rate}%", f"{wins}W / {losses}L")
    with c3:
        st.metric("Avg R", avg_r)
    with c4:
        st.metric("Profit Factor", pf)
    with c5:
        st.metric("Total P&L", f"₹{total_pnl:,.0f}")
    with c6:
        st.metric("Open Trades", len(open_t))
    with c7:
        st.metric("Pending", len(pending))


# --- Equity Curve (Drilldown Expander) ---
def render_equity_curve(trades_df):
    with st.expander("📈 Equity Curve", expanded=True):
        closed = trades_df[trades_df["status"] == "CLOSED"].copy() \
            if not trades_df.empty else pd.DataFrame()

        if closed.empty:
            st.info("No closed trades yet — equity curve will "
                    "appear here once trades are completed.")
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
            name="Cumulative P&L",
            hovertemplate="<b>%{x}</b><br>P&L: ₹%{y:,.0f}<extra></extra>"
        ))
        fig.update_layout(
            template="plotly_dark",
            height=320,
            margin=dict(l=0, r=0, t=10, b=0),
            xaxis_title="Exit Date",
            yaxis_title="Cumulative P&L (₹)",
            showlegend=False,
            font=dict(family="Inter")
        )
        st.plotly_chart(fig, use_container_width=True)


# --- R Distribution (Drilldown Expander) ---
def render_r_distribution(trades_df):
    with st.expander("📊 R Distribution", expanded=True):
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
            template="plotly_dark",
            labels={"r_multiple": "R Multiple"}
        )
        fig.add_vline(
            x=0, line_color="#ff1744",
            line_dash="dash",
            annotation_text="Break Even",
            annotation_position="top right"
        )
        fig.add_vline(
            x=1.5, line_color="#00c853",
            line_dash="dash",
            annotation_text="TP (1.5R)",
            annotation_position="top right"
        )
        fig.update_layout(
            height=320,
            margin=dict(l=0, r=0, t=10, b=0),
            xaxis_title="R Multiple",
            yaxis_title="Number of Trades",
            showlegend=False,
            font=dict(family="Inter")
        )
        st.plotly_chart(fig, use_container_width=True)


# --- Open / Pending Trades ---
def render_open_trades(trades_df):
    st.markdown("## 📂 Active Trades")

    open_t  = trades_df[trades_df["status"] == "OPEN"].copy() \
        if not trades_df.empty else pd.DataFrame()
    pending = trades_df[trades_df["status"] == "PENDING"].copy() \
        if not trades_df.empty else pd.DataFrame()

    if open_t.empty and pending.empty:
        st.info("No active or pending trades at the moment.")
        return

    OPEN_COLS = {
        "symbol":               "Symbol",
        "sector":               "Sector",
        "entry_time":           "Entry Time",
        "entry_price":          "Entry Price (₹)",
        "actual_entry_price":   "Actual Fill (₹)",
        "sl":                   "Stop Loss (₹)",
        "tp":                   "Take Profit (₹)",
        "quantity":             "Qty",
        "risk_amount":          "Risk (₹)",
        "ema_exit_alert":       "EMA Alert"
    }

    PENDING_COLS = {
        "symbol":       "Symbol",
        "sector":       "Sector",
        "entry_time":   "Signal Time",
        "entry_price":  "Entry Price (₹)",
        "sl":           "Stop Loss (₹)",
        "tp":           "Take Profit (₹)",
        "quantity":     "Qty",
        "risk_amount":  "Risk (₹)"
    }

    if not open_t.empty:
        st.markdown("#### ✅ Confirmed Open")
        cols = [c for c in OPEN_COLS if c in open_t.columns]
        display = open_t[cols].rename(
            columns={c: OPEN_COLS[c] for c in cols}
        ).reset_index(drop=True)
        st.dataframe(display, use_container_width=True, hide_index=True)

    if not pending.empty:
        st.markdown(
            "#### ⏳ Pending "
            "<span style='font-size:0.78rem; color:#9e9e9e;'>"
            "Place a CNC SL-M order in Zerodha at the entry price</span>",
            unsafe_allow_html=True
        )
        cols = [c for c in PENDING_COLS if c in pending.columns]
        display = pending[cols].rename(
            columns={c: PENDING_COLS[c] for c in cols}
        ).reset_index(drop=True)
        st.dataframe(display, use_container_width=True, hide_index=True)


# --- Signals / Watchlist ---
def render_signals(signals_df):
    if signals_df.empty:
        st.info("No signals yet — run the weekly scan to populate.")
        return

    # Separate WL from entry signals
    wl_df     = signals_df[signals_df["event_type"] == "WL"].copy()
    entry_df  = signals_df[
        signals_df["event_type"].isin(
            ["ENTRY_INITIAL", "ENTRY_UPDATED"]
        )
    ].copy()

    # --- Watchlist ---
    with st.expander("🔍 Watchlist (WL)", expanded=True):
        if wl_df.empty:
            st.info("No watchlist symbols yet.")
        else:
            WL_COLS = {
                "timestamp":          "Timestamp",
                "event_type":         "Event Type",
                "symbol":             "Symbol",
                "sector":             "Sector",
                "rsi5":               "RSI (5)",
                "support_zone_price": "Support Zone (₹)"
            }
            cols    = [c for c in WL_COLS if c in wl_df.columns]
            display = wl_df[cols].rename(
                columns={c: WL_COLS[c] for c in cols}
            ).sort_values(
                "Timestamp", ascending=False
            ).reset_index(drop=True)

            # Symbol filter
            sym_filter = st.text_input(
                "Filter by Symbol", "", key="wl_filter"
            )
            if sym_filter:
                display = display[
                    display["Symbol"].str.contains(
                        sym_filter.upper(), na=False
                    )
                ]
            st.dataframe(
                display, use_container_width=True,
                hide_index=True
            )

    # --- Entry Signals ---
    with st.expander("📋 Entry Signals", expanded=False):
        if entry_df.empty:
            st.info("No entry signals yet.")
        else:
            ENTRY_COLS = {
                "timestamp":   "Timestamp",
                "event_type":  "Event Type",
                "symbol":      "Symbol",
                "sector":      "Sector",
                "entry":       "Entry (₹)",
                "sl":          "Stop Loss (₹)",
                "tp":          "Take Profit (₹)",
                "quantity":    "Qty",
                "atr":         "ATR"
            }
            cols    = [c for c in ENTRY_COLS if c in entry_df.columns]
            display = entry_df[cols].rename(
                columns={c: ENTRY_COLS[c] for c in cols}
            ).sort_values(
                "Timestamp", ascending=False
            ).reset_index(drop=True)
            st.dataframe(
                display, use_container_width=True,
                hide_index=True
            )


# --- Trade History ---
def render_trade_history(trades_df):
    closed = trades_df[trades_df["status"] == "CLOSED"].copy() \
        if not trades_df.empty else pd.DataFrame()

    if closed.empty:
        st.info("No closed trades yet.")
        return

    closed["pnl_rupees"]  = closed["pnl_rupees"].astype(float)
    closed["r_multiple"]  = closed["r_multiple"].astype(float)

    HISTORY_COLS = {
        "symbol":               "Symbol",
        "sector":               "Sector",
        "entry_time":           "Entry Time",
        "actual_entry_price":   "Fill Price (₹)",
        "sl":                   "Stop Loss (₹)",
        "tp":                   "Take Profit (₹)",
        "quantity":             "Qty",
        "exit_time":            "Exit Time",
        "exit_price":           "Exit Price (₹)",
        "exit_reason":          "Result",
        "pnl_rupees":           "P&L (₹)",
        "r_multiple":           "R",
        "holding_period":       "Held"
    }

    cols    = [c for c in HISTORY_COLS if c in closed.columns]
    display = closed[cols].rename(
        columns={c: HISTORY_COLS[c] for c in cols}
    ).sort_values(
        "Exit Time", ascending=False
    ).reset_index(drop=True)

    def color_pnl(val):
        try:
            v     = float(val)
            color = "#00c853" if v > 0 else "#ff1744"
            return f"color: {color}; font-weight: 600"
        except Exception:
            return ""

    styled = display.style.map(
        color_pnl, subset=["P&L (₹)", "R"]
    )
    st.dataframe(
        styled, use_container_width=True,
        hide_index=True, height=400
    )


# --- Main ---
def main():
    signals_df, trades_df, stats_raw = load_all_data()
    stats_dict = parse_stats(stats_raw)

    render_sidebar(stats_dict)

    st.title("📈 Nifty 500 Trading Dashboard")
    st.markdown("---")

    # Performance metrics
    render_metrics(trades_df)
    st.markdown("---")

    # Charts side by side as drilldown expanders
    col1, col2 = st.columns(2)
    with col1:
        render_equity_curve(trades_df)
    with col2:
        render_r_distribution(trades_df)

    st.markdown("---")

    # Active trades
    render_open_trades(trades_df)
    st.markdown("---")

    # Tabs
    tab1, tab2 = st.tabs(["📋 Signals & Watchlist", "📜 Trade History"])
    with tab1:
        render_signals(signals_df)
    with tab2:
        render_trade_history(trades_df)


if __name__ == "__main__":
    main()