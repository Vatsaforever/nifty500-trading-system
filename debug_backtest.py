import sys
import pandas as pd
sys.path.append(".")

from scripts.data_fetch.kite_auth import load_kite_client
from scripts.data_fetch.fetch_daily import fetch_daily_kite, load_instrument_map
from scripts.backtest.backtest import prepare_daily_indicators, is_daily_signal_candle

symbol = "RELIANCE"

kite = load_kite_client()
imap = load_instrument_map()

print(f"Fetching daily data for {symbol}...")
daily_df = fetch_daily_kite(symbol, kite=kite, instrument_map=imap)
print(f"Rows: {len(daily_df)}")

df = prepare_daily_indicators(daily_df)
df.index = df.index.tz_localize(None) if df.index.tzinfo else df.index

print(f"\nSample indicators (last 5 rows):")
print(df[["close","weekly_close","weekly_ema20","rsi5","ema9","atr14"]].tail())

print(f"\nChecking filter conditions across all bars (from row 60)...")
weekly_pass_count  = 0
rsi_pass_count     = 0
support_pass_count = 0
signal_count       = 0

from scripts.filters.daily_oversold_filter import is_daily_oversold_at_support

for i in range(60, len(df)-1):
    candle = df.iloc[i]

    # Weekly trend
    wc  = float(candle["weekly_close"])
    we  = float(candle["weekly_ema20"])
    if pd.isna(we) or wc <= we:
        continue
    weekly_pass_count += 1

    # RSI — check PREVIOUS bar
    if i < 1:
        continue
    prev_rv = float(df["rsi5"].iloc[i-1])
    if pd.isna(prev_rv) or prev_rv >= 30:
        continue
    rsi_pass_count += 1

    # Support — check previous bar's data
    daily_slice = df.iloc[max(0, i-180):i]
    dp, _ = is_daily_oversold_at_support(daily_slice)
    if not dp:
        continue
    support_pass_count += 1

    # Signal candle
    if not is_daily_signal_candle(df, i):
        continue
    signal_count += 1
    print(f"  SIGNAL at {df.index[i].date()} | "
          f"RSI: {prev_rv:.1f} | Close: {candle['close']:.0f}")

print(f"\n--- Filter Funnel ---")
print(f"Total bars checked:      {len(df)-60}")
print(f"Passed weekly trend:     {weekly_pass_count}")
print(f"Passed RSI < 30:         {rsi_pass_count}")
print(f"Passed support zone:     {support_pass_count}")
print(f"Passed signal candle:    {signal_count}")