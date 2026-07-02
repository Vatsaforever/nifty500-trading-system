import pandas as pd
import sys
import os
sys.path.append(".")

from scripts.data_fetch.kite_auth import load_kite_client

UNIVERSE_FILE = "data/universe/nifty500.csv"
OUTPUT_FILE = "data/universe/kite_instrument_map.csv"

def build_instrument_map():
    """
    Fetches the full NSE instrument list from Kite, filters to only
    the symbols in our Nifty 500 universe, and saves the token map.
    """
    # Load our universe
    universe = pd.read_csv(UNIVERSE_FILE)
    our_symbols = set(universe["symbol"].tolist())

    # Fetch all NSE instruments from Kite
    print("Fetching instrument list from Kite...")
    kite = load_kite_client()
    instruments = kite.instruments("NSE")
    instruments_df = pd.DataFrame(instruments)

    # Filter to EQ (equity) segment only — excludes ETFs, derivatives etc.
    instruments_df = instruments_df[instruments_df["segment"] == "NSE"]
    instruments_df = instruments_df[instruments_df["instrument_type"] == "EQ"]

    # Filter to only our Nifty 500 symbols
    matched = instruments_df[instruments_df["tradingsymbol"].isin(our_symbols)].copy()
    matched = matched[["tradingsymbol", "instrument_token", "name", "last_price"]].copy()
    matched.columns = ["symbol", "instrument_token", "company_name", "last_price"]
    matched = matched.reset_index(drop=True)

    # Check for any unmatched symbols
    matched_symbols = set(matched["symbol"].tolist())
    unmatched = our_symbols - matched_symbols
    if unmatched:
        print(f"\nWARNING: {len(unmatched)} symbols in universe not found in Kite:")
        for s in sorted(unmatched):
            print(f"  - {s}")
    else:
        print("\nAll 500 symbols matched successfully.")

    matched.to_csv(OUTPUT_FILE, index=False)
    print(f"\nInstrument map saved: {OUTPUT_FILE}")
    print(f"Total matched: {len(matched)}")
    print("\nFirst 5 rows:")
    print(matched.head())

if __name__ == "__main__":
    build_instrument_map()