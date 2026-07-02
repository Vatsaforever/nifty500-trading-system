import sys
import os
import json
import pandas as pd
from datetime import datetime
sys.path.append(".")

from scripts.signals.signal_engine_60m import (
    prepare_60m_indicators,
    is_signal_candle,
    compute_trade_levels
)
from scripts.utils.config import ACTIVE_SIGNALS_DIR

# State file — one JSON file per symbol
def _state_path(symbol):
    return os.path.join(ACTIVE_SIGNALS_DIR, f"{symbol}_signal.json")


def load_active_signal(symbol):
    """
    Loads the current active signal state for a symbol from disk.
    Returns None if no active signal exists.
    """
    path = _state_path(symbol)
    if not os.path.exists(path):
        return None
    with open(path, "r") as f:
        return json.load(f)


def save_active_signal(signal_state):
    """Persists the active signal state for a symbol to disk."""
    os.makedirs(ACTIVE_SIGNALS_DIR, exist_ok=True)
    path = _state_path(signal_state["symbol"])
    with open(path, "w") as f:
        json.dump(signal_state, f, indent=2, default=str)


def clear_active_signal(symbol):
    """
    Removes the active signal state file for a symbol.
    Called when a trade is triggered (BUY) or signal is invalidated.
    """
    path = _state_path(symbol)
    if os.path.exists(path):
        os.remove(path)
    print(f"  [{symbol}] Active signal cleared.")


def create_initial_signal(symbol, signal_dict):
    """
    Creates a fresh active signal state from an ENTRY_INITIAL signal dict.
    """
    state = {
        "symbol":           symbol,
        "has_active_signal": True,
        "entry_triggered":  False,
        "active_entry":     signal_dict["entry"],
        "active_sl":        signal_dict["sl"],
        "active_tp":        signal_dict["tp"],
        "active_high":      signal_dict["signal_high"],
        "active_low":       signal_dict["signal_low"],
        "active_atr":       signal_dict["atr"],
        "active_quantity":  signal_dict["quantity"],
        "risk_amount":      signal_dict["risk_amount"],
        "signal_time":      signal_dict["signal_time"],
        "last_updated_time": signal_dict["signal_time"]
    }
    save_active_signal(state)
    return state


def process_new_candle(symbol, new_candle, df_60m_with_indicators):
    """
    Processes a new 60m candle against the active signal state.

    Returns (updated_state, event) where event is one of:
        None           — no change
        "BUY"          — entry triggered
        "ENTRY_UPDATED"— signal replaced with lower-high candle
    """
    active = load_active_signal(symbol)
    if active is None:
        return None, None

    if active["entry_triggered"]:
        return active, None

    candle_high  = float(new_candle["high"])
    candle_time  = str(new_candle.name)

    # --- Priority 1: Check if entry has triggered ---
    if candle_high >= active["active_entry"]:
        active["entry_triggered"]  = True
        active["entry_fill_time"]  = candle_time
        save_active_signal(active)
        return active, "BUY"

    # --- Priority 2: Check for a lower-high replacement signal ---
    idx = df_60m_with_indicators.index.get_loc(new_candle.name)
    if is_signal_candle(df_60m_with_indicators, idx):
        if candle_high < active["active_high"]:
            atr_value = float(new_candle["atr14"])
            levels    = compute_trade_levels(
                new_candle, atr_value, active["risk_amount"]
            )
            if levels is not None:
                old_entry = active["active_entry"]
                old_sl    = active["active_sl"]

                active.update({
                    "active_entry":      levels["entry"],
                    "active_sl":         levels["sl"],
                    "active_tp":         levels["tp"],
                    "active_high":       round(candle_high, 2),
                    "active_low":        round(float(new_candle["low"]), 2),
                    "active_atr":        round(atr_value, 2),
                    "active_quantity":   levels["quantity"],
                    "last_updated_time": candle_time
                })
                save_active_signal(active)

                # Return update details for event logging
                active["_old_entry"] = old_entry
                active["_old_sl"]    = old_sl
                return active, "ENTRY_UPDATED"

    # --- No change ---
    return active, None


def simulate_entry_update_sequence(df_60m, risk_amount, symbol="TEST"):
    """
    Simulates the full entry-update lifecycle on historical 60m data.
    Used for testing — walks candle by candle and prints state transitions.
    """
    from scripts.signals.signal_engine_60m import scan_for_signal

    df = prepare_60m_indicators(df_60m)
    print(f"\n[{symbol}] Starting entry update simulation...")
    print(f"  Scanning {len(df)} candles...\n")

    active = None
    events = []

    for i in range(1, len(df)):
        current_candle = df.iloc[i]
        candle_time    = str(current_candle.name)

        # If no active signal, check if this candle starts one
        if active is None:
            if is_signal_candle(df, i):
                atr_value = float(current_candle["atr14"])
                levels    = compute_trade_levels(
                    current_candle, atr_value, risk_amount
                )
                if levels:
                    signal_dict = {
                        "entry":       levels["entry"],
                        "sl":          levels["sl"],
                        "tp":          levels["tp"],
                        "signal_high": round(float(current_candle["high"]), 2),
                        "signal_low":  round(float(current_candle["low"]),  2),
                        "atr":         round(atr_value, 2),
                        "quantity":    levels["quantity"],
                        "risk_amount": risk_amount,
                        "signal_time": candle_time
                    }
                    active = create_initial_signal(symbol, signal_dict)
                    events.append({
                        "event": "ENTRY_INITIAL",
                        "time":  candle_time,
                        "entry": levels["entry"],
                        "sl":    levels["sl"],
                        "tp":    levels["tp"],
                        "qty":   levels["quantity"]
                    })
                    print(f"  ENTRY_INITIAL @ {candle_time}")
                    print(f"    Entry: ₹{levels['entry']} | "
                          f"SL: ₹{levels['sl']} | "
                          f"TP: ₹{levels['tp']} | "
                          f"Qty: {levels['quantity']}")
            continue

        # Active signal exists — process this candle
        updated, event = process_new_candle(symbol, current_candle, df)

        if event == "BUY":
            events.append({
                "event": "BUY",
                "time":  candle_time,
                "entry": active["active_entry"]
            })
            print(f"\n  BUY TRIGGERED @ {candle_time}")
            print(f"    Entry: ₹{active['active_entry']}")
            active = None
            clear_active_signal(symbol)

        elif event == "ENTRY_UPDATED":
            events.append({
                "event":     "ENTRY_UPDATED",
                "time":      candle_time,
                "old_entry": updated["_old_entry"],
                "new_entry": updated["active_entry"],
                "old_sl":    updated["_old_sl"],
                "new_sl":    updated["active_sl"]
            })
            print(f"\n  ENTRY_UPDATED @ {candle_time}")
            print(f"    Entry: ₹{updated['_old_entry']} → "
                  f"₹{updated['active_entry']}")
            print(f"    SL:    ₹{updated['_old_sl']} → "
                  f"₹{updated['active_sl']}")
            active = updated

    print(f"\n[{symbol}] Simulation complete.")
    print(f"  Total events: {len(events)}")
    for e in events:
        print(f"  {e['event']} @ {e['time']}")

    # Clean up test state file
    clear_active_signal(symbol)
    return events


if __name__ == "__main__":
    try:
        from scripts.data_fetch.fetch_intraday_60m import load_60m

        TEST_CAPITAL     = 1000000
        test_risk_amount = TEST_CAPITAL * 0.0025

        print("Loading 60m data for RELIANCE...")
        df_60m = load_60m("RELIANCE")
        print(f"Rows loaded: {len(df_60m)}")

        events = simulate_entry_update_sequence(
            df_60m, test_risk_amount, symbol="RELIANCE"
        )

    except Exception as e:
        import traceback
        print(f"ERROR: {e}")
        traceback.print_exc()