import os
import sys
import pandas as pd
sys.path.append(".")

from scripts.data_fetch.fetch_daily import fetch_daily_kite, load_daily
from scripts.utils.indicators import resample_ohlcv
from scripts.utils.config import RAW_WEEKLY_DIR

def fetch_weekly(symbol, kite=None, instrument_map=None, force_refresh=False):
    """
    Resamples daily data to weekly OHLCV.
    Loads from disk if already fetched, unless force_refresh=True.
    """
    out_path = os.path.join(RAW_WEEKLY_DIR, f"{symbol}_weekly.csv")

    # Load or fetch daily first
    try:
        if force_refresh:
            raise FileNotFoundError
        daily = load_daily(symbol)
    except FileNotFoundError:
        daily = fetch_daily_kite(symbol, kite=kite, instrument_map=instrument_map)

    weekly = resample_ohlcv(daily, rule="W")
    os.makedirs(RAW_WEEKLY_DIR, exist_ok=True)
    weekly.to_csv(out_path)
    return weekly

def load_weekly(symbol):
    """Loads already-computed weekly data from disk."""
    path = os.path.join(RAW_WEEKLY_DIR, f"{symbol}_weekly.csv")
    if not os.path.exists(path):
        raise FileNotFoundError(f"No weekly data for {symbol}. Run fetch first.")
    df = pd.read_csv(path, index_col="datetime", parse_dates=True)
    return df

if __name__ == "__main__":
    print("Testing weekly fetch for RELIANCE...")
    df = fetch_weekly("RELIANCE")
    print(f"Rows fetched: {len(df)}")
    print(df.tail(3))