import sys
import os
import pandas as pd
from datetime import datetime
sys.path.append(".")

from scripts.data_fetch.kite_auth import load_kite_client
from scripts.data_fetch.fetch_daily import fetch_daily_kite, load_instrument_map
from scripts.data_fetch.fetch_weekly import fetch_weekly
from scripts.filters.weekly_trend_filter import is_weekly_uptrend
from scripts.filters.daily_oversold_filter import is_daily_oversold_at_support
from scripts.sheets.sheets_writer import write_signal_event
from scripts.utils.config import (
    UNIVERSE_FILE,
    WATCHLIST_DIR
)


def run_weekly_scan():
    """
    Full weekly scan across the Nifty 500 universe.
    1. Load universe
    2. Fetch daily + weekly data for each symbol
    3. Apply weekly trend filter
    4. Apply daily oversold/support filter
    5. Log WL events to Signals sheet
    6. Save watchlist snapshot to disk
    """
    print(f"\n{'='*60}")
    print(f"WEEKLY SCAN — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")

    # Load universe and instrument map
    universe     = pd.read_csv(UNIVERSE_FILE)
    active       = universe[universe["active"] == True]
    symbols      = active["symbol"].tolist()
    sector_map   = active.set_index("symbol")["sector"].to_dict()

    # Clear previous WL entries from Signals sheet
    # (keeps ENTRY_INITIAL and ENTRY_UPDATED rows intact)
    print("Clearing previous WL entries from Signals sheet...")
    try:
        from scripts.sheets.sheets_writer import get_sheet_client
        ws      = get_sheet_client("Signals")
        records = ws.get_all_values()
        rows_to_delete = []
        for idx, row in enumerate(records):
            if idx == 0:
                continue   # skip header
            if len(row) > 1 and row[1] == "WL":
                rows_to_delete.append(idx + 1)   # 1-indexed

        # Delete in reverse order so row numbers stay valid
        for row_num in reversed(rows_to_delete):
            ws.delete_rows(row_num)

        print(f"  Cleared {len(rows_to_delete)} old WL entries.")
    except Exception as e:
        print(f"  Warning: could not clear old WL entries: {e}")

    # Load company names from instrument map
    from scripts.utils.config import INSTRUMENT_MAP_FILE
    imap_df      = pd.read_csv(INSTRUMENT_MAP_FILE)
    company_map  = imap_df.set_index("symbol")["company_name"].to_dict()

    print(f"Universe: {len(symbols)} active symbols\n")

    # Load Kite client and instrument map
    kite         = load_kite_client()
    imap         = load_instrument_map()

    watchlist    = []
    passed_weekly = 0
    passed_both  = 0
    errors       = 0

    for i, symbol in enumerate(symbols):
        try:
            print(f"[{i+1}/{len(symbols)}] {symbol}", end=" ... ")

            # Fetch data
            daily_df  = fetch_daily_kite(symbol, kite=kite,
                                          instrument_map=imap)
            weekly_df = fetch_weekly(symbol)

            # Weekly trend filter
            weekly_pass, weekly_details = is_weekly_uptrend(weekly_df)
            if not weekly_pass:
                print(f"❌ Weekly ({weekly_details['reason']})")
                continue

            passed_weekly += 1

            # Daily oversold/support filter
            daily_pass, daily_details = is_daily_oversold_at_support(daily_df)
            if not daily_pass:
                print(f"⚠️  Daily ({daily_details['reason']})")
                continue

            passed_both += 1
            sector = sector_map.get(symbol, "")

            # Build WL event
            wl_event = {
                "event_type":         "WL",
                "symbol":             symbol,
                "company_name":       company_map.get(symbol, ""),
                "weekly_close":       weekly_details.get("weekly_close"),
                "weekly_ema20":       weekly_details.get("weekly_ema20"),
                "rsi5":               daily_details.get("rsi5"),
                "support_zone_price": daily_details.get("support_zone_price"),
                "notes":              ""
            }

            # Log to Signals sheet
            write_signal_event(wl_event, sector=sector)

            # Add to watchlist
            watchlist.append({
                "symbol":            symbol,
                "sector":            sector,
                "weekly_close":      weekly_details.get("weekly_close"),
                "weekly_ema20":      weekly_details.get("weekly_ema20"),
                "rsi5":              daily_details.get("rsi5"),
                "support_zone_price": daily_details.get("support_zone_price"),
                "scan_date":         datetime.now().strftime("%Y-%m-%d")
            })

            print(f"✅ WL — RSI: {daily_details.get('rsi5')} | "
                  f"Support: ₹{daily_details.get('support_zone_price')}")

        except Exception as e:
            print(f"ERROR — {e}")
            errors += 1
            continue

    # Save watchlist snapshot
    os.makedirs(WATCHLIST_DIR, exist_ok=True)
    date_str      = datetime.now().strftime("%Y-%m-%d")
    watchlist_path = os.path.join(WATCHLIST_DIR,
                                   f"watchlist_{date_str}.csv")
    wl_df = pd.DataFrame(watchlist)
    wl_df.to_csv(watchlist_path, index=False)

    # Summary
    print(f"\n{'='*60}")
    print(f"WEEKLY SCAN COMPLETE")
    print(f"  Total scanned:      {len(symbols)}")
    print(f"  Passed weekly trend: {passed_weekly}")
    print(f"  Passed both filters: {passed_both} → added to WL")
    print(f"  Errors:              {errors}")
    print(f"  Watchlist saved:     {watchlist_path}")
    print(f"{'='*60}\n")

    # Alert for any signals dropped from new WL
    print("\nChecking for dropped signals...")
    from scripts.live.kite_order_sync import cancel_dropped_signals
    new_wl_symbols = [w["symbol"] for w in watchlist]
    cancel_dropped_signals(new_wl_symbols)

    return watchlist


if __name__ == "__main__":
    try:
        watchlist = run_weekly_scan()
    except Exception as e:
        import traceback
        print(f"ERROR: {e}")
        traceback.print_exc()