import pandas as pd
import os

NSE_FILE = "data/universe/nifty500_nse.csv"
OUTPUT_FILE = "data/universe/nifty500.csv"

def build_universe(nse_file):
    df = pd.read_csv(nse_file)

    universe = pd.DataFrame()
    universe["symbol"]    = df["Symbol"].str.strip()
    universe["yf_symbol"] = universe["symbol"] + ".NS"
    universe["exchange"]  = "NSE"
    universe["sector"]    = df["Industry"].str.strip()
    universe["notes"]     = ""
    universe["active"]    = True

    universe.to_csv(OUTPUT_FILE, index=False)

    print(f"Universe file built: {OUTPUT_FILE}")
    print(f"Total symbols: {len(universe)}")
    print("\nFirst 5 rows:")
    print(universe.head())
    print("\nSectors found:")
    print(universe["sector"].value_counts())

if __name__ == "__main__":
    if not os.path.exists(NSE_FILE):
        print(f"ERROR: Could not find {NSE_FILE}")
        print("Please place the NSE CSV at: " + NSE_FILE)
    else:
        build_universe(NSE_FILE)