import sys
import os
import pandas as pd
sys.path.append(".")

from scripts.utils.indicators import ema
from scripts.utils.config import EMA_EXIT_FAST, EMA_EXIT_SLOW


def check_exit_conditions(live_trade, new_candle, df_60m):
    """
    Checks all exit conditions for a live trade on each new 60m candle.

    Priority order (per spec):
    1. SL_HIT  — checked first (conservative)
    2. TP_HIT  — checked second
    3. EMA_EXIT — alert only, does not close trade

    live_trade dict must contain:
        symbol, entry, sl, tp, quantity

    Returns (event, details) where event is one of:
        None        — no exit condition met
        "SL_HIT"    — stop loss hit
        "TP_HIT"    — take profit hit
        "EMA_EXIT"  — EMA cross alert (trade stays open)
    """
    candle_low  = float(new_candle["low"])
    candle_high = float(new_candle["high"])
    candle_time = str(new_candle.name)

    entry = float(live_trade["entry"])
    sl    = float(live_trade["sl"])
    tp    = float(live_trade["tp"])
    qty   = int(live_trade["quantity"])

    # --- Priority 1: SL Hit ---
    if candle_low <= sl:
        r_multiple   = round((sl - entry) / (entry - sl), 2)   # always -1.0
        pnl          = round((sl - entry) * qty, 2)
        return "SL_HIT", {
            "exit_price":    sl,
            "exit_time":     candle_time,
            "exit_reason":   "SL_HIT",
            "r_multiple":    r_multiple,
            "pnl_rupees":    pnl,
            "entry":         entry,
            "tp":            tp,
            "quantity":      qty
        }

    # --- Priority 2: TP Hit ---
    if candle_high >= tp:
        r_multiple = round((tp - entry) / (entry - sl), 2)     # always ~1.5
        pnl        = round((tp - entry) * qty, 2)
        return "TP_HIT", {
            "exit_price":    tp,
            "exit_time":     candle_time,
            "exit_reason":   "TP_HIT",
            "r_multiple":    r_multiple,
            "pnl_rupees":    pnl,
            "entry":         entry,
            "sl":            sl,
            "quantity":      qty
        }

    # --- Priority 3: EMA Exit Alert (alert only, no close) ---
    ema_event = check_ema_exit(df_60m, new_candle)
    if ema_event:
        return "EMA_EXIT", {
            "ema9":          round(ema_event["ema9"], 2),
            "ema21":         round(ema_event["ema21"], 2),
            "current_price": round(float(new_candle["close"]), 2),
            "candle_time":   candle_time,
            "note":          "Alert only — position remains open"
        }

    return None, None


def check_ema_exit(df_60m, new_candle):
    """
    Returns EMA values if EMA9 has crossed below EMA21 on this candle,
    None otherwise. Only fires on the crossover candle — not on every
    subsequent candle where EMA9 remains below EMA21.
    """
    df = df_60m.copy()
    df.index = df.index.tz_localize(None) if df.index.tzinfo else df.index

    df["ema9"]  = ema(df["close"], period=EMA_EXIT_FAST)
    df["ema21"] = ema(df["close"], period=EMA_EXIT_SLOW)

    # Find this candle's position
    try:
        idx = df.index.get_loc(new_candle.name)
    except KeyError:
        return None

    if idx < 1:
        return None

    curr_ema9  = df["ema9"].iloc[idx]
    curr_ema21 = df["ema21"].iloc[idx]
    prev_ema9  = df["ema9"].iloc[idx - 1]
    prev_ema21 = df["ema21"].iloc[idx - 1]

    # Crossover: was above, now below
    crossed_below = (prev_ema9 >= prev_ema21) and (curr_ema9 < curr_ema21)
    if crossed_below:
        return {"ema9": curr_ema9, "ema21": curr_ema21}

    return None


def simulate_trade_exits(df_60m, signals, symbol="TEST"):
    """
    Simulates exit logic on historical data for a list of BUY signals.
    For each BUY, walks forward candle by candle until an exit is found.
    Returns a list of completed trade results.
    """
    df = df_60m.copy()
    df.index = df.index.tz_localize(None) if df.index.tzinfo else df.index
    df["ema9"]  = ema(df["close"], period=EMA_EXIT_FAST)
    df["ema21"] = ema(df["close"], period=EMA_EXIT_SLOW)

    results = []

    for signal in signals:
        entry_time = pd.Timestamp(signal["signal_time"])
        if entry_time not in df.index:
            continue

        entry_idx = df.index.get_loc(entry_time)

        print(f"\n  Trade: Entry ₹{signal['entry']} | "
              f"SL ₹{signal['sl']} | "
              f"TP ₹{signal['tp']} | "
              f"Qty {signal['quantity']}")

        trade_result = None
        ema_alert_fired = False

        for i in range(entry_idx + 1, len(df)):
            candle = df.iloc[i]
            event, details = check_exit_conditions(signal, candle, df.iloc[:i+1])

            if event == "EMA_EXIT" and not ema_alert_fired:
                print(f"    ⚠️  EMA_EXIT alert @ {str(candle.name)} "
                      f"(EMA9: {details['ema9']} < EMA21: {details['ema21']}) "
                      f"— position stays open")
                ema_alert_fired = True

            elif event in ("SL_HIT", "TP_HIT"):
                print(f"    {'✅' if event == 'TP_HIT' else '❌'} "
                      f"{event} @ {details['exit_time']} | "
                      f"Exit: ₹{details['exit_price']} | "
                      f"P&L: ₹{details['pnl_rupees']} | "
                      f"R: {details['r_multiple']}")
                trade_result = {
                    "symbol":        symbol,
                    "entry":         signal["entry"],
                    "sl":            signal["sl"],
                    "tp":            signal["tp"],
                    "quantity":      signal["quantity"],
                    "entry_time":    str(entry_time),
                    "ema_exit_alert": ema_alert_fired,
                    **details
                }
                results.append(trade_result)
                break

        if trade_result is None:
            print(f"    ⏳ No exit found yet — trade still open")

    return results


if __name__ == "__main__":
    try:
        from scripts.data_fetch.fetch_intraday_60m import load_60m
        from scripts.signals.signal_engine_60m import (
            find_historical_signals, prepare_60m_indicators
        )

        TEST_CAPITAL     = 1000000
        test_risk_amount = TEST_CAPITAL * 0.0025

        print("Loading 60m data for RELIANCE...")
        df_60m = load_60m("RELIANCE")
        print(f"Rows loaded: {len(df_60m)}")

        print("\nFinding historical signals...")
        signals = find_historical_signals(
            df_60m, test_risk_amount, symbol="RELIANCE"
        )
        print(f"Total signals: {len(signals)}")

        print("\n--- Simulating Trade Exits ---")
        results = simulate_trade_exits(df_60m, signals, symbol="RELIANCE")

        print(f"\n--- Summary ---")
        print(f"Total completed trades: {len(results)}")
        if results:
            wins   = [r for r in results if r["r_multiple"] > 0]
            losses = [r for r in results if r["r_multiple"] <= 0]
            total_pnl = sum(r["pnl_rupees"] for r in results)
            print(f"Wins:   {len(wins)}")
            print(f"Losses: {len(losses)}")
            print(f"Win Rate: {round(len(wins)/len(results)*100, 1)}%")
            print(f"Total P&L: ₹{round(total_pnl, 2):,}")

    except Exception as e:
        import traceback
        print(f"ERROR: {e}")
        traceback.print_exc()