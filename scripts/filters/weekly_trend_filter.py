import sys
import os
import pandas as pd
sys.path.append(".")

from scripts.utils.indicators import ema
from scripts.utils.config import (
    WEEKLY_EMA_PERIOD,
    PROCESSED_TREND_DIR,
    RAW_WEEKLY_DIR
)

def detect_swing_highs_lows(df, swing_window=3):
    """Detects swing highs and lows over a rolling window."""
    highs = []
    lows = []
    for i in range(swing_window, len(df) - swing_window):
        window_high = df["high"].iloc[i - swing_window: i + swing_window + 1]
        window_low = df["low"].iloc[i - swing_window: i + swing_window + 1]
        if df["high"].iloc[i] == window_high.max():
            highs.append(df["high"].iloc[i])
        if df["low"].iloc[i] == window_low.min():
            lows.append(df["low"].iloc[i])
    return highs, lows


def is_weekly_uptrend(weekly_df, use_dow_confirmation=False, min_weeks=30):
    """
    Returns (bool, dict) — whether symbol is in a weekly uptrend.

    Conditions:
    - Minimum history: 30 weeks
    - Primary: latest weekly close > EMA20
    - Optional: Dow-style higher high + higher low (default OFF)
    """
    if len(weekly_df) < min_weeks:
        return False, {"reason": "insufficient_history"}

    # Strip timezone for clean processing
    df = weekly_df.copy()
    df.index = df.index.tz_localize(None) if df.index.tzinfo else df.index

    df["ema20"] = ema(df["close"], period=WEEKLY_EMA_PERIOD)
    latest = df.iloc[-1]

    base_condition = latest["close"] > latest["ema20"]
    if not base_condition:
        return False, {
            "reason": "close_below_ema20",
            "weekly_close": round(latest["close"], 2),
            "weekly_ema20": round(latest["ema20"], 2)
        }

    if use_dow_confirmation:
        swing_highs, swing_lows = detect_swing_highs_lows(df)
        if len(swing_highs) < 2 or len(swing_lows) < 2:
            return False, {"reason": "insufficient_swings_for_dow"}
        hh = swing_highs[-1] > swing_highs[-2]
        hl = swing_lows[-1] > swing_lows[-2]
        if not (hh and hl):
            return False, {"reason": "no_dow_confirmation"}

    return True, {
        "reason": "pass",
        "weekly_close": round(latest["close"], 2),
        "weekly_ema20": round(latest["ema20"], 2)
    }


def run_weekly_trend_filter(symbols, weekly_data_map, use_dow_confirmation=False):
    """
    Runs the weekly trend filter across a list of symbols.
    weekly_data_map: dict of {symbol: weekly_df}
    Returns a DataFrame of results for all symbols.
    """
    results = []
    for symbol in symbols:
        if symbol not in weekly_data_map:
            results.append({
                "symbol": symbol,
                "passes_weekly_trend": False,
                "reason": "no_data",
                "weekly_close": None,
                "weekly_ema20": None
            })
            continue

        passes, details = is_weekly_uptrend(
            weekly_data_map[symbol],
            use_dow_confirmation=use_dow_confirmation
        )
        results.append({
            "symbol": symbol,
            "passes_weekly_trend": passes,
            **details
        })

    return pd.DataFrame(results)


if __name__ == "__main__":
    # Test on RELIANCE
    from scripts.data_fetch.fetch_weekly import load_weekly

    print("Testing weekly trend filter for RELIANCE...")
    weekly_df = load_weekly("RELIANCE")
    passes, details = is_weekly_uptrend(weekly_df)

    print(f"Passes weekly trend: {passes}")
    print(f"Details: {details}")