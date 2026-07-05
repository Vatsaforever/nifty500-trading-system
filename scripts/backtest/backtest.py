import sys
import os
import math
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
sys.path.append(".")

from scripts.data_fetch.kite_auth import load_kite_client
from scripts.data_fetch.fetch_daily import fetch_daily_kite, load_instrument_map
from scripts.data_fetch.fetch_weekly import fetch_weekly
from scripts.data_fetch.fetch_intraday_60m import fetch_intraday_60m
from scripts.filters.weekly_trend_filter import is_weekly_uptrend
from scripts.filters.daily_oversold_filter import is_daily_oversold_at_support
from scripts.signals.signal_engine_60m import (
    prepare_60m_indicators, is_signal_candle, compute_trade_levels
)
from scripts.utils.indicators import ema
from scripts.utils.config import (
    UNIVERSE_FILE, EMA_EXIT_FAST, EMA_EXIT_SLOW,
    RISK_PCT, TP_MULTIPLE
)

# --- Config ---
BACKTEST_CAPITAL = 1_000_000
BACKTEST_RISK    = BACKTEST_CAPITAL * RISK_PCT
OUTPUT_FILE      = "data/processed/backtest_results_60m.csv"


def run_backtest_on_symbol(symbol, daily_df, weekly_df, df_60m):
    """
    Runs the full 60m strategy backtest on a single symbol.
    Weekly/daily filters applied per bar date.
    Returns a list of completed trade dicts.
    """
    trades = []

    # Prepare indicators
    df = prepare_60m_indicators(df_60m)
    df.index = df.index.tz_localize(None) \
        if df.index.tzinfo else df.index

    df["ema9_exit"]  = ema(df["close"], period=EMA_EXIT_FAST)
    df["ema21_exit"] = ema(df["close"], period=EMA_EXIT_SLOW)

    daily_df = daily_df.copy()
    daily_df.index = daily_df.index.tz_localize(None) \
        if daily_df.index.tzinfo else daily_df.index

    weekly_df = weekly_df.copy()
    weekly_df.index = weekly_df.index.tz_localize(None) \
        if weekly_df.index.tzinfo else weekly_df.index

    active_signal   = None
    live_trade      = None
    ema_alert_fired = False

    for i in range(1, len(df) - 1):
        candle      = df.iloc[i]
        candle_time = candle.name
        candle_date = candle_time.date()

        # ---------------------------------------------------
        # LIVE TRADE: check exits first
        # ---------------------------------------------------
        if live_trade is not None:
            candle_high = float(candle["high"])
            candle_low  = float(candle["low"])
            entry = live_trade["entry"]
            sl    = live_trade["sl"]
            tp    = live_trade["tp"]
            qty   = live_trade["quantity"]

            # SL hit (priority)
            if candle_low <= sl:
                pnl = round((sl - entry) * qty, 2)
                trades.append({
                    **live_trade,
                    "exit_time":      str(candle_time),
                    "exit_price":     sl,
                    "exit_reason":    "SL_HIT",
                    "pnl_rupees":     pnl,
                    "r_multiple":     -1.0,
                    "ema_exit_alert": ema_alert_fired,
                    "holding_hours":  round(
                        (candle_time - pd.Timestamp(
                            live_trade["entry_time"]
                        )).total_seconds() / 3600, 1
                    )
                })
                live_trade      = None
                ema_alert_fired = False
                continue

            # TP hit
            if candle_high >= tp:
                pnl = round((tp - entry) * qty, 2)
                trades.append({
                    **live_trade,
                    "exit_time":      str(candle_time),
                    "exit_price":     tp,
                    "exit_reason":    "TP_HIT",
                    "pnl_rupees":     pnl,
                    "r_multiple":     round(TP_MULTIPLE, 2),
                    "ema_exit_alert": ema_alert_fired,
                    "holding_hours":  round(
                        (candle_time - pd.Timestamp(
                            live_trade["entry_time"]
                        )).total_seconds() / 3600, 1
                    )
                })
                live_trade      = None
                ema_alert_fired = False
                continue

            # EMA exit alert (not closing)
            curr_9  = candle["ema9_exit"]
            curr_21 = candle["ema21_exit"]
            prev_9  = df["ema9_exit"].iloc[i - 1]
            prev_21 = df["ema21_exit"].iloc[i - 1]
            if (prev_9 >= prev_21) and (curr_9 < curr_21):
                ema_alert_fired = True
            continue

        # ---------------------------------------------------
        # ACTIVE SIGNAL: check BUY trigger or ENTRY_UPDATED
        # ---------------------------------------------------
        if active_signal is not None:
            candle_high = float(candle["high"])

            # BUY triggered
            if candle_high >= active_signal["active_entry"]:
                live_trade = {
                    "symbol":      symbol,
                    "entry_time":  str(candle_time),
                    "entry":       active_signal["active_entry"],
                    "sl":          active_signal["active_sl"],
                    "tp":          active_signal["active_tp"],
                    "quantity":    active_signal["active_quantity"],
                    "risk_amount": BACKTEST_RISK,
                    "signal_time": active_signal["signal_time"]
                }
                active_signal = None
                continue

            # Lower-high replacement
            if is_signal_candle(df, i):
                if candle_high < active_signal["active_high"]:
                    atr_val = float(candle["atr14"])
                    levels  = compute_trade_levels(
                        candle, atr_val, BACKTEST_RISK
                    )
                    if levels:
                        active_signal.update({
                            "active_entry":    levels["entry"],
                            "active_sl":       levels["sl"],
                            "active_tp":       levels["tp"],
                            "active_high":     candle_high,
                            "active_low":      float(candle["low"]),
                            "active_atr":      atr_val,
                            "active_quantity": levels["quantity"]
                        })
            continue

        # ---------------------------------------------------
        # NO SIGNAL: check filters on PREVIOUS daily bar,
        # then check 60m signal candle on current bar
        # ---------------------------------------------------

        # Weekly filter — use weekly data up to this date
        weekly_to_date = weekly_df[
            weekly_df.index.date <= candle_date
        ]
        if len(weekly_to_date) < 30:
            continue
        weekly_pass, _ = is_weekly_uptrend(weekly_to_date)
        if not weekly_pass:
            continue

        # Daily filter — use PREVIOUS day's data
        # (oversold yesterday → signal today)
        prev_date     = pd.Timestamp(candle_date) - timedelta(days=1)
        daily_to_prev = daily_df[
            daily_df.index.date <= prev_date.date()
        ]
        if len(daily_to_prev) < 60:
            continue
        daily_pass, _ = is_daily_oversold_at_support(daily_to_prev)
        if not daily_pass:
            continue

        # 60m signal candle check on current bar
        if not is_signal_candle(df, i):
            continue

        atr_val = float(candle["atr14"])
        levels  = compute_trade_levels(candle, atr_val, BACKTEST_RISK)
        if levels is None:
            continue

        active_signal = {
            "active_entry":    levels["entry"],
            "active_sl":       levels["sl"],
            "active_tp":       levels["tp"],
            "active_high":     float(candle["high"]),
            "active_low":      float(candle["low"]),
            "active_atr":      atr_val,
            "active_quantity": levels["quantity"],
            "signal_time":     str(candle_time)
        }

    return trades


def print_summary(df):
    total     = len(df)
    wins      = len(df[df["r_multiple"] > 0])
    losses    = total - wins
    win_rate  = round(wins / total * 100, 1) if total > 0 else 0
    avg_r     = round(df["r_multiple"].mean(), 3)
    total_pnl = round(df["pnl_rupees"].sum(), 2)
    expectancy = round(df["pnl_rupees"].mean(), 2)

    gross_win  = df[df["pnl_rupees"] > 0]["pnl_rupees"].sum()
    gross_loss = abs(
        df[df["pnl_rupees"] < 0]["pnl_rupees"].sum()
    )
    pf = round(gross_win / gross_loss, 2) if gross_loss > 0 else 0

    # Max drawdown
    df_s     = df.sort_values("exit_time")
    cum_pnl  = df_s["pnl_rupees"].cumsum()
    roll_max = cum_pnl.cummax()
    drawdown = cum_pnl - roll_max
    max_dd   = round(drawdown.min(), 2)
    max_dd_pct = round(max_dd / BACKTEST_CAPITAL * 100, 2)

    # Avg holding in hours
    avg_hold = round(df["holding_hours"].mean(), 1) \
        if "holding_hours" in df.columns else "N/A"

    # By exit reason
    by_reason = df.groupby("exit_reason").agg(
        count=("pnl_rupees", "count"),
        total_pnl=("pnl_rupees", "sum")
    )

    # By symbol
    by_symbol = df.groupby("symbol").agg(
        trades=("pnl_rupees", "count"),
        pnl=("pnl_rupees", "sum"),
        win_rate=("r_multiple", lambda x:
                  round((x > 0).mean() * 100, 1)),
        avg_r=("r_multiple", "mean")
    ).sort_values("pnl", ascending=False)

    print(f"\n{'='*60}")
    print(f"BACKTEST RESULTS (60m Signal Engine)")
    print(f"Capital: ₹{BACKTEST_CAPITAL:,} | "
          f"Risk/trade: ₹{BACKTEST_RISK:,.0f} | "
          f"Window: Last 60 days")
    print(f"{'='*60}")
    print(f"Total Trades:     {total}")
    print(f"Wins:             {wins}")
    print(f"Losses:           {losses}")
    print(f"Win Rate:         {win_rate}%")
    print(f"Average R:        {avg_r}")
    print(f"Profit Factor:    {pf}")
    print(f"Expectancy:       ₹{expectancy:,.2f} per trade")
    print(f"Total P&L:        ₹{total_pnl:,.2f}")
    print(f"Max Drawdown:     ₹{max_dd:,.2f} ({max_dd_pct}%)")
    print(f"Avg Holding:      {avg_hold} hours")
    print(f"\n--- By Exit Reason ---")
    print(by_reason.to_string())
    print(f"\n--- Top 10 Symbols ---")
    print(by_symbol.head(10).to_string())
    print(f"\n--- Bottom 10 Symbols ---")
    print(by_symbol.tail(10).to_string())
    print(f"{'='*60}")
    print(f"Results saved: {OUTPUT_FILE}")


def run_full_backtest(max_symbols=500):
    print(f"\n{'='*60}")
    print(f"60M BACKTEST — "
          f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Symbols: {max_symbols} | "
          f"60m window: last 60 days")
    print(f"{'='*60}\n")

    universe = pd.read_csv(UNIVERSE_FILE)
    active   = universe[universe["active"] == True]
    symbols  = active["symbol"].tolist()[:max_symbols]

    kite = load_kite_client()
    imap = load_instrument_map()

    all_trades = []
    errors     = 0
    skipped    = 0

    for i, symbol in enumerate(symbols):
        try:
            print(f"[{i+1}/{len(symbols)}] {symbol}", end=" ... ")

            daily_df  = fetch_daily_kite(
                symbol, kite=kite, instrument_map=imap
            )
            weekly_df = fetch_weekly(symbol)
            df_60m    = fetch_intraday_60m(
                symbol, kite=kite, instrument_map=imap
            )

            if df_60m.empty or len(df_60m) < 20:
                print("⏭️  Skipped (insufficient 60m data)")
                skipped += 1
                continue

            trades = run_backtest_on_symbol(
                symbol, daily_df, weekly_df, df_60m
            )

            if trades:
                all_trades.extend(trades)
                wins   = sum(1 for t in trades
                             if t["r_multiple"] > 0)
                losses = len(trades) - wins
                pnl    = sum(t["pnl_rupees"] for t in trades)
                print(f"✅ {len(trades)} trades | "
                      f"{wins}W {losses}L | "
                      f"₹{pnl:,.0f}")
            else:
                print("— No trades")

        except Exception as e:
            print(f"ERROR — {e}")
            errors += 1
            continue

    if all_trades:
        results_df = pd.DataFrame(all_trades)
        os.makedirs("data/processed", exist_ok=True)
        results_df.to_csv(OUTPUT_FILE, index=False)
        print_summary(results_df)
    else:
        print("\nNo trades generated.")

    print(f"\nErrors: {errors} | Skipped: {skipped}")
    return all_trades


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--symbols", type=int, default=500,
        help="Symbols to test (default 500)"
    )
    args = parser.parse_args()
    run_full_backtest(max_symbols=args.symbols)