import os
import sys
import pandas as pd
from datetime import datetime, timedelta
sys.path.append(".")

from scripts.data_fetch.kite_auth import load_kite_client
from scripts.utils.config import (
    INSTRUMENT_MAP_FILE, RAW_DAILY_DIR, DAILY_LOOKBACK_DAYS
)

def load_instrument_map():
    return pd.read_csv(INSTRUMENT_MAP_FILE).set_index("symbol")

def fetch_daily_kite(symbol, kite=None, instrument_map=None):
    """Fetches daily OHLCV from Kite for a single symbol."""
    if kite is None:
        kite = load_kite_client()
    if instrument_map is None:
        instrument_map = load_instrument_map()

    token = int(instrument_map.loc[symbol, "instrument_token"])
    to_date = datetime.now().date()
    from_date = to_date - timedelta(days=DAILY_LOOKBACK_DAYS)


    candles = kite.historical_data(
        instrument_token=token,
        from_date=from_date,
        to_date=to_date,
        interval="day"
    )

    df = pd.DataFrame(candles)
    df = df.rename(columns={"date": "datetime"})
    df = df.set_index("datetime")
    df.columns = [c.lower() for c in df.columns]
    df = df[["open", "high", "low", "close", "volume"]]

    os.makedirs(RAW_DAILY_DIR, exist_ok=True)
    out_path = os.path.join(RAW_DAILY_DIR, f"{symbol}_daily.csv")
    df.to_csv(out_path)
    return df

def load_daily(symbol):
    """Loads already-fetched daily data from disk."""
    path = os.path.join(RAW_DAILY_DIR, f"{symbol}_daily.csv")
    if not os.path.exists(path):
        raise FileNotFoundError(f"No daily data for {symbol}. Run fetch first.")
    df = pd.read_csv(path, index_col="datetime", parse_dates=True)
    return df

if __name__ == "__main__":
    # Quick test on one symbol
    print("Testing daily fetch for RELIANCE...")
    kite = load_kite_client()
    imap = load_instrument_map()
    df = fetch_daily_kite("RELIANCE", kite=kite, instrument_map=imap)
    print(f"Rows fetched: {len(df)}")
    print(df.tail(3))