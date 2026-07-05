import sys
import os
import math
import pandas as pd
from datetime import datetime, date
sys.path.append(".")

from scripts.data_fetch.kite_auth import load_kite_client
from scripts.data_fetch.fetch_daily import fetch_daily_kite, load_instrument_map
from scripts.data_fetch.fetch_intraday_60m import fetch_intraday_60m
from scripts.utils.config import RISK_PCT, MAX_POSITION_VALUE, TP_MULTIPLE
from scripts.sheets.sheets_writer import get_risk_amount, get_sheet_client

# ORB Parameters
MIN_GAP_PCT        = -0.02   # allow slight gap down too
MAX_GAP_PCT        =  0.05   # max 5% gap up
MIN_RANGE_PCT      =  0.003  # 0.3% min opening range
MAX_RANGE_PCT      =  0.03   # 3.0% max opening range
VOLUME_MULTIPLIER  =  1.5    # breakout volume > 1.5x OR candle
ENTRY_BUFFER_PCT   =  0.001  # 0.1% above OR high
NIFTY50_FILE       = "data/universe/nifty50.csv"
ORB_SIGNALS_SHEET  = "ORB Signals"
ORB_TRADES_SHEET   = "ORB Trades"


def is_market_open():
    now     = datetime.now()
    weekday = now.weekday()
    if weekday > 4:
        return False
    open_time  = now.replace(hour=9,  minute=25, second=0)
    close_time = now.replace(hour=9,  minute=45, second=0)
    return open_time <= now <= close_time


def get_opening_range(df_60m):
    """
    Returns the first completed 60m candle (9:15-10:15 AM)
    as the opening range candle.
    """
    df = df_60m.copy()
    df.index = df.index.tz_localize(None) \
        if df.index.tzinfo else df.index
    today = date.today()
    today_candles = df[df.index.date == today].sort_index()
    if len(today_candles) < 1:
        return None
    return today_candles.iloc[0]


def check_orb_signal(symbol, daily_df, df_60m, risk_amount):
    """
    Checks if a valid ORB breakout signal exists for today.
    Returns signal dict or None.
    """
    or_candle = get_opening_range(df_60m)
    if or_candle is None:
        return None

    or_high   = float(or_candle['high'])
    or_low    = float(or_candle['low'])
    or_open   = float(or_candle['open'])
    or_close  = float(or_candle['close'])
    or_volume = float(or_candle['volume'])

    # Need previous close for gap check
    daily_df = daily_df.copy()
    daily_df.index = daily_df.index.tz_localize(None) \
        if daily_df.index.tzinfo else daily_df.index
    prev_days = daily_df[daily_df.index.date < date.today()]
    if len(prev_days) < 20:
        return None
    prev_close  = float(prev_days['close'].iloc[-1])
    avg_volume  = float(prev_days['volume'].iloc[-20:].mean())

    # Gap filter
    gap_pct     = (or_open - prev_close) / prev_close
    if gap_pct > MAX_GAP_PCT:
        return None

    # Range size filter
    range_width = or_high - or_low
    range_pct   = range_width / or_low
    if range_pct < MIN_RANGE_PCT or range_pct > MAX_RANGE_PCT:
        return None

    # Must be a bullish opening candle
    if or_close <= or_open:
        return None

    # Price must break above OR high
    # Check the SECOND candle (the breakout candle)
    df = df_60m.copy()
    df.index = df.index.tz_localize(None) \
        if df.index.tzinfo else df.index
    today_candles = df[df.index.date == date.today()].sort_index()
    if len(today_candles) < 2:
        return None

    breakout_candle = today_candles.iloc[1]
    if float(breakout_candle['high']) <= or_high:
        return None

    # Volume filter on breakout candle
    if float(breakout_candle['volume']) < or_volume * VOLUME_MULTIPLIER:
        return None

    # Weekly trend filter
    weekly      = daily_df['close'].resample('W').last()
    weekly_ema  = weekly.ewm(span=20, adjust=False).mean()
    if len(weekly) < 30:
        return None
    if float(weekly.iloc[-1]) <= float(weekly_ema.iloc[-1]):
        return None

    # Compute levels
    entry       = round(or_high * (1 + ENTRY_BUFFER_PCT), 2)
    sl          = round(or_low, 2)
    rps         = entry - sl
    if rps <= 0:
        return None

    qty_risk    = math.floor(risk_amount / rps)
    qty_cap     = math.floor(MAX_POSITION_VALUE / entry)
    qty         = min(qty_risk, qty_cap)
    if qty == 0:
        return None

    tp          = round(entry + TP_MULTIPLE * rps, 2)

    return {
        'symbol':       symbol,
        'signal_time':  str(breakout_candle.name),
        'or_high':      round(or_high, 2),
        'or_low':       round(or_low, 2),
        'range_pct':    round(range_pct * 100, 2),
        'gap_pct':      round(gap_pct * 100, 2),
        'entry':        entry,
        'sl':           sl,
        'tp':           tp,
        'quantity':     qty,
        'risk_amount':  round(rps * qty, 2),
        'order_type':   'MIS SL-M',
        'exit_by':      '3:15 PM (EOD)'
    }


def write_orb_signal(signal, sector=''):
    """Writes ORB signal to ORB Signals sheet."""
    try:
        ws  = get_sheet_client(ORB_SIGNALS_SHEET)
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        row = [
            now,
            signal['symbol'],
            sector,
            signal['or_high'],
            signal['or_low'],
            signal['range_pct'],
            signal['gap_pct'],
            signal['entry'],
            signal['sl'],
            signal['tp'],
            signal['quantity'],
            signal['risk_amount'],
            signal['order_type'],
            signal['exit_by']
        ]
        ws.append_row(row)
        print(f"  📋 ORB signal written to Sheets: {signal['symbol']}")
    except Exception as e:
        print(f"  ⚠️ Could not write to Sheets: {e}")


def send_orb_alert(signal):
    try:
        from scripts.utils.telegram_alerts import alert_orb_signal
        alert_orb_signal(
            symbol    = signal['symbol'],
            entry     = signal['entry'],
            sl        = signal['sl'],
            tp        = signal['tp'],
            qty       = signal['quantity'],
            risk      = signal['risk_amount'],
            or_high   = signal['or_high'],
            or_low    = signal['or_low'],
            range_pct = signal['range_pct']
        )
    except Exception as e:
        print(f"  ⚠️ Alert failed: {e}")


def run_orb_scan():
    """
    Main ORB scan — runs at 9:30 AM after first candle closes.
    Scans all Nifty 50 stocks for ORB breakout signals.
    """
    print(f"\n{'='*55}")
    print(f"ORB SCAN — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*55}\n")

    if not os.path.exists(NIFTY50_FILE):
        print("Nifty 50 universe file not found.")
        print("Run: python scripts/utils/build_nifty50.py")
        return

    nifty50    = pd.read_csv(NIFTY50_FILE)
    symbols    = nifty50[nifty50['active'] == True]['symbol'].tolist()
    sector_map = nifty50.set_index('symbol')['sector'].to_dict()

    kite       = load_kite_client()
    imap       = load_instrument_map()

    try:
        risk_amount = get_risk_amount()
    except Exception:
        risk_amount = 1_000_000 * 0.0025
    print(f"Risk per trade: ₹{risk_amount:,.2f}\n")

    signals = []

    for symbol in symbols:
        try:
            print(f"  [{symbol}]", end=" ")
            if symbol not in imap.index:
                print("not in map")
                continue

            daily_df = fetch_daily_kite(
                symbol, kite=kite, instrument_map=imap
            )
            df_60m   = fetch_intraday_60m(
                symbol, kite=kite, instrument_map=imap
            )

            signal = check_orb_signal(
                symbol, daily_df, df_60m, risk_amount
            )

            if signal:
                sector = sector_map.get(symbol, '')
                signals.append(signal)
                print(
                    f"🚀 SIGNAL | "
                    f"Entry ₹{signal['entry']} | "
                    f"SL ₹{signal['sl']} | "
                    f"TP ₹{signal['tp']} | "
                    f"Qty {signal['quantity']}"
                )
                write_orb_signal(signal, sector=sector)
                send_orb_alert(signal)
            else:
                print("no signal")

        except Exception as e:
            print(f"ERROR — {e}")
            continue

    print(f"\n{'='*55}")
    print(f"ORB SCAN COMPLETE — {len(signals)} signal(s) found")
    if signals:
        print("\nAction required:")
        for s in signals:
            print(
                f"  {s['symbol']}: Place MIS SL-M BUY order "
                f"| {s['quantity']} shares "
                f"| Trigger ₹{s['entry']} "
                f"| SL ₹{s['sl']}"
            )
    print(f"{'='*55}\n")
    return signals


if __name__ == "__main__":
    run_orb_scan()