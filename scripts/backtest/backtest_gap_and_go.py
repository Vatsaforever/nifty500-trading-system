import sys
import os
import math
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
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
OUTPUT_FILE         = "data/processed/backtest_gap_and_go.csv"

# Gap and Go parameters
MIN_GAP_PCT         = 0.01    # 1.0% minimum gap
MAX_GAP_PCT         = 0.05    # 5.0% maximum gap
VOLUME_MULTIPLIER   = 1.5     # gap day volume > 1.5x 20-day avg
MIN_PRICE           = 50      # exclude stocks below ₹50
ENTRY_BUFFER_PCT    = 0.001   # 0.1% buffer above first candle high
MAX_HOLD_DAYS       = 3       # maximum holding period in days


def get_weekly_ema20(daily_df, date):
    """Returns weekly close and EMA20 for a given date."""
    daily_to_date = daily_df[daily_df.index.date <= date].copy()
    if len(daily_to_date) < 30:
        return None, None
    weekly      = daily_to_date["close"].resample("W").last()
    weekly_ema  = weekly.ewm(span=20, adjust=False).mean()
    return float(weekly.iloc[-1]), float(weekly_ema.iloc[-1])


def get_avg_volume(daily_df, date, period=20):
    """Returns 20-day average volume up to but not including date."""
    prior = daily_df[daily_df.index.date < date]
    if len(prior) < period:
        return None
    return float(prior["volume"].iloc[-period:].mean())


def run_gap_and_go_on_symbol(symbol, daily_df, df_60m):
    """
    Runs Gap and Go backtest on a single symbol.
    Returns list of completed trades.
    """
    trades = []

    daily_df = daily_df.copy()
    daily_df.index = daily_df.index.tz_localize(None) \
        if daily_df.index.tzinfo else daily_df.index

    df = df_60m.copy()
    df.index = df.index.tz_localize(None) \
        if df.index.tzinfo else df.index

    df['date'] = df.index.date
    dates      = sorted(df['date'].unique())

    active_trade = None

    for trade_date in dates:
        day_candles = df[df['date'] == trade_date].sort_index()

        if len(day_candles) < 1:
            continue

        # -------------------------------------------------------
        # Check exit on active trade first
        # -------------------------------------------------------
        if active_trade is not None:
            days_held = (pd.Timestamp(trade_date) -
                         pd.Timestamp(active_trade['entry_date'])).days

            for _, candle in day_candles.iterrows():
                candle_high = float(candle['high'])
                candle_low  = float(candle['low'])
                entry       = active_trade['entry']
                sl          = active_trade['sl']
                tp          = active_trade['tp']
                qty         = active_trade['quantity']

                # SL hit (priority)
                if candle_low <= sl:
                    pnl = round((sl - entry) * qty, 2)
                    trades.append({
                        **active_trade,
                        'exit_date':    str(trade_date),
                        'exit_time':    str(candle.name),
                        'exit_price':   sl,
                        'exit_reason':  'SL_HIT',
                        'pnl_rupees':   pnl,
                        'r_multiple':   -1.0,
                        'holding_days': days_held
                    })
                    active_trade = None
                    break

                # TP hit
                if candle_high >= tp:
                    pnl = round((tp - entry) * qty, 2)
                    r   = round(TP_MULTIPLE, 2)
                    trades.append({
                        **active_trade,
                        'exit_date':    str(trade_date),
                        'exit_time':    str(candle.name),
                        'exit_price':   tp,
                        'exit_reason':  'TP_HIT',
                        'pnl_rupees':   pnl,
                        'r_multiple':   r,
                        'holding_days': days_held
                    })
                    active_trade = None
                    break

            # Max hold days exit
            if active_trade is not None and days_held >= MAX_HOLD_DAYS:
                last_candle = day_candles.iloc[-1]
                exit_price  = float(last_candle['close'])
                pnl         = round(
                    (exit_price - active_trade['entry']) *
                    active_trade['quantity'], 2
                )
                r = round(
                    (exit_price - active_trade['entry']) /
                    (active_trade['entry'] - active_trade['sl']), 2
                ) if (active_trade['entry'] - active_trade['sl']) > 0 else 0
                trades.append({
                    **active_trade,
                    'exit_date':    str(trade_date),
                    'exit_time':    str(last_candle.name),
                    'exit_price':   exit_price,
                    'exit_reason':  'TIME_EXIT',
                    'pnl_rupees':   pnl,
                    'r_multiple':   r,
                    'holding_days': days_held
                })
                active_trade = None

            # Skip signal check if trade still active
            if active_trade is not None:
                continue

        # -------------------------------------------------------
        # Check for new Gap and Go signal on this day
        # -------------------------------------------------------
        if len(day_candles) < 1:
            continue

        first_candle = day_candles.iloc[0]
        candle_open  = float(first_candle['open'])
        candle_close = float(first_candle['close'])
        candle_high  = float(first_candle['high'])
        candle_low   = float(first_candle['low'])
        candle_vol   = float(first_candle['volume'])

        # Need previous day close for gap calculation
        prev_days = daily_df[daily_df.index.date < trade_date]
        if len(prev_days) < 21:
            continue
        prev_close = float(prev_days['close'].iloc[-1])

        # Price filter
        if prev_close < MIN_PRICE:
            continue

        # Gap calculation
        gap_pct = (candle_open - prev_close) / prev_close
        if gap_pct < MIN_GAP_PCT or gap_pct > MAX_GAP_PCT:
            continue

        # Volume filter — use today's first candle volume
        # scaled to full day estimate vs 20-day avg daily volume
        avg_vol = get_avg_volume(daily_df, trade_date, period=20)
        if avg_vol is None:
            continue
        # Estimate full day volume from first candle
        # (first candle typically ~15-20% of daily volume)
        est_day_vol = candle_vol * 5
        if est_day_vol < avg_vol * VOLUME_MULTIPLIER:
            continue

        # Weekly trend filter
        weekly_close, weekly_ema20 = get_weekly_ema20(
            daily_df, trade_date
        )
        if weekly_close is None or weekly_close <= weekly_ema20:
            continue

        # Signal candle: first 60m candle must be bullish
        # and close above the gap level (prev close)
        if candle_close <= candle_open:
            continue   # bearish first candle — no signal
        if candle_close <= prev_close:
            continue   # didn't hold above gap level

        # Compute trade levels
        entry = round(candle_high * (1 + ENTRY_BUFFER_PCT), 2)
        sl    = round(candle_low, 2)
        rps   = entry - sl

        if rps <= 0:
            continue

        qty_risk = math.floor(BACKTEST_RISK / rps)
        qty_cap  = math.floor(MAX_POSITION_VALUE / entry)
        qty      = min(qty_risk, qty_cap)

        if qty == 0:
            continue

        tp  = round(entry + TP_MULTIPLE * rps, 2)
        pos = round(entry * qty, 2)

        active_trade = {
            'symbol':        symbol,
            'entry_date':    str(trade_date),
            'entry_time':    str(first_candle.name),
            'prev_close':    round(prev_close, 2),
            'gap_pct':       round(gap_pct * 100, 2),
            'first_candle_high': round(candle_high, 2),
            'first_candle_low':  round(candle_low, 2),
            'entry':         entry,
            'sl':            sl,
            'tp':            tp,
            'quantity':      qty,
            'position_value': pos,
            'risk_amount':   round(rps * qty, 2)
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
    gross_loss = abs(df[df['pnl_rupees'] < 0]['pnl_rupees'].sum())
    pf         = round(gross_win / gross_loss, 2) \
        if gross_loss > 0 else 0

    df_s       = df.sort_values('exit_time')
    cum_pnl    = df_s['pnl_rupees'].cumsum()
    roll_max   = cum_pnl.cummax()
    drawdown   = cum_pnl - roll_max
    max_dd     = round(drawdown.min(), 2)
    max_dd_pct = round(max_dd / BACKTEST_CAPITAL * 100, 2)

    avg_hold   = round(df['holding_days'].mean(), 1) \
        if 'holding_days' in df.columns else 'N/A'

    by_reason  = df.groupby('exit_reason').agg(
        count=('pnl_rupees', 'count'),
        total_pnl=('pnl_rupees', 'sum'),
        avg_r=('r_multiple', 'mean')
    ).round(2)

    df['month'] = pd.to_datetime(
        df['exit_date']
    ).dt.to_period('M')
    by_month = df.groupby('month').agg(
        trades=('pnl_rupees', 'count'),
        wins=('r_multiple', lambda x: (x > 0).sum()),
        pnl=('pnl_rupees', 'sum')
    )
    by_month['win_rate']   = (
        by_month['wins'] / by_month['trades'] * 100
    ).round(1)
    by_month['net_pnl']    = (
        by_month['pnl'] - by_month['trades'] * 75
    )
    by_month['cumulative'] = by_month['net_pnl'].cumsum().round(0)

    by_symbol = df.groupby('symbol').agg(
        trades=('pnl_rupees', 'count'),
        pnl=('pnl_rupees', 'sum'),
        win_rate=('r_multiple', lambda x:
                  round((x > 0).mean() * 100, 1))
    ).sort_values('pnl', ascending=False)

    # Gap size analysis
    df['gap_bucket'] = pd.cut(
        df['gap_pct'],
        bins=[0, 1.5, 2, 3, 5],
        labels=['1-1.5%', '1.5-2%', '2-3%', '3-5%']
    )
    gap_perf = df.groupby('gap_bucket').agg(
        trades=('pnl_rupees', 'count'),
        win_rate=('r_multiple', lambda x:
                  round((x > 0).mean() * 100, 1)),
        avg_pnl=('pnl_rupees', 'mean')
    ).round(2)

    final_capital = round(BACKTEST_CAPITAL + net_pnl, 2)
    return_pct    = round(net_pnl / BACKTEST_CAPITAL * 100, 2)

    print(f"\n{'='*60}")
    print(f"GAP AND GO BACKTEST RESULTS")
    print(f"Capital: ₹{BACKTEST_CAPITAL:,} | "
          f"Risk/trade: ₹{BACKTEST_RISK:,.0f} | "
          f"Max hold: {MAX_HOLD_DAYS} days")
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
    print(f"Final Capital:    ₹{final_capital:,.0f}")
    print(f"Expectancy:       ₹{expectancy:,.2f} per trade (net)")
    print(f"Max Drawdown:     ₹{max_dd:,.2f} ({max_dd_pct}%)")
    print(f"Avg Holding:      {avg_hold} days")
    print(f"\n--- By Exit Reason ---")
    print(by_reason.to_string())
    print(f"\n--- By Gap Size ---")
    print(gap_perf.to_string())
    print(f"\n--- Monthly Breakdown ---")
    print(by_month[['trades', 'wins', 'win_rate',
                    'pnl', 'net_pnl', 'cumulative']].to_string())
    print(f"\n--- Top 10 Symbols ---")
    print(by_symbol.head(10).to_string())
    print(f"\n--- Bottom 10 Symbols ---")
    print(by_symbol.tail(10).to_string())
    print(f"{'='*60}")
    print(f"Results saved: {OUTPUT_FILE}")


def run_full_backtest(max_symbols=500):
    print(f"\n{'='*60}")
    print(f"GAP AND GO BACKTEST — "
          f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Symbols: {max_symbols} | Window: last 60 days")
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

            trades = run_gap_and_go_on_symbol(
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