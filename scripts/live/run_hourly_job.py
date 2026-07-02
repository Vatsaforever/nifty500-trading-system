import sys
import os
import pandas as pd
from datetime import datetime
sys.path.append(".")

from scripts.data_fetch.kite_auth import load_kite_client
from scripts.data_fetch.fetch_daily import load_instrument_map
from scripts.data_fetch.fetch_intraday_60m import fetch_intraday_60m
from scripts.signals.signal_engine_60m import (
    prepare_60m_indicators, scan_for_signal
)
from scripts.signals.entry_update_logic import (
    load_active_signal, create_initial_signal,
    process_new_candle, clear_active_signal
)
from scripts.signals.exit_logic import check_exit_conditions
from scripts.sheets.sheets_writer import (
    write_signal_event, write_trade_open,
    write_trade_exit, write_ema_exit_alert,
    get_risk_amount, send_buy_notification,
    get_sheet_client
)
from scripts.live.kite_order_sync import sync_pending_trades
from scripts.utils.config import WATCHLIST_DIR


def load_latest_watchlist():
    if not os.path.exists(WATCHLIST_DIR):
        return None
    files = sorted([
        f for f in os.listdir(WATCHLIST_DIR)
        if f.startswith("watchlist_") and f.endswith(".csv")
    ])
    if not files:
        return None
    latest = os.path.join(WATCHLIST_DIR, files[-1])
    print(f"  Loaded watchlist: {latest}")
    return pd.read_csv(latest)


def is_market_hours():
    now     = datetime.now()
    weekday = now.weekday()
    if weekday > 4:
        return False
    market_open  = now.replace(hour=9,  minute=15, second=0)
    market_close = now.replace(hour=15, minute=30, second=0)
    return market_open <= now <= market_close


def run_hourly_scan():
    print(f"\n{'='*60}")
    print(f"HOURLY SCAN — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")

    if not is_market_hours():
        print("Outside market hours — skipping scan.")
        return

    kite = load_kite_client()
 # --- Step 1: Pre-fetch 60m data for pending symbols ---
    # so gap-up check has data available during sync
    print("Syncing pending trades with Kite orders...")
    from scripts.sheets.sheets_writer import get_sheet_client
    from scripts.data_fetch.fetch_intraday_60m import fetch_intraday_60m
    from scripts.signals.signal_engine_60m import prepare_60m_indicators

    trades_ws      = get_sheet_client("Trades")
    trade_records  = trades_ws.get_all_records()
    pending_symbols = [
        r["symbol"] for r in trade_records
        if r["status"] == "PENDING"
    ]

    df_60m_map = {}
    if pending_symbols:
        imap_early = load_instrument_map()
        for psym in pending_symbols:
            try:
                df = fetch_intraday_60m(psym, kite=kite,
                                         instrument_map=imap_early)
                df_60m_map[psym] = prepare_60m_indicators(df)
            except Exception:
                pass

    newly_confirmed = sync_pending_trades(kite, df_60m_map=df_60m_map)
    print()

    wl_df = load_latest_watchlist()
    if wl_df is None or len(wl_df) == 0:
        print("No watchlist found — run the weekly job first.")
        return

    print(f"Watchlist symbols: {len(wl_df)}\n")

    imap        = load_instrument_map()
    risk_amount = get_risk_amount()
    sector_map  = wl_df.set_index("symbol")["sector"].to_dict()

    print(f"Risk amount per trade: ₹{risk_amount:,.2f}\n")

    for _, row in wl_df.iterrows():
        symbol = row["symbol"]
        sector = sector_map.get(symbol, "")

        try:
            print(f"[{symbol}]")

            df_60m = fetch_intraday_60m(
                symbol, kite=kite, instrument_map=imap
            )
            df_60m = prepare_60m_indicators(df_60m)
            active = load_active_signal(symbol)

            # ---------------------------------------------------
            # CASE 1: No active signal — scan for ENTRY_INITIAL
            # ---------------------------------------------------
            if active is None:
                signal = scan_for_signal(
                    df_60m, risk_amount, symbol=symbol
                )
                if signal:
                    create_initial_signal(symbol, signal)
                    signal["event_type"] = "ENTRY_INITIAL"
                    write_signal_event(signal, sector=sector)
                    print(f"  📋 ENTRY_INITIAL — "
                          f"Entry: ₹{signal['entry']} | "
                          f"SL: ₹{signal['sl']} | "
                          f"TP: ₹{signal['tp']}\n"
                          f"  👉 Place a SL-M BUY order in Zerodha "
                          f"for {signal['quantity']} shares "
                          f"of {symbol} "
                          f"with trigger price ₹{signal['entry']}")
                else:
                    print(f"  No signal.")
                continue

            # ---------------------------------------------------
            # CASE 2: Active signal — check BUY or ENTRY_UPDATED
            # ---------------------------------------------------
            if not active["entry_triggered"]:
                latest_candle  = df_60m.iloc[-2]
                updated, event = process_new_candle(
                    symbol, latest_candle, df_60m
                )

                if event == "BUY":
                    write_trade_open({
                        "symbol":      symbol,
                        "entry":       active["active_entry"],
                        "sl":          active["active_sl"],
                        "tp":          active["active_tp"],
                        "quantity":    active["active_quantity"],
                        "risk_amount": risk_amount
                    }, sector=sector)
                    send_buy_notification(
                        symbol=symbol,
                        entry=active["active_entry"],
                        sl=active["active_sl"],
                        tp=active["active_tp"],
                        quantity=active["active_quantity"],
                        risk_amount=risk_amount
                    )
                    clear_active_signal(symbol)

                elif event == "ENTRY_UPDATED":
                    updated["event_type"]   = "ENTRY_UPDATED"
                    updated["old_entry"]    = updated.get("_old_entry")
                    updated["new_entry"]    = updated["active_entry"]
                    updated["old_sl"]       = updated.get("_old_sl")
                    updated["new_sl"]       = updated["active_sl"]
                    updated["new_tp"]       = updated["active_tp"]
                    updated["new_quantity"] = updated["active_quantity"]
                    write_signal_event(updated, sector=sector)
                    print(f"  🔄 ENTRY_UPDATED — "
                          f"New Entry: ₹{updated['active_entry']}\n"
                          f"  👉 Modify your Zerodha order trigger "
                          f"price to ₹{updated['active_entry']}")
                else:
                    print(f"  ⏳ Waiting — "
                          f"entry: ₹{active['active_entry']}")
                continue

            # ---------------------------------------------------
            # CASE 3: Entry triggered — monitor if confirmed OPEN
            # ---------------------------------------------------
            trades_ws = get_sheet_client("Trades")
            records   = trades_ws.get_all_records()

            open_trade = next(
                (r for r in records
                 if r["symbol"] == symbol
                 and r["status"] == "OPEN"),
                None
            )

            if open_trade is None:
                skipped = next(
                    (r for r in records
                     if r["symbol"] == symbol
                     and r["status"] == "SKIPPED"),
                    None
                )
                if skipped:
                    print(f"  ⏭️  Trade skipped — clearing signal.")
                    clear_active_signal(symbol)
                else:
                    print(f"  ⏳ BUY triggered — "
                          f"waiting for Kite order confirmation.")
                continue

            # Confirmed OPEN — check exits
            # Use actual fill price if available
            actual_entry = open_trade.get("actual_entry_price")
            entry_price  = float(actual_entry) \
                if actual_entry else float(open_trade["entry_price"])

            latest_candle = df_60m.iloc[-2]
            live_trade    = {
                "symbol":   symbol,
                "entry":    entry_price,
                "sl":       float(open_trade["sl"]),
                "tp":       float(open_trade["tp"]),
                "quantity": int(open_trade["quantity"])
            }

            event, details = check_exit_conditions(
                live_trade, latest_candle, df_60m
            )

            if event == "EMA_EXIT":
                write_ema_exit_alert(symbol)
                print(f"  ⚠️  EMA_EXIT alert — consider exiting.")

            elif event in ("TP_HIT", "SL_HIT"):
                write_trade_exit(symbol, details)
                clear_active_signal(symbol)
                icon = "✅" if event == "TP_HIT" else "❌"
                print(f"  {icon} {event} — "
                      f"Exit: ₹{details['exit_price']} | "
                      f"P&L: ₹{details['pnl_rupees']}\n"
                      f"  👉 Close your Zerodha position in {symbol}")
            else:
                print(f"  📊 Live — "
                      f"Entry: ₹{entry_price} | "
                      f"SL: ₹{live_trade['sl']} | "
                      f"TP: ₹{live_trade['tp']}")

        except Exception as e:
            import traceback
            print(f"  ERROR — {e}")
            traceback.print_exc()
            continue

    print(f"\n{'='*60}")
    print(f"HOURLY SCAN COMPLETE")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    run_hourly_scan()