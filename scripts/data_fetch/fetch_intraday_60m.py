import os
import sys
import pandas as pd
from datetime import datetime, timedelta
sys.path.append(".")

from scripts.data_fetch.kite_auth import load_kite_client
from scripts.data_fetch.fetch_daily import load_instrument_map
from scripts.utils.config import RAW_60M_DIR, INTRADAY_60M_DAYS

def fetch_intraday_60m(symbol, kite=None, instrument_map=None):
    """Fetches 60-minute OHLCV from Kite for a single symbol."""
    if kite is None:
        kite = load_kite_client()
    if instrument_map is None:
        instrument_map = load_instrument_map()

    token = int(instrument_map.loc[symbol, "instrument_token"])
    to_date = datetime.now().date()
    from_date = to_date - timedelta(days=INTRADAY_60M_DAYS)

    candles = kite.historical_data(
        instrument_token=token,
        from_date=from_date,
        to_date=to_date,
        interval="60minute"
    )

    df = pd.DataFrame(candles)
    df = df.rename(columns={"date": "datetime"})
    df = df.set_index("datetime")
    df.columns = [c.lower() for c in df.columns]
    df = df[["open", "high", "low", "close", "volume"]]

    # Filter to market hours only (9:15am - 3:30pm IST)
    df = df.between_time("09:15", "15:30")

    os.makedirs(RAW_60M_DIR, exist_ok=True)
    out_path = os.path.join(RAW_60M_DIR, f"{symbol}_60m.csv")
    df.to_csv(out_path)
    return df

def load_60m(symbol):
    """Loads already-fetched 60m data from disk."""
    path = os.path.join(RAW_60M_DIR, f"{symbol}_60m.csv")
    if not os.path.exists(path):
        raise FileNotFoundError(f"No 60m data for {symbol}. Run fetch first.")
    df = pd.read_csv(path, index_col="datetime", parse_dates=True)
    return df

if __name__ == "__main__":
    print("Testing 60m fetch for RELIANCE...")
    kite = load_kite_client()
    imap = load_instrument_map()
    df = fetch_intraday_60m("RELIANCE", kite=kite, instrument_map=imap)
    print(f"Rows fetched: {len(df)}")
    print(df.tail(3))