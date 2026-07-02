import sys
import os
import math
import pandas as pd
sys.path.append(".")

from scripts.utils.indicators import ema, atr, obv
from scripts.utils.config import (
    EMA_SIGNAL_PERIOD,
    ATR_PERIOD,
    VOLUME_AVG_PERIOD,
    TP_MULTIPLE,
    RISK_PCT
)


def prepare_60m_indicators(df_60m):
    """
    Adds all indicator columns needed for signal detection.
    Returns a new DataFrame with added columns.
    """
    df = df_60m.copy()
    df.index = df.index.tz_localize(None) if df.index.tzinfo else df.index

    df["ema9"]          = ema(df["close"], period=EMA_SIGNAL_PERIOD)
    df["atr14"]         = atr(df, period=ATR_PERIOD)
    df["avg_volume14"]  = df["volume"].rolling(window=VOLUME_AVG_PERIOD).mean()
    df["obv"]           = obv(df)

    return df


def is_signal_candle(df_60m, i):
    """
    Returns True if candle at index i meets all signal conditions:
    1. Close > EMA9
    2. Close > Open (bullish candle)
    3. Volume > 14-period average volume
    4. OBV rising (OBV[i] > OBV[i-1])
    """
    if i < 1:
        return False

    candle   = df_60m.iloc[i]
    prev_obv = df_60m.iloc[i - 1]["obv"]

    bullish     = candle["close"] > candle["open"]
    above_ema9  = candle["close"] > candle["ema9"]
    volume_ok   = candle["volume"] > candle["avg_volume14"]
    obv_rising  = candle["obv"] > prev_obv

    return bullish and above_ema9 and volume_ok and obv_rising


def compute_trade_levels(signal_candle, atr_value, risk_amount,
                          tp_multiple=None):
    """
    Computes entry, SL, TP, quantity from a signal candle.
    Returns a dict or None if quantity works out to zero.
    """
    tp_multiple = tp_multiple or TP_MULTIPLE

    entry          = round(signal_candle["high"] + atr_value, 2)
    sl             = round(signal_candle["low"]  - atr_value, 2)
    risk_per_share = round(entry - sl, 2)

    if risk_per_share <= 0:
        return None

    quantity = math.floor(risk_amount / risk_per_share)
    if quantity == 0:
        return None

    tp = round(entry + tp_multiple * (entry - sl), 2)

    return {
        "entry":          entry,
        "sl":             sl,
        "tp":             tp,
        "risk_per_share": risk_per_share,
        "quantity":       quantity,
        "risk_amount":    round(risk_amount, 2)
    }


def scan_for_signal(df_60m, risk_amount, symbol=None):
    """
    Scans the most recent completed 60m candle for a valid signal.
    Returns a signal dict (ENTRY_INITIAL payload) or None.

    Note: uses iloc[-2] (last completed candle) not iloc[-1]
    (which may still be forming during market hours).
    """
    df = prepare_60m_indicators(df_60m)

    # Use the last completed candle (not the still-forming current one)
    signal_idx = len(df) - 2
    if signal_idx < 1:
        return None

    if not is_signal_candle(df, signal_idx):
        return None

    signal_candle = df.iloc[signal_idx]
    atr_value     = signal_candle["atr14"]

    levels = compute_trade_levels(signal_candle, atr_value, risk_amount)
    if levels is None:
        return None

    return {
        "symbol":      symbol,
        "signal_time": str(signal_candle.name),
        "signal_high": round(float(signal_candle["high"]), 2),
        "signal_low":  round(float(signal_candle["low"]),  2),
        "atr":         round(float(atr_value), 2),
        **levels
    }


def find_historical_signals(df_60m, risk_amount, symbol=None):
    """
    Scans all historical 60m candles for valid signal candles.
    Used for backtesting — returns a list of all signals found.
    """
    df      = prepare_60m_indicators(df_60m)
    signals = []

    for i in range(1, len(df) - 1):
        if not is_signal_candle(df, i):
            continue

        signal_candle = df.iloc[i]
        atr_value     = signal_candle["atr14"]
        levels        = compute_trade_levels(signal_candle, atr_value,
                                              risk_amount)
        if levels is None:
            continue

        signals.append({
            "symbol":      symbol,
            "signal_time": str(signal_candle.name),
            "signal_high": round(float(signal_candle["high"]), 2),
            "signal_low":  round(float(signal_candle["low"]),  2),
            "atr":         round(float(atr_value), 2),
            **levels
        })

    return signals


if __name__ == "__main__":
    try:
        from scripts.data_fetch.fetch_intraday_60m import load_60m

        # Use a test risk amount (will come from Sheets in live system)
        TEST_CAPITAL    = 1000000
        test_risk_amount = TEST_CAPITAL * RISK_PCT
        print(f"Test capital: ₹{TEST_CAPITAL:,}")
        print(f"Risk per trade (0.25%): ₹{test_risk_amount:,}")

        print("\nLoading 60m data for RELIANCE...")
        df_60m = load_60m("RELIANCE")
        print(f"Rows loaded: {len(df_60m)}")

        # Check most recent candle for a live signal
        print("\n--- Live Signal Check (last completed candle) ---")
        signal = scan_for_signal(df_60m, test_risk_amount, symbol="RELIANCE")
        if signal:
            print("SIGNAL FOUND:")
            for k, v in signal.items():
                print(f"  {k}: {v}")
        else:
            print("No signal on last completed candle.")

        # Scan all historical candles
        print("\n--- Historical Signal Scan ---")
        all_signals = find_historical_signals(
            df_60m, test_risk_amount, symbol="RELIANCE"
        )
        print(f"Total historical signals found: {len(all_signals)}")
        if all_signals:
            print("\nMost recent 3 signals:")
            for s in all_signals[-3:]:
                print(f"  {s['signal_time']} | "
                      f"Entry: ₹{s['entry']} | "
                      f"SL: ₹{s['sl']} | "
                      f"TP: ₹{s['tp']} | "
                      f"Qty: {s['quantity']}")

    except Exception as e:
        import traceback
        print(f"ERROR: {e}")
        traceback.print_exc()