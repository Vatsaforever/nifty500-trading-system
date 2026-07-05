import sys
import os
import math
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, time
sys.path.append(".")

from scripts.data_fetch.kite_auth import load_kite_client
from scripts.data_fetch.fetch_daily import fetch_daily_kite, load_instrument_map
from scripts.data_fetch.fetch_intraday_60m import fetch_intraday_60m
from scripts.utils.indicators import ema
from scripts.utils.config import UNIVERSE_FILE, RISK_PCT, TP_MULTIPLE

# --- Config ---
BACKTEST_CAPITAL    = 1_000_000
BACKTEST_RISK       = BACKTEST_CAPITAL * RISK_PCT
MAX_POSITION_VALUE  = 100_000
OUTPUT_FILE         = "data/processed/backtest_orb.csv"

# ORB-specific parameters
MIN_RANGE_PCT       = 0.003   # 0.3% minimum opening range
MAX_RANGE_PCT       = 0.03    # 3.0% maximum opening range
MAX_GAP_PCT         = 0.02    # 2.0% max gap at open vs prev close
VOLUME_MULTIPLIER   = 1.5     # breakout volume must be 1.5x OR candle volume
EOD_EXIT_TIME       = time(15, 15)   # exit at 3:15pm if still open


def get_weekly_ema20(daily_df, date):
    """Returns weekly EMA20 for a given date using daily data."""
    daily_to_date = daily_df[daily_df.index.date <= date].copy()
    if len(daily_to_date) < 30:
        return None, None
    weekly = daily_to_date["close"].resample("W").last()
    weekly_ema = weekly.ewm(span=20, adjust=False).mean()
    return float(weekly.iloc[-1]), float(weekly_ema.iloc[-1])


def run_orb_backtest_on_symbol(symbol, daily_df, df_60m):
    """
    Runs ORB backtest on a single symbol using 60m data.
    Returns list of completed trades.
    """
    trades = []

    daily_df = daily_df.copy()
    daily_df.index = daily_df.index.tz_localize(None) \
        if daily_df.index.tzinfo else daily_df.index

    df = df_60m.copy()
    df.index = df.index.tz_localize(None) \
        if df.index.tzinfo else df.index

    # Group candles by trading date
    df['date'] = df.index.date
    dates = sorted(df['date'].unique())

    for trade_date in dates:
        day_candles = df[df['date'] == trade_date].copy()
        day_candles = day_candles.sort_index()

        if len(day_candles) < 2:
            continue

        # --- Opening Range: first candle (9:15-9:30am) ---
        or_candle = day_candles.iloc[0]
        or_high   = float(or_candle['high'])
        or_low    = float(or_candle['low'])
        or_close  = float(or_candle['close'])
        or_volume = float(or_candle['volume'])
        or_open   = float(or_candle['open'])

        # --- Filters ---

        # 1. Weekly trend filter
        weekly_close, weekly_ema20 = get_weekly_ema20(
            daily_df, trade_date
        )
        if weekly_close is None or weekly_close <= weekly_ema20:
            continue

        # 2. Gap filter — skip if gapped up more than 2%
        prev_days = daily_df[daily_df.index.date < trade_date]
        if len(prev_days) == 0:
            continue
        prev_close = float(prev_days['close'].iloc[-1])
        gap_pct = (or_open - prev_close) / prev_close
        if gap_pct > MAX_GAP_PCT:
            continue

        # 3. Range size filter
        range_width = or_high - or_low
        range_pct   = range_width / or_low
        if range_pct < MIN_RANGE_PCT or range_pct > MAX_RANGE_PCT:
            continue

        # --- Scan remaining candles for breakout ---
        remaining = day_candles.iloc[1:]
        trade_taken = False

        for _, candle in remaining.iterrows():
            candle_time = candle.name.time()

            # EOD exit — if we have an open trade close it
            if candle_time >= EOD_EXIT_TIME:
                break

            candle_high   = float(candle['high'])
            candle_low    = float(candle['low'])
            candle_volume = float(candle['volume'])

            # Check for upside breakout
            if candle_high > or_high and not trade_taken:

                # Volume filter
                if candle_volume < or_volume * VOLUME_MULTIPLIER:
                    continue

                # Compute trade levels
                entry = or_high
                sl    = or_low
                rps   = entry - sl

                if rps <= 0:
                    break

                qty_risk = math.floor(BACKTEST_RISK / rps)
                qty_cap  = math.floor(MAX_POSITION_VALUE / entry)
                qty      = min(qty_risk, qty_cap)

                if qty == 0:
                    break

                tp           = round(entry + TP_MULTIPLE * rps, 2)
                actual_risk  = round(rps * qty, 2)
                position_val = round(entry * qty, 2)

                trade_taken = True
                entry_time  = str(candle.name)

                # Now scan forward for exit
                exit_candles = remaining[
                    remaining.index > candle.name
                ]
                exit_price  = None
                exit_reason = None
                exit_time   = None

                for _, ec in exit_candles.iterrows():
                    ec_time = ec.name.time()
                    ec_high = float(ec['high'])
                    ec_low  = float(ec['low'])

                    # EOD exit
                    if ec_time >= EOD_EXIT_TIME:
                        exit_price  = float(ec['open'])
                        exit_reason = "EOD_EXIT"
                        exit_time   = str(ec.name)
                        break

                    # SL hit (priority)
                    if ec_low <= sl:
                        exit_price  = sl
                        exit_reason = "SL_HIT"
                        exit_time   = str(ec.name)
                        break

                    # TP hit
                    if ec_high >= tp:
                        exit_price  = tp
                        exit_reason = "TP_HIT"
                        exit_time   = str(ec.name)
                        break

                # If no exit found, close at last candle
                if exit_price is None:
                    last = day_candles.iloc[-1]
                    exit_price  = float(last['close'])
                    exit_reason = "EOD_EXIT"
                    exit_time   = str(last.name)

                pnl        = round((exit_price - entry) * qty, 2)
                r_multiple = round(
                    (exit_price - entry) / rps, 2
                ) if rps > 0 else 0

                trades.append({
                    "symbol":        symbol,
                    "trade_date":    str(trade_date),
                    "entry_time":    entry_time,
                    "or_high":       round(or_high, 2),
                    "or_low":        round(or_low, 2),
                    "or_range_pct":  round(range_pct * 100, 2),
                    "entry":         round(entry, 2),
                    "sl":            round(sl, 2),
                    "tp":            round(tp, 2),
                    "quantity":      qty,
                    "position_value": position_val,
                    "risk_amount":   actual_risk,
                    "exit_time":     exit_time,
                    "exit_price":    round(exit_price, 2),
                    "exit_reason":   exit_reason,
                    "pnl_rupees":    pnl,
                    "r_multiple":    r_multiple,
                    "gap_pct":       round(gap_pct * 100, 2)
                })
                break   # one trade per day per symbol

    return trades


def print_summary(df):
    total      = len(df)
    wins       = len(df[df['r_multiple'] > 0])
    losses     = len(df[df['r_multiple'] < 0])
    eod        = len(df[df['exit_reason'] == 'EOD_EXIT'])
    win_rate   = round(wins / total * 100, 1) if total > 0 else 0
    avg_r      = round(df['r_multiple'].mean(), 3)
    total_pnl  = round(df['pnl_rupees'].sum(), 2)
    expectancy = round(df['pnl_rupees'].mean(), 2)

    gross_win  = df[df['pnl_rupees'] > 0]['pnl_rupees'].sum()
    gross_loss = abs(df[df['pnl_rupees'] < 0]['pnl_rupees'].sum())
    pf         = round(gross_win / gross_loss, 2) \
        if gross_loss > 0 else 0

    df_s       = df.sort_values('exit_time')
    cum_pnl    = df_s['pnl_rupees'].cumsum()
    roll_max   = cum_pnl.cummax()
    drawdown   = cum_pnl - roll_max
    max_dd     = round(drawdown.min(), 2)
    max_dd_pct = round(max_dd / BACKTEST_CAPITAL * 100, 2)

    final_capital = round(BACKTEST_CAPITAL + total_pnl, 2)
    return_pct    = round(total_pnl / BACKTEST_CAPITAL * 100, 2)

    by_reason = df.groupby('exit_reason').agg(
        count=('pnl_rupees', 'count'),
        total_pnl=('pnl_rupees', 'sum'),
        avg_r=('r_multiple', 'mean')
    ).round(2)

    df['month'] = pd.to_datetime(df['trade_date']).dt.to_period('M')
    by_month = df.groupby('month').agg(
        trades=('pnl_rupees', 'count'),
        wins=('r_multiple', lambda x: (x > 0).sum()),
        pnl=('pnl_rupees', 'sum')
    )
    by_month['win_rate']   = (
        by_month['wins'] / by_month['trades'] * 100
    ).round(1)
    by_month['cumulative'] = by_month['pnl'].cumsum().round(0)

    by_symbol = df.groupby('symbol').agg(
        trades=('pnl_rupees', 'count'),
        pnl=('pnl_rupees', 'sum'),
        win_rate=('r_multiple', lambda x:
                  round((x > 0).mean() * 100, 1))
    ).sort_values('pnl', ascending=False)

    print(f"\n{'='*60}")
    print(f"ORB BACKTEST RESULTS")
    print(f"Capital: ₹{BACKTEST_CAPITAL:,} | "
          f"Risk/trade: ₹{BACKTEST_RISK:,.0f} | "
          f"Position cap: ₹{MAX_POSITION_VALUE:,}")
    print(f"{'='*60}")
    print(f"Total Trades:     {total}")
    print(f"Wins (TP):        {wins}")
    print(f"Losses (SL):      {losses}")
    print(f"EOD Exits:        {eod}")
    print(f"Win Rate:         {win_rate}%")
    print(f"Average R:        {avg_r}")
    print(f"Profit Factor:    {pf}")
    print(f"Expectancy:       ₹{expectancy:,.2f} per trade")
    print(f"Total P&L:        ₹{total_pnl:,.2f}")
    print(f"Return:           {return_pct}%")
    print(f"Final Capital:    ₹{final_capital:,.0f}")
    print(f"Max Drawdown:     ₹{max_dd:,.2f} ({max_dd_pct}%)")
    print(f"\n--- By Exit Reason ---")
    print(by_reason.to_string())
    print(f"\n--- Monthly Breakdown ---")
    print(by_month[['trades','wins','win_rate',
                    'pnl','cumulative']].to_string())
    print(f"\n--- Top 10 Symbols ---")
    print(by_symbol.head(10).to_string())
    print(f"\n--- Bottom 10 Symbols ---")
    print(by_symbol.tail(10).to_string())
    print(f"{'='*60}")
    print(f"Results saved: {OUTPUT_FILE}")


def run_full_backtest(max_symbols=500):
    print(f"\n{'='*60}")
    print(f"ORB BACKTEST — "
          f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Symbols: {max_symbols} | "
          f"60m window: last 60 days")
    print(f"{'='*60}\n")

    universe = pd.read_csv(UNIVERSE_FILE)
    active   = universe[universe['active'] == True]
    symbols  = active['symbol'].tolist()[:max_symbols]

    kite = load_kite_client()
    imap = load_instrument_map()

    all_trades = []
    errors     = 0
    skipped    = 0

    for i, symbol in enumerate(symbols):
        try:
            print(f"[{i+1}/{len(symbols)}] {symbol}", end=" ... ")

            daily_df = fetch_daily_kite(
                symbol, kite=kite, instrument_map=imap
            )
            df_60m   = fetch_intraday_60m(
                symbol, kite=kite, instrument_map=imap
            )

            if df_60m.empty or len(df_60m) < 10:
                print("⏭️  Skipped")
                skipped += 1
                continue

            trades = run_orb_backtest_on_symbol(
                symbol, daily_df, df_60m
            )

            if trades:
                all_trades.extend(trades)
                wins   = sum(1 for t in trades
                             if t['r_multiple'] > 0)
                losses = len(trades) - wins
                pnl    = sum(t['pnl_rupees'] for t in trades)
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
        help="Symbols to backtest (default 500)"
    )
    args = parser.parse_args()
    run_full_backtest(max_symbols=args.symbols)