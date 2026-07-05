import sys
import os
import math
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
sys.path.append(".")

from scripts.data_fetch.kite_auth import load_kite_client
from scripts.data_fetch.fetch_daily import fetch_daily_kite, load_instrument_map
from scripts.utils.indicators import ema
from scripts.utils.config import UNIVERSE_FILE, RISK_PCT, TP_MULTIPLE

# --- Config ---
BACKTEST_CAPITAL   = 1_000_000
BACKTEST_RISK      = BACKTEST_CAPITAL * RISK_PCT
MAX_POSITION_VALUE = 100_000
OUTPUT_FILE        = "data/processed/backtest_52wk.csv"

# 52-Week High parameters
VOLUME_MULTIPLIER  = 1.5     # breakout day volume > 1.5x 20-day avg
MIN_PRICE          = 50      # exclude stocks below ₹50
LOOKBACK_DAYS      = 252     # trading days in a year (~252)
BREAKOUT_BUFFER    = 0.002   # 0.2% above 52-week high to confirm breakout
MAX_HOLD_DAYS      = 15      # maximum holding period
TP_MULT            = 2.0     # wider TP for momentum — 2R instead of 1.5R


def get_weekly_ema20(daily_df, date):
    """Returns weekly close and EMA20 for a given date."""
    daily_to_date = daily_df[daily_df.index.date <= date].copy()
    if len(daily_to_date) < 30:
        return None, None
    weekly     = daily_to_date["close"].resample("W").last()
    weekly_ema = weekly.ewm(span=20, adjust=False).mean()
    return float(weekly.iloc[-1]), float(weekly_ema.iloc[-1])


def run_52wk_backtest_on_symbol(symbol, daily_df):
    """
    Runs 52-Week High Breakout backtest on a single symbol.
    Uses daily data only — 5 years of history.
    Returns list of completed trades.
    """
    trades       = []
    active_trade = None

    daily_df = daily_df.copy()
    daily_df.index = daily_df.index.tz_localize(None) \
        if daily_df.index.tzinfo else daily_df.index
    daily_df = daily_df.sort_index()

    for i in range(LOOKBACK_DAYS + 20, len(daily_df)):
        today      = daily_df.iloc[i]
        today_date = today.name.date()

        # -------------------------------------------------------
        # Check exit on active trade first
        # -------------------------------------------------------
        if active_trade is not None:
            days_held = (pd.Timestamp(today_date) -
                         pd.Timestamp(
                             active_trade['entry_date']
                         )).days

            candle_high = float(today['high'])
            candle_low  = float(today['low'])
            entry       = active_trade['entry']
            sl          = active_trade['sl']
            tp          = active_trade['tp']
            qty         = active_trade['quantity']

            # SL hit (priority)
            if candle_low <= sl:
                pnl = round((sl - entry) * qty, 2)
                trades.append({
                    **active_trade,
                    'exit_date':    str(today_date),
                    'exit_price':   sl,
                    'exit_reason':  'SL_HIT',
                    'pnl_rupees':   pnl,
                    'r_multiple':   -1.0,
                    'holding_days': days_held
                })
                active_trade = None
                continue

            # TP hit
            if candle_high >= tp:
                pnl = round((tp - entry) * qty, 2)
                trades.append({
                    **active_trade,
                    'exit_date':    str(today_date),
                    'exit_price':   tp,
                    'exit_reason':  'TP_HIT',
                    'pnl_rupees':   pnl,
                    'r_multiple':   round(TP_MULT, 2),
                    'holding_days': days_held
                })
                active_trade = None
                continue

            # Max hold days exit
            if days_held >= MAX_HOLD_DAYS:
                exit_price = float(today['close'])
                pnl        = round((exit_price - entry) * qty, 2)
                r          = round(
                    (exit_price - entry) /
                    (entry - sl), 2
                ) if (entry - sl) > 0 else 0
                trades.append({
                    **active_trade,
                    'exit_date':    str(today_date),
                    'exit_price':   exit_price,
                    'exit_reason':  'TIME_EXIT',
                    'pnl_rupees':   pnl,
                    'r_multiple':   r,
                    'holding_days': days_held
                })
                active_trade = None
                continue

            # Still holding
            continue

        # -------------------------------------------------------
        # Check for new 52-week high breakout signal
        # -------------------------------------------------------
        today_close  = float(today['close'])
        today_high   = float(today['high'])
        today_low    = float(today['low'])
        today_open   = float(today['open'])
        today_volume = float(today['volume'])

        # Price filter
        if today_close < MIN_PRICE:
            continue

        # Get 52-week high (prior 252 trading days, not including today)
        prior        = daily_df.iloc[i - LOOKBACK_DAYS:i]
        high_52wk    = float(prior['high'].max())
        avg_volume   = float(prior['volume'].iloc[-20:].mean())

        # Breakout: today's close must exceed 52-week high by buffer
        breakout_level = high_52wk * (1 + BREAKOUT_BUFFER)
        if today_close < breakout_level:
            continue

        # Must be a bullish candle
        if today_close <= today_open:
            continue

        # Volume filter
        if today_volume < avg_volume * VOLUME_MULTIPLIER:
            continue

        # Weekly trend filter
        weekly_close, weekly_ema20 = get_weekly_ema20(
            daily_df, today_date
        )
        if weekly_close is None or weekly_close <= weekly_ema20:
            continue

        # Compute trade levels
        # Entry: next day open (we buy on the day after breakout)
        # Use today's close as proxy for next day open in backtest
        entry = round(today_close, 2)
        sl    = round(high_52wk, 2)   # SL at the old 52-week high
        rps   = entry - sl

        if rps <= 0:
            continue

        qty_risk = math.floor(BACKTEST_RISK / rps)
        qty_cap  = math.floor(MAX_POSITION_VALUE / entry)
        qty      = min(qty_risk, qty_cap)

        if qty == 0:
            continue

        tp  = round(entry + TP_MULT * rps, 2)
        pos = round(entry * qty, 2)

        active_trade = {
            'symbol':          symbol,
            'entry_date':      str(today_date),
            'high_52wk':       round(high_52wk, 2),
            'breakout_level':  round(breakout_level, 2),
            'entry':           entry,
            'sl':              sl,
            'tp':              tp,
            'quantity':        qty,
            'position_value':  pos,
            'risk_amount':     round(rps * qty, 2),
            'volume_ratio':    round(
                today_volume / avg_volume, 2
            )
        }

    return trades


def print_summary(df):
    total      = len(df)
    wins       = len(df[df['r_multiple'] > 0])
    losses     = len(df[df['r_multiple'] <= 0])
    win_rate   = round(wins / total * 100, 1) if total > 0 else 0
    avg_r      = round(df['r_multiple'].mean(), 3)
    total_pnl  = round(df['pnl_rupees'].sum(), 2)
    charges    = total * 75
    net_pnl    = total_pnl - charges
    expectancy = round(net_pnl / total, 2) if total > 0 else 0

    gross_win  = df[df['pnl_rupees'] > 0]['pnl_rupees'].sum()
    gross_loss = abs(
        df[df['pnl_rupees'] < 0]['pnl_rupees'].sum()
    )
    pf = round(gross_win / gross_loss, 2) if gross_loss > 0 else 0

    df_s       = df.sort_values('exit_date')
    cum_pnl    = df_s['pnl_rupees'].cumsum()
    roll_max   = cum_pnl.cummax()
    drawdown   = cum_pnl - roll_max
    max_dd     = round(drawdown.min(), 2)
    max_dd_pct = round(max_dd / BACKTEST_CAPITAL * 100, 2)

    avg_hold   = round(df['holding_days'].mean(), 1)
    final_cap  = round(BACKTEST_CAPITAL + net_pnl, 2)
    return_pct = round(net_pnl / BACKTEST_CAPITAL * 100, 2)

    by_reason  = df.groupby('exit_reason').agg(
        count=('pnl_rupees', 'count'),
        total_pnl=('pnl_rupees', 'sum'),
        avg_r=('r_multiple', 'mean')
    ).round(2)

    df['year'] = pd.to_datetime(df['exit_date']).dt.year
    by_year    = df.groupby('year').agg(
        trades=('pnl_rupees', 'count'),
        wins=('r_multiple', lambda x: (x > 0).sum()),
        pnl=('pnl_rupees', 'sum')
    )
    by_year['win_rate']   = (
        by_year['wins'] / by_year['trades'] * 100
    ).round(1)
    by_year['net_pnl']    = (
        by_year['pnl'] - by_year['trades'] * 75
    )
    by_year['cumulative'] = by_year['net_pnl'].cumsum().round(0)

    by_symbol = df.groupby('symbol').agg(
        trades=('pnl_rupees', 'count'),
        pnl=('pnl_rupees', 'sum'),
        win_rate=('r_multiple', lambda x:
                  round((x > 0).mean() * 100, 1))
    ).sort_values('pnl', ascending=False)

    print(f"\n{'='*60}")
    print(f"52-WEEK HIGH BREAKOUT BACKTEST RESULTS")
    print(f"Capital: ₹{BACKTEST_CAPITAL:,} | "
          f"Risk/trade: ₹{BACKTEST_RISK:,.0f} | "
          f"TP: {TP_MULT}R | Max hold: {MAX_HOLD_DAYS} days")
    print(f"{'='*60}")
    print(f"Total Trades:     {total}")
    print(f"Wins:             {wins}")
    print(f"Losses:           {losses}")
    print(f"Win Rate:         {win_rate}%")
    print(f"Average R:        {avg_r}")
    print(f"Profit Factor:    {pf}")
    print(f"Gross P&L:        ₹{total_pnl:,.2f}")
    print(f"Charges (~₹75):   ₹{charges:,.0f}")
    print(f"Net P&L:          ₹{net_pnl:,.2f}")
    print(f"Net Return:       {return_pct}%")
    print(f"Final Capital:    ₹{final_cap:,.0f}")
    print(f"Expectancy:       ₹{expectancy:,.2f} per trade (net)")
    print(f"Max Drawdown:     ₹{max_dd:,.2f} ({max_dd_pct}%)")
    print(f"Avg Holding:      {avg_hold} days")
    print(f"\n--- By Exit Reason ---")
    print(by_reason.to_string())
    print(f"\n--- By Year ---")
    print(by_year[['trades', 'wins', 'win_rate',
                   'pnl', 'net_pnl', 'cumulative']].to_string())
    print(f"\n--- Top 10 Symbols ---")
    print(by_symbol.head(10).to_string())
    print(f"\n--- Bottom 10 Symbols ---")
    print(by_symbol.tail(10).to_string())
    print(f"{'='*60}")
    print(f"Results saved: {OUTPUT_FILE}")


def run_full_backtest(max_symbols=500):
    print(f"\n{'='*60}")
    print(f"52-WEEK HIGH BACKTEST — "
          f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Symbols: {max_symbols} | Data: 5 years daily")
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

            if len(daily_df) < LOOKBACK_DAYS + 20:
                print("⏭️  Skipped (insufficient history)")
                skipped += 1
                continue

            trades = run_52wk_backtest_on_symbol(symbol, daily_df)

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