import pandas as pd
import numpy as np

def ema(series, period):
    """Exponential Moving Average."""
    return series.ewm(span=period, adjust=False).mean()

def rsi(series, period=5):
    """Relative Strength Index."""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def atr(df, period=14):
    """Average True Range."""
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return true_range.ewm(alpha=1/period, adjust=False).mean()

def obv(df):
    """On Balance Volume."""
    direction = df["close"].diff().apply(
        lambda x: 1 if x > 0 else (-1 if x < 0 else 0)
    )
    return (direction * df["volume"]).cumsum()

def resample_ohlcv(daily_df, rule="W"):
    """
    Resamples daily OHLCV data to weekly (or any other rule).
    Open = first, High = max, Low = min, Close = last, Volume = sum.
    """
    resampled = daily_df.resample(rule).agg({
        "open":   "first",
        "high":   "max",
        "low":    "min",
        "close":  "last",
        "volume": "sum"
    }).dropna()
    return resampled