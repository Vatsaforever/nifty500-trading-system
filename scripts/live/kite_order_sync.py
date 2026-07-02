import sys
import os
from datetime import datetime
sys.path.append(".")


def get_todays_orders(kite):
    """
    Fetches all of today's orders from Kite.
    Returns a dict of {symbol: order_details}.
    For CNC orders, TRIGGER PENDING status means the SL-M
    order is live and waiting for the trigger price to be hit.
    """
    try:
        orders = kite.orders()
    except Exception as e:
        print(f"  ERROR fetching orders from Kite: {e}")
        return {}

    order_map = {}
    for order in orders:
        if order["transaction_type"] != "BUY":
            continue
        # Only care about CNC orders
        if order["product"] != "CNC":
            continue
        symbol = order["tradingsymbol"]
        order_map[symbol] = {
            "status":       order["status"],
            "fill_price":   float(order["average_price"] or 0),
            "order_id":     order["order_id"],
            "quantity":     int(order["quantity"]),
            "placed_at":    order["order_timestamp"],
            "trigger_price": float(order.get("trigger_price") or 0)
        }

    return order_map


def check_gap_up(symbol, active_signal, df_60m):
    """
    Checks if the stock has gapped up above the entry price
    on today's open — meaning the move happened overnight
    and the entry is no longer valid.

    Only checked on the first candle of the day (9:15 AM).
    """
    if df_60m is None or len(df_60m) == 0:
        return False

    now = datetime.now()
    # Only run this check in the first hour of market
    if not (now.hour == 9 and now.minute <= 30):
        return False

    entry       = float(active_signal["active_entry"])
    first_candle = df_60m.iloc[-1]
    candle_open  = float(first_candle["open"])

    if candle_open > entry:
        print(f"  [{symbol}] ⚠️  GAP UP DETECTED — "
              f"stock opened at ₹{candle_open} which is above "
              f"entry ₹{entry}. Move was missed overnight.")
        return True

    return False


def sync_pending_trades(kite, df_60m_map=None):
    """
    Called at the start of every hourly scan.

    For each PENDING row in the Trades sheet:
    1. Check Kite order status
    2. COMPLETE   → auto-confirm OPEN with real fill price
    3. CANCELLED  → auto-skip (you cancelled manually)
    4. REJECTED   → auto-skip
    5. TRIGGER PENDING → check for gap-up condition
    6. No order found  → remind you to place the order

    df_60m_map: optional dict of {symbol: df_60m} for gap-up checks.
    """
    from scripts.sheets.sheets_writer import get_sheet_client
    from scripts.signals.entry_update_logic import (
        load_active_signal, clear_active_signal
    )

    ws      = get_sheet_client("Trades")
    records = ws.get_all_records()

    pending = [
        (idx, r) for idx, r in enumerate(records)
        if r["status"] == "PENDING"
    ]

    if not pending:
        print("  No pending trades to sync.")
        return []

    print(f"  {len(pending)} pending trade(s) — "
          f"syncing with Kite CNC orders...")

    orders    = get_todays_orders(kite)
    confirmed = []

    for idx, record in pending:
        row_number = idx + 2
        symbol     = record["symbol"]

        print(f"\n  [{symbol}]")

        # -------------------------------------------------------
        # No CNC order found in Kite for this symbol
        # -------------------------------------------------------
        if symbol not in orders:
            active = load_active_signal(symbol)
            print(f"  No CNC order found in Kite.")
            print(f"  👉 If you intend to take this trade, place a "
                  f"CNC SL-M BUY order in Zerodha for "
                  f"{record['quantity']} shares of {symbol} "
                  f"with trigger price ₹{record['entry_price']}")
            continue

        order       = orders[symbol]
        kite_status = order["status"]
        print(f"  Kite order status: {kite_status}")

        # -------------------------------------------------------
        # COMPLETE: filled — auto-confirm
        # -------------------------------------------------------
        if kite_status == "COMPLETE":
            fill_price = order["fill_price"]
            ws.update(f"J{row_number}", [["OPEN"]])
            ws.update(f"K{row_number}", [["YES"]])
            ws.update(f"L{row_number}", [[fill_price]])
            print(f"  ✅ AUTO-CONFIRMED OPEN "
                  f"@ actual fill ₹{fill_price}")
            confirmed.append(symbol)

        # -------------------------------------------------------
        # CANCELLED: you cancelled it manually
        # -------------------------------------------------------
        elif kite_status == "CANCELLED":
            ws.update(f"J{row_number}", [["SKIPPED"]])
            ws.update(f"K{row_number}", [["NO"]])
            ws.update(
                f"U{row_number}",
                [["Order cancelled manually in Zerodha"]]
            )
            clear_active_signal(symbol)
            print(f"  ⏭️  Order cancelled in Zerodha — "
                  f"marked SKIPPED, signal cleared.")

        # -------------------------------------------------------
        # REJECTED: exchange rejected the order
        # -------------------------------------------------------
        elif kite_status == "REJECTED":
            ws.update(f"J{row_number}", [["SKIPPED"]])
            ws.update(f"K{row_number}", [["NO"]])
            ws.update(
                f"U{row_number}",
                [[f"Order rejected by exchange"]]
            )
            clear_active_signal(symbol)
            print(f"  ❌ Order REJECTED by exchange — "
                  f"marked SKIPPED, signal cleared.")

        # -------------------------------------------------------
        # TRIGGER PENDING: CNC SL-M order live, waiting for price
        # -------------------------------------------------------
        elif kite_status in ("TRIGGER PENDING", "OPEN",
                              "PUT ORDER REQ RECEIVED"):
            active = load_active_signal(symbol)

            # Check for gap-up above entry
            df_60m = df_60m_map.get(symbol) \
                if df_60m_map else None
            if active and check_gap_up(symbol, active, df_60m):
                print(f"  👉 CANCEL your Zerodha CNC order for "
                      f"{symbol} — entry price was gapped over, "
                      f"setup is invalidated.")
                ws.update(
                    f"U{row_number}",
                    [["Gap up above entry — cancel Zerodha order"]]
                )
            else:
                trigger = order["trigger_price"]
                print(f"  ⏳ CNC order live in Zerodha "
                      f"(trigger: ₹{trigger}) — "
                      f"waiting for price to be hit. "
                      f"Can trigger any day.")

        # -------------------------------------------------------
        # Anything else
        # -------------------------------------------------------
        else:
            print(f"  ⚠️  Unknown order status: {kite_status} "
                  f"— leaving as PENDING.")

    return confirmed


def cancel_dropped_signals(new_watchlist_symbols):
    """
    Called at the end of every weekly scan.
    Checks if any symbols with active signals/pending trades
    are no longer on the new watchlist.
    Alerts you to cancel the Zerodha order manually.
    """
    from scripts.signals.entry_update_logic import clear_active_signal
    from scripts.sheets.sheets_writer import get_sheet_client
    from scripts.utils.config import ACTIVE_SIGNALS_DIR

    if not os.path.exists(ACTIVE_SIGNALS_DIR):
        return

    active_files = [
        f.replace("_signal.json", "")
        for f in os.listdir(ACTIVE_SIGNALS_DIR)
        if f.endswith("_signal.json")
    ]

    dropped = [s for s in active_files
               if s not in new_watchlist_symbols]

    if not dropped:
        print("  No dropped signals this week.")
        return

    # Also check Trades sheet for PENDING rows
    ws      = get_sheet_client("Trades")
    records = ws.get_all_records()

    for symbol in dropped:
        print(f"\n  [{symbol}] Dropped from WL this week.")

        # Check if there's a pending order in Trades sheet
        pending_row = next(
            (r for r in records
             if r["symbol"] == symbol
             and r["status"] == "PENDING"),
            None
        )

        if pending_row:
            print(f"  👉 CANCEL your pending CNC order for "
                  f"{symbol} in Zerodha — "
                  f"stock no longer qualifies for the watchlist.")

        # Clear the local signal state
        clear_active_signal(symbol)
        print(f"  Signal state cleared for {symbol}.")