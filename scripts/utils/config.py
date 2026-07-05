import os

# --- Data Source ---
DATA_SOURCE = "kite"   # "kite" or "yfinance"

# --- File Paths ---
UNIVERSE_FILE         = "data/universe/nifty500.csv"
INSTRUMENT_MAP_FILE   = "data/universe/kite_instrument_map.csv"
SESSION_FILE          = "data/.kite_session.json"
RAW_DAILY_DIR         = "data/raw/daily/"
RAW_WEEKLY_DIR        = "data/raw/weekly/"
RAW_60M_DIR           = "data/raw/intraday_60m/"
PROCESSED_TREND_DIR   = "data/processed/weekly_trend/"
PROCESSED_OVERSOLD_DIR= "data/processed/daily_oversold/"
WATCHLIST_DIR         = "data/processed/watchlist/"
ACTIVE_SIGNALS_DIR    = "data/processed/active_signals/"

# --- Fetch Parameters ---
DAILY_LOOKBACK_DAYS   = 365 * 5   # 5 years
INTRADAY_60M_DAYS     = 60        # Kite's practical limit for 60m candles

# --- Strategy Parameters ---
WEEKLY_EMA_PERIOD     = 20
DAILY_RSI_PERIOD      = 5
DAILY_RSI_THRESHOLD   = 30
SUPPORT_LOOKBACK_DAYS = 180
SUPPORT_TOLERANCE_PCT = 1.5
SUPPORT_MIN_TOUCHES   = 3
ATR_PERIOD            = 14
EMA_SIGNAL_PERIOD     = 9
EMA_EXIT_FAST         = 9
EMA_EXIT_SLOW         = 21
VOLUME_AVG_PERIOD     = 14
TP_MULTIPLE           = 1.5
RISK_PCT              = 0.0025    # 0.25% of capital
MAX_POSITION_VALUE = 100000   # ₹1L max capital per single trade
# --- Risk (capital read live from Sheets at runtime) ---
# get_risk_amount() in sheets_writer.py handles this