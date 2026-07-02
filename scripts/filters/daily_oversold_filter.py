import sys
import os
import pandas as pd
sys.path.append(".")

from scripts.utils.indicators import rsi
from scripts.utils.config import (
    DAILY_RSI_PERIOD,
    DAILY_RSI_THRESHOLD,
    SUPPORT_LOOKBACK_DAYS,
    SUPPORT_TOLERANCE_PCT,
    SUPPORT_MIN_TOUCHES
)


def detect_swing_lows(df, swing_window=3):
    """Detects swing lows in a daily OHLCV dataframe."""
    lows = []
    for i in range(swing_window, len(df) - swing_window):
        window = df["low"].iloc[i - swing_window: i + swing_window + 1]
        if df["low"].iloc[i] == window.min():
            lows.append(df["low"].iloc[i])
    return lows


def find_support_zones(daily_df, lookback_days=None, tolerance_pct=None,
                        min_touches=None):
    """
    Finds frequently tested support zones within the lookback window.
    Returns a list of dicts: {avg, touches, touch_count}
    """
    lookback_days  = lookback_days  or SUPPORT_LOOKBACK_DAYS
    tolerance_pct  = tolerance_pct  or SUPPORT_TOLERANCE_PCT
    min_touches    = min_touches    or SUPPORT_MIN_TOUCHES

    recent = daily_df.tail(lookback_days).copy()
    swing_lows = detect_swing_lows(recent)

    if not swing_lows:
        return []

    clusters = []
    for low in sorted(swing_lows):
        placed = False
        for cluster in clusters:
            if abs(low - cluster["avg"]) / cluster["avg"] * 100 <= tolerance_pct:
                cluster["touches"].append(low)
                cluster["avg"] = sum(cluster["touches"]) / len(cluster["touches"])
                placed = True
                break
        if not placed:
            clusters.append({"avg": low, "touches": [low]})

    valid = [
        {
            "avg": round(c["avg"], 2),
            "touch_count": len(c["touches"]),
            "touches": [round(t, 2) for t in c["touches"]]
        }
        for c in clusters if len(c["touches"]) >= min_touches
    ]
    return valid


def is_daily_oversold_at_support(daily_df, rsi_period=None, rsi_threshold=None,
                                   min_history_days=60):
    """
    Returns (bool, dict) — whether symbol is oversold at a support zone.

    Conditions (both required):
    - RSI(5) < 30
    - Latest close within 1.5% of a frequently tested support zone
    """
    rsi_period    = rsi_period    or DAILY_RSI_PERIOD
    rsi_threshold = rsi_threshold or DAILY_RSI_THRESHOLD

    if len(daily_df) < min_history_days:
        return False, {"reason": "insufficient_history"}

    df = daily_df.copy()
    df.index = df.index.tz_localize(None) if df.index.tzinfo else df.index
    df["rsi5"] = rsi(df["close"], period=rsi_period)
    latest = df.iloc[-1]
    latest_rsi = round(float(latest["rsi5"]), 2)
    latest_close = round(float(latest["close"]), 2)

    # Condition 1: RSI oversold
    if latest_rsi >= rsi_threshold:
        return False, {
            "reason": "rsi_not_oversold",
            "rsi5": latest_rsi,
            "rsi_threshold": rsi_threshold
        }

    # Condition 2: At support zone
    zones = find_support_zones(df)
    if not zones:
        return False, {
            "reason": "no_support_zone_found",
            "rsi5": latest_rsi
        }

    nearest_zone = min(zones, key=lambda z: abs(latest_close - z["avg"]))
    distance_pct = abs(latest_close - nearest_zone["avg"]) / nearest_zone["avg"] * 100

    if distance_pct > SUPPORT_TOLERANCE_PCT:
        return False, {
            "reason": "not_at_support",
            "rsi5": latest_rsi,
            "nearest_zone": nearest_zone["avg"],
            "distance_pct": round(distance_pct, 2)
        }

    return True, {
        "reason": "pass",
        "rsi5": latest_rsi,
        "support_zone_price": nearest_zone["avg"],
        "support_touches": nearest_zone["touch_count"],
        "distance_pct": round(distance_pct, 2)
    }


def run_daily_oversold_filter(symbols, daily_data_map):
    """
    Runs the daily oversold/support filter across a list of symbols.
    daily_data_map: dict of {symbol: daily_df}
    Returns a DataFrame of results.
    """
    results = []
    for symbol in symbols:
        if symbol not in daily_data_map:
            results.append({
                "symbol": symbol,
                "passes_daily_oversold": False,
                "reason": "no_data",
                "rsi5": None,
                "support_zone_price": None
            })
            continue

        passes, details = is_daily_oversold_at_support(daily_data_map[symbol])
        results.append({
            "symbol": symbol,
            "passes_daily_oversold": passes,
            **details
        })

    return pd.DataFrame(results)


if __name__ == "__main__":
    try:
        from scripts.data_fetch.fetch_daily import load_daily

        print("Testing daily oversold/support filter for RELIANCE...")
        daily_df = load_daily("RELIANCE")
        print(f"Rows loaded: {len(daily_df)}")

        passes, details = is_daily_oversold_at_support(daily_df)
        print(f"\nPasses daily oversold filter: {passes}")
        print(f"Details: {details}")

        print("\nSupport zones found:")
        zones = find_support_zones(daily_df)
        if zones:
            for z in zones:
                print(f"  Zone: ₹{z['avg']} — {z['touch_count']} touches")
        else:
            print("  No support zones found")

    except Exception as e:
        import traceback
        print(f"ERROR: {e}")
        traceback.print_exc()