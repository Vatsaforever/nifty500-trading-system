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
        background-color: #f8fafc;
    }

    .card {
        background: #f8fafc;
        border: 0.5px solid #e2e8f0;
        border-radius: 10px;
        padding: 14px 16px;
        min-height: 80px;
        margin: 4px 0;
    }
    .card-badge-row {
        display: flex;
        align-items: center;
        gap: 8px;
        margin-bottom: 4px;
    }
    .card-badge {
        border-radius: 6px;
        padding: 4px 10px;
        font-size: 0.82rem;
        font-weight: 600;
        line-height: 1;
    }
    .card-label {
        font-size: 0.68rem;
        font-weight: 500;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: #64748b;
    }
    .card-sub {
        font-size: 0.72rem;
        color: #94a3b8;
        margin-top: 2px;
        padding-left: 2px;
    }

    .badge-blue   { background: #eff6ff; color: #3b82f6; }
    .badge-green  { background: #f0fdf4; color: #16a34a; }
    .badge-amber  { background: #fffbeb; color: #d97706; }
    .badge-red    { background: #fef2f2; color: #dc2626; }
    .badge-purple { background: #faf5ff; color: #7c3aed; }
    .badge-teal   { background: #f0fdfa; color: #0d9488; }
    .badge-slate  { background: #f1f5f9; color: #475569; }

    .section-title {
        font-size: 0.68rem;
        font-weight: 600;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: #94a3b8;
        margin: 20px 0 10px 0;
        padding-bottom: 6px;
        border-bottom: 0.5px solid #e2e8f0;
    }

    .health-row {
        display: flex;
        align-items: center;
        margin: 8px 0;
        gap: 12px;
    }
    .health-label {
        font-size: 0.76rem;
        color: #64748b;
        width: 100px;
        flex-shrink: 0;
    }
    .health-bar-bg {
        flex: 1;
        background: #f1f5f9;
        border-radius: 4px;
        height: 6px;
        overflow: hidden;
    }
    .health-bar-fill {
        height: 100%;
        border-radius: 4px;
    }
    .health-count {
        font-size: 0.82rem;
        font-weight: 600;
        color: #1e293b;
        width: 24px;
        text-align: right;
        flex-shrink: 0;
    }

    .regime-panel {
        background: #f8fafc;
        border: 0.5px solid #e2e8f0;
        border-radius: 10px;
        padding: 20px;
        height: 100%;
    }
    .regime-desc {
        font-size: 0.78rem;
        color: #64748b;
        margin-top: 8px;
        line-height: 1.6;
    }

    .status-open    { color: #16a34a; font-weight: 600; font-size: 0.76rem; }
    .status-pending { color: #d97706; font-weight: 600; font-size: 0.76rem; }

    .stMetric label {
        font-size: 0.72rem;
        color: #64748b;
        font-weight: 500;
        letter-spacing: 0.06em;
        text-transform: uppercase;
    }
    div[data-testid="stMetricValue"] {
        font-size: 1.5rem;
        font-weight: 600;
        color: #0f172a;
    }
    h1 {
        font-weight: 700;
        letter-spacing: -0.5px;
        font-size: 1.4rem !important;
        color: #0f172a !important;
    }
    .stTabs [data-baseweb="tab"] {
        font-size: 0.8rem;
        font-weight: 500;
    }
    div[data-testid="stDataFrame"] {
        border-radius: 8px;
        border: 0.5px solid #e2e8f0;
    }
    .stExpander {
        border: 0.5px solid #e2e8f0 !important;
        border-radius: 10px !important;
    }
</style>
""", unsafe_allow_html=True)


# --- Helpers ---
def card(icon, label, value, sub="", badge_color="blue"):
    st.markdown(f"""
    <div class="card">
        <div class="card-badge-row">
            <span class="card-badge badge-{badge_color}">{value}</span>
            <span class="card-label">{label}</span>
        </div>
        <div class="card-sub">{sub}</div>
    </div>
    """, unsafe_allow_html=True)

def health_bar(label, count, total, color):
    pct = (count / total * 100) if total > 0 else 0
    st.markdown(f"""
    <div class="health-row">
        <div class="health-label">{label}</div>
        <div class="health-bar-bg">
            <div class="health-bar-fill"
                 style="width:{pct}%; background:{color};">
            </div>
        </div>
        <div class="health-count">{count}</div>
    </div>
    """, unsafe_allow_html=True)


# --- Data Loading ---
@st.cache_data(ttl=300)
def load_sheet(tab_name):
    try:
        ws      = get_sheet_client(tab_name)
        records = ws.get_all_records()
        return pd.DataFrame(records)
    except Exception as e:
        st.error(f"Error loading {tab_name}: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=300)
def load_stats_raw():
    try:
        ws = get_sheet_client("Stats")
        return ws.get_all_values()
    except Exception as e:
        st.error(f"Error loading Stats: {e}")
        return []


def parse_stats(stats_raw):
    result = {}
    for row in stats_raw:
        if len(row) >= 2 and row[0] and row[1]:
            result[row[0]] = row[1]
    return result


def compute_portfolio_metrics(trades_df, capital):
    """Computes live portfolio metrics from open trades."""
    metrics = {
        "open_count":        0,
        "pending_count":     0,
        "portfolio_heat":    0.0,
        "capital_at_risk":   0.0,
        "largest_position":  0.0,
        "winning_capital":   0.0,
        "losing_capital":    0.0,
        "ema_alerts":        0,
        "near_tp":           0,
        "healthy":           0,
        "watch":             0,
        "at_risk":           0
    }

    if trades_df.empty or capital == 0:
        return metrics

    open_t = trades_df[trades_df["status"] == "OPEN"].copy()
    pending = trades_df[trades_df["status"] == "PENDING"].copy()

    metrics["open_count"]    = len(open_t)
    metrics["pending_count"] = len(pending)

    if open_t.empty:
        return metrics

    for _, t in open_t.iterrows():
        try:
            entry = float(t.get("actual_entry_price") or
                          t.get("entry_price") or 0)
            sl    = float(t.get("sl") or 0)
            tp    = float(t.get("tp") or 0)
            qty   = int(t.get("quantity") or 0)
            risk  = (entry - sl) * qty

            metrics["capital_at_risk"] += risk

            position_value = entry * qty
            if position_value > metrics["largest_position"]:
                metrics["largest_position"] = position_value

            if entry > sl:
                metrics["winning_capital"] += position_value
            else:
                metrics["losing_capital"]  += position_value

            if t.get("ema_exit_alert") == "TRUE":
                metrics["ema_alerts"] += 1

            # Distance to TP as % of range
            if tp > entry > sl:
                dist_to_tp = (tp - entry) / (tp - sl) * 100
                if dist_to_tp <= 20:
                    metrics["near_tp"] += 1

            # Portfolio health classification
            if entry > 0 and sl > 0:
                sl_dist_pct = (entry - sl) / entry * 100
                if sl_dist_pct > 5:
                    metrics["at_risk"]  += 1
                elif sl_dist_pct > 2:
                    metrics["watch"]    += 1
                else:
                    metrics["healthy"]  += 1

        except Exception:
            continue

    total_open = metrics["open_count"]
    metrics["portfolio_heat"]   = round(
        metrics["capital_at_risk"] / capital * 100, 1
    ) if capital > 0 else 0
    metrics["capital_at_risk"]  = round(
        metrics["capital_at_risk"] / capital * 100, 1
    )
    metrics["largest_position"] = round(
        metrics["largest_position"] / capital * 100, 1
    ) if capital > 0 else 0
    metrics["winning_capital"]  = round(
        metrics["winning_capital"] /
        (metrics["winning_capital"] + metrics["losing_capital"]) * 100, 1
    ) if (metrics["winning_capital"] + metrics["losing_capital"]) > 0 else 0
    metrics["losing_capital"]   = round(
        100 - metrics["winning_capital"], 1
    )

    return metrics


def compute_market_breadth(signals_df):
    """
    Estimates market breadth from the latest weekly scan —
    what % of scanned symbols passed the weekly trend filter.
    Uses WL count vs total scanned as a proxy.
    """
    if signals_df.empty:
        return None, "No data"

    wl_count = len(
        signals_df[signals_df["event_type"] == "WL"]
    )

    # Breadth interpretation
    if wl_count >= 50:
        return "BULL", f"{wl_count} symbols in uptrend — broad participation"
    elif wl_count >= 20:
        return "NEUTRAL", f"{wl_count} symbols in uptrend — mixed market"
    else:
        return "BEAR", f"{wl_count} symbols in uptrend — weak breadth"


# --- Sidebar ---
def render_sidebar(stats_dict):
    st.sidebar.markdown(
        "<h2 style='font-size:1.1rem; font-weight:700; "
        "letter-spacing:-0.3px;'>📈 Trading System</h2>",
        unsafe_allow_html=True
    )
    st.sidebar.markdown("---")

    capital = stats_dict.get("Trading Capital (₹)", "—")
    risk    = stats_dict.get("Risk Amount per Trade", "—")
    st.sidebar.metric("Trading Capital", f"₹{capital}")
    st.sidebar.metric("Risk Per Trade",  f"₹{risk}")

    st.sidebar.markdown("---")
    status       = stats_dict.get("Status", "—")
    days_left    = stats_dict.get("Days Till Refresh", "—")
    next_refresh = stats_dict.get("Next Refresh Due", "—")

    st.sidebar.markdown(
        "<p class='card-label'>🌐 Universe Status</p>",
        unsafe_allow_html=True
    )
    st.sidebar.markdown(f"**Status**: {status}")
    st.sidebar.markdown(f"**Days Till Refresh**: {days_left}")
    st.sidebar.markdown(f"**Next Due**: {next_refresh}")

    st.sidebar.markdown("---")
    st.sidebar.caption(
        f"Refreshes every 5 min · "
        f"Last: {datetime.now().strftime('%H:%M:%S')}"
    )
    if st.sidebar.button("🔄 Refresh Now"):
        st.cache_data.clear()
        st.rerun()


# --- Top Metric Cards Row 1: Performance ---
def render_performance_cards(trades_df):
    st.markdown(
        "<div class='section-title'>Performance</div>",
        unsafe_allow_html=True
    )

    closed = trades_df[trades_df["status"] == "CLOSED"].copy() \
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

    pnl_color = "green" if total_pnl >= 0 else "red"
    r_color   = "green" if avg_r >= 0 else "red"

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        card("", "Total Trades", total,
             f"{wins}W / {losses}L", "blue")
    with c2:
        card("", "Win Rate", f"{win_rate}%",
             "closed trades", "green")
    with c3:
        card("", "Avg R", avg_r,
             "per trade",
             "green" if avg_r >= 0 else "red")
    with c4:
        card("", "Profit Factor", pf,
             "gross profit / loss", "purple")
    with c5:
        card("", "Total P&L",
             f"₹{total_pnl:,.0f}",
             "all closed trades",
             "green" if total_pnl >= 0 else "red")


# --- Top Metric Cards Row 2: Portfolio ---
def render_portfolio_cards(pm, wl_count):
    st.markdown(
        "<div class='section-title'>Portfolio</div>",
        unsafe_allow_html=True
    )

    heat_color = (
        "red"    if pm["portfolio_heat"] > 10 else
        "yellow" if pm["portfolio_heat"] > 5  else
        "green"
    )
    c1, c2, c3, c4, c5, c6, c7 = st.columns(7)
    with c1:
        card("", "Holdings",
             pm["open_count"],
             "active positions", "blue")
    with c2:
        card("", "Watch List",
             wl_count,
             "monitor closely", "teal")
    with c3:
        card("", "Pending",
             pm["pending_count"],
             "awaiting fill", "amber")
    with c4:
        heat_color = (
            "red"   if pm["portfolio_heat"] > 10 else
            "amber" if pm["portfolio_heat"] > 5  else
            "green"
        )
        card("", "Portfolio Heat",
             f"{pm['portfolio_heat']}%",
             "total risk / capital", heat_color)
    with c5:
        card("", "Capital at Risk",
             f"{pm['capital_at_risk']}%",
             "across open trades", "amber")
    with c6:
        card("", "EMA Alerts",
             pm["ema_alerts"],
             "consider exiting",
             "red" if pm["ema_alerts"] > 0 else "slate")
    with c7:
        card("", "Near TP",
             pm["near_tp"],
             "within 20% of target",
             "green" if pm["near_tp"] > 0 else "slate")


def render_portfolio_health(pm):
    st.markdown(
        "<div class='section-title'>Portfolio Health</div>",
        unsafe_allow_html=True
    )

    total_open = pm["open_count"]

    col1, col2 = st.columns([1, 2])
    with col1:
        st.markdown(f"""
        <div class="regime-panel">
            <div class="card-label">Position Health</div>
            <br>
        """, unsafe_allow_html=True)

        health_bar("Healthy",       pm["healthy"], total_open, "#00c853")
        health_bar("Watch Closely", pm["watch"],   total_open, "#ffd600")
        health_bar("At Risk",       pm["at_risk"], total_open, "#ff1744")

        st.markdown("""
            <div class="regime-desc" style="margin-top:12px;">
                Healthy = SL within 2% of entry ·
                Watch = 2–5% · At Risk = more than 5%
            </div>
        </div>
        """, unsafe_allow_html=True)

    with col2:
        pass

# --- Charts ---
def render_charts(trades_df):
    col1, col2 = st.columns(2)

    with col1:
        with st.expander("📈 Equity Curve", expanded=True):
            closed = trades_df[trades_df["status"] == "CLOSED"].copy() \
                if not trades_df.empty else pd.DataFrame()
            if closed.empty:
                st.info("No closed trades yet.")
            else:
                closed["pnl_rupees"] = closed["pnl_rupees"].astype(float)
                closed = closed.sort_values("exit_time")
                closed["cumulative_pnl"] = \
                    closed["pnl_rupees"].cumsum()
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=closed["exit_time"],
                    y=closed["cumulative_pnl"],
                    mode="lines+markers",
                    line=dict(color="#00c853", width=2),
                    fill="tozeroy",
                    fillcolor="rgba(0,200,83,0.08)",
                    hovertemplate=(
                        "<b>%{x}</b><br>"
                        "P&L: ₹%{y:,.0f}<extra></extra>"
                    )
                ))
                fig.update_layout(
                    template="plotly_dark",
                    height=280,
                    margin=dict(l=0, r=0, t=10, b=0),
                    xaxis_title="Exit Date",
                    yaxis_title="Cumulative P&L (₹)",
                    showlegend=False,
                    font=dict(family="Inter"),
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)"
                )
                st.plotly_chart(fig, use_container_width=True)

    with col2:
        with st.expander("📊 R Distribution", expanded=True):
            closed = trades_df[trades_df["status"] == "CLOSED"].copy() \
                if not trades_df.empty else pd.DataFrame()
            if closed.empty:
                st.info("No closed trades yet.")
            else:
                closed["r_multiple"] = \
                    closed["r_multiple"].astype(float)
                fig = px.histogram(
                    closed, x="r_multiple", nbins=20,
                    color_discrete_sequence=["#2979ff"],
                    template="plotly_dark"
                )
                fig.add_vline(
                    x=0, line_color="#ff1744",
                    line_dash="dash",
                    annotation_text="Break Even"
                )
                fig.add_vline(
                    x=1.5, line_color="#00c853",
                    line_dash="dash",
                    annotation_text="TP 1.5R"
                )
                fig.update_layout(
                    height=280,
                    margin=dict(l=0, r=0, t=10, b=0),
                    xaxis_title="R Multiple",
                    yaxis_title="Trades",
                    showlegend=False,
                    font=dict(family="Inter"),
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)"
                )
                st.plotly_chart(fig, use_container_width=True)


# --- Active Trades ---
def render_active_trades(trades_df):
    st.markdown(
        "<div class='section-title'>Active Trades</div>",
        unsafe_allow_html=True
    )

    open_t  = trades_df[trades_df["status"] == "OPEN"].copy() \
        if not trades_df.empty else pd.DataFrame()
    pending = trades_df[trades_df["status"] == "PENDING"].copy() \
        if not trades_df.empty else pd.DataFrame()

    if open_t.empty and pending.empty:
        st.info("No active or pending trades.")
        return

    OPEN_COLS = {
        "symbol":             "Symbol",
        "company_name":       "Company",
        "sector":             "Sector",
        "entry_time":         "Entry Time",
        "entry_price":        "Entry (₹)",
        "actual_entry_price": "Fill (₹)",
        "sl":                 "SL (₹)",
        "tp":                 "TP (₹)",
        "quantity":           "Qty",
        "risk_amount":        "Risk (₹)",
        "ema_exit_alert":     "EMA ⚠️"
    }

    PENDING_COLS = {
        "symbol":       "Symbol",
        "company_name": "Company",
        "sector":       "Sector",
        "entry_time":   "Signal Time",
        "entry_price":  "Entry (₹)",
        "sl":           "SL (₹)",
        "tp":           "TP (₹)",
        "quantity":     "Qty",
        "risk_amount":  "Risk (₹)"
    }

    if not open_t.empty:
        st.markdown(
            "<p style='font-size:0.78rem; font-weight:600; "
            "color:#00c853;'>● CONFIRMED OPEN</p>",
            unsafe_allow_html=True
        )
        cols    = [c for c in OPEN_COLS if c in open_t.columns]
        display = open_t[cols].rename(
            columns={c: OPEN_COLS[c] for c in cols}
        ).reset_index(drop=True)
        st.dataframe(display, use_container_width=True,
                     hide_index=True)

    if not pending.empty:
        st.markdown(
            "<p style='font-size:0.78rem; font-weight:600; "
            "color:#ffd600;'>● PENDING "
            "<span style='font-weight:400; color:#757575;'>"
            "— Place CNC SL-M order in Zerodha</span></p>",
            unsafe_allow_html=True
        )
        cols    = [c for c in PENDING_COLS if c in pending.columns]
        display = pending[cols].rename(
            columns={c: PENDING_COLS[c] for c in cols}
        ).reset_index(drop=True)
        st.dataframe(display, use_container_width=True,
                     hide_index=True)


# --- Signals ---
def render_signals(signals_df):
    wl_df    = signals_df[
        signals_df["event_type"] == "WL"
    ].copy() if not signals_df.empty else pd.DataFrame()

    entry_df = signals_df[
        signals_df["event_type"].isin(
            ["ENTRY_INITIAL", "ENTRY_UPDATED"]
        )
    ].copy() if not signals_df.empty else pd.DataFrame()

    with st.expander("🔍 Watchlist (WL)", expanded=True):
        if wl_df.empty:
            st.info("No watchlist symbols yet.")
        else:
            WL_COLS = {
                "timestamp":          "Timestamp",
                "event_type":         "Event Type",
                "symbol":             "Symbol",
                "company_name":       "Company",
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

            sym = st.text_input(
                "Filter by Symbol", "", key="wl_sym"
            )
            if sym:
                display = display[
                    display["Symbol"].str.contains(
                        sym.upper(), na=False
                    )
                ]
            st.dataframe(display, use_container_width=True,
                         hide_index=True)

    with st.expander("📋 Entry Signals", expanded=False):
        if entry_df.empty:
            st.info("No entry signals yet.")
        else:
            ENTRY_COLS = {
                "timestamp":   "Timestamp",
                "event_type":  "Event Type",
                "symbol":      "Symbol",
                "company_name": "Company",
                "sector":      "Sector",
                "entry":       "Entry (₹)",
                "sl":          "SL (₹)",
                "tp":          "TP (₹)",
                "quantity":    "Qty",
                "atr":         "ATR"
            }
            cols    = [c for c in ENTRY_COLS
                       if c in entry_df.columns]
            display = entry_df[cols].rename(
                columns={c: ENTRY_COLS[c] for c in cols}
            ).sort_values(
                "Timestamp", ascending=False
            ).reset_index(drop=True)
            st.dataframe(display, use_container_width=True,
                         hide_index=True)


# --- Trade History ---
def render_trade_history(trades_df):
    closed = trades_df[trades_df["status"] == "CLOSED"].copy() \
        if not trades_df.empty else pd.DataFrame()

    if closed.empty:
        st.info("No closed trades yet.")
        return

    closed["pnl_rupees"] = closed["pnl_rupees"].astype(float)
    closed["r_multiple"] = closed["r_multiple"].astype(float)

    HISTORY_COLS = {
        "symbol":             "Symbol",
        "company_name":       "Company",
        "sector":             "Sector",
        "entry_time":         "Entry",
        "actual_entry_price": "Fill (₹)",
        "sl":                 "SL (₹)",
        "tp":                 "TP (₹)",
        "quantity":           "Qty",
        "exit_time":          "Exit",
        "exit_price":         "Exit (₹)",
        "exit_reason":        "Result",
        "pnl_rupees":         "P&L (₹)",
        "r_multiple":         "R",
        "holding_period":     "Held"
    }

    cols    = [c for c in HISTORY_COLS if c in closed.columns]
    display = closed[cols].rename(
        columns={c: HISTORY_COLS[c] for c in cols}
    ).sort_values("Exit", ascending=False).reset_index(drop=True)

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
    st.dataframe(styled, use_container_width=True,
                 hide_index=True, height=400)
def render_orb_signals():
    st.markdown(
        "<div class='section-title'>ORB Signals — Nifty 50 Intraday</div>",
        unsafe_allow_html=True
    )
    try:
        orb_ws  = get_sheet_client("ORB Signals")
        records = orb_ws.get_all_records()
        orb_df  = pd.DataFrame(records)
    except Exception as e:
        st.info("ORB Signals sheet not available.")
        return

    if orb_df.empty:
        st.info("No ORB signals yet — scanner runs at 9:30 AM on trading days.")
        return

    orb_df['timestamp'] = pd.to_datetime(orb_df['timestamp'])
    today    = pd.Timestamp.now().date()
    today_df = orb_df[orb_df['timestamp'].dt.date == today].copy()

    if today_df.empty:
        last_date = orb_df['timestamp'].max().date()
        st.info(f"No ORB signals today. Last signal date: {last_date}")
        all_df = orb_df.copy()
    else:
        st.markdown(
            f"<p style='font-size:0.78rem; color:#16a34a; font-weight:600;'>"
            f"● {len(today_df)} signal(s) today — "
            f"place MIS SL-M orders in Zerodha, close by 3:15 PM</p>",
            unsafe_allow_html=True
        )
        all_df = orb_df.copy()

    ORB_COLS = {
        'timestamp':   'Time',
        'symbol':      'Symbol',
        'sector':      'Sector',
        'or_high':     'OR High (₹)',
        'or_low':      'OR Low (₹)',
        'range_pct':   'Range %',
        'gap_pct':     'Gap %',
        'entry':       'Entry (₹)',
        'sl':          'SL (₹)',
        'tp':          'TP (₹)',
        'quantity':    'Qty',
        'risk_amount': 'Risk (₹)',
        'order_type':  'Order',
        'exit_by':     'Exit By'
    }
    cols    = [c for c in ORB_COLS if c in all_df.columns]
    display = all_df[cols].rename(
        columns={c: ORB_COLS[c] for c in cols}
    ).sort_values('Time', ascending=False).reset_index(drop=True)
    st.dataframe(display, use_container_width=True, hide_index=True)

@st.cache_data(ttl=300)
def load_stats_raw():
    try:
        ws = get_sheet_client("Stats")
        return ws.get_all_values()
    except Exception as e:
        st.error(f"Error loading Stats: {e}")
        return []


@st.cache_data(ttl=300)
def load_ft_data():
    try:
        pb  = get_sheet_client("FT Pullback")
        orb = get_sheet_client("FT ORB")
        sm  = get_sheet_client("FT Summary")
        return (
            pd.DataFrame(pb.get_all_records()),
            pd.DataFrame(orb.get_all_records()),
            pd.DataFrame(sm.get_all_records())
        )
    except Exception:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()


def render_forward_test(ft_pb, ft_orb, ft_sum):
    st.markdown(
        "<div class='section-title'>"
        "Forward Test — Live Paper Trading</div>",
        unsafe_allow_html=True
    )

    col1, col2 = st.columns(2)

    # Pullback summary
    with col1:
        st.markdown("**Pullback System (₹10L)**")
        if not ft_pb.empty:
            total  = len(ft_pb)
            closed = ft_pb[ft_pb['status'] == 'CLOSED']
            open_t = ft_pb[ft_pb['status'] == 'OPEN']
            wins   = len(closed[
                pd.to_numeric(closed['r_multiple'],
                              errors='coerce') > 0
            ]) if not closed.empty else 0
            pnl    = pd.to_numeric(
                closed['pnl_rupees'], errors='coerce'
            ).sum() if not closed.empty else 0
            net    = pnl - len(closed) * 75

            st.metric("Total Signals",  total)
            st.metric("Open Trades",    len(open_t))
            st.metric("Closed Trades",  len(closed))
            st.metric("Wins",           wins)
            st.metric("Net P&L",        f"₹{net:,.0f}")
        else:
            st.info("No pullback FT trades yet.")

    # ORB summary
    with col2:
        st.markdown("**ORB System (₹10L)**")
        if not ft_orb.empty:
            total  = len(ft_orb)
            closed = ft_orb[ft_orb['status'] == 'CLOSED']
            open_t = ft_orb[ft_orb['status'] == 'OPEN']
            wins   = len(closed[
                pd.to_numeric(closed['r_multiple'],
                              errors='coerce') > 0
            ]) if not closed.empty else 0
            pnl    = pd.to_numeric(
                closed['pnl_rupees'], errors='coerce'
            ).sum() if not closed.empty else 0
            net    = pnl - len(closed) * 75

            st.metric("Total Signals",  total)
            st.metric("Open Trades",    len(open_t))
            st.metric("Closed Trades",  len(closed))
            st.metric("Wins",           wins)
            st.metric("Net P&L",        f"₹{net:,.0f}")
        else:
            st.info("No ORB FT trades yet.")

    # Open trades detail
    if not ft_pb.empty:
        open_pb = ft_pb[ft_pb['status'] == 'OPEN']
        if not open_pb.empty:
            with st.expander(
                f"📋 Pullback Open Trades ({len(open_pb)})",
                expanded=True
            ):
                st.dataframe(
                    open_pb[[
                        'entry_date', 'symbol', 'sector',
                        'entry_price', 'sl', 'tp', 'quantity'
                    ]].reset_index(drop=True),
                    use_container_width=True,
                    hide_index=True
                )

    if not ft_orb.empty:
        open_orb = ft_orb[ft_orb['status'] == 'OPEN']
        if not open_orb.empty:
            with st.expander(
                f"🚀 ORB Open Trades ({len(open_orb)})",
                expanded=True
            ):
                st.dataframe(
                    open_orb[[
                        'trade_date', 'symbol', 'sector',
                        'entry_price', 'sl', 'tp', 'quantity'
                    ]].reset_index(drop=True),
                    use_container_width=True,
                    hide_index=True
                )

# --- Main ---
def main():
    signals_df, trades_df, stats_raw = (
        load_sheet("Signals"),
        load_sheet("Trades"),
        load_stats_raw()
    )
    stats_dict = parse_stats(stats_raw)

    # Capital
    try:
        capital = float(
            str(stats_dict.get(
                "Trading Capital (₹)", "0"
            )).replace(",", "")
        )
    except Exception:
        capital = 0

    # Portfolio metrics
    pm = compute_portfolio_metrics(trades_df, capital)

    # WL count
    wl_count = len(
        signals_df[signals_df["event_type"] == "WL"]
    ) if not signals_df.empty else 0

    render_sidebar(stats_dict)

    # Header
    st.markdown(
        "<h1 style='color:#0f172a;'>Nifty 500 · Trading Dashboard</h1>",
        unsafe_allow_html=True
    )
    st.markdown(
        "<p style='color:#94a3b8; font-size:0.8rem; "
        "margin-top:-12px;'>Scanner intelligence and "
        "holding action dashboard</p>",
        unsafe_allow_html=True
    )
    # Row 1: Performance cards
    render_performance_cards(trades_df)

    # Row 2: Portfolio cards
    render_portfolio_cards(pm, wl_count)

    st.markdown("---")

    # Row 3: Portfolio Health
    render_portfolio_health(pm)

    st.markdown("---")

    # Row 4: Charts
    render_charts(trades_df)

    st.markdown("---")

    # Row 5: Active trades
    render_active_trades(trades_df)

    st.markdown("---")

        # ORB Signals
    render_orb_signals()
    st.markdown("---")

    # Row 6: Tabs
    tab1, tab2 = st.tabs([
        "📋 Signals & Watchlist",
        "📜 Trade History"
    ])
    with tab1:
        render_signals(signals_df)
    with tab2:
        render_trade_history(trades_df)
# Forward Test
    ft_pb, ft_orb, ft_sum = load_ft_data()
    render_forward_test(ft_pb, ft_orb, ft_sum)
    st.markdown("---")

if __name__ == "__main__":
    main()