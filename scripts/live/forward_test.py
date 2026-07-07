import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
import os
import math
import pandas as pd
from datetime import datetime, date, timedelta
sys.path.append(".")

from scripts.data_fetch.kite_auth import load_kite_client
from scripts.data_fetch.fetch_daily import fetch_daily_kite, load_instrument_map
from scripts.data_fetch.fetch_intraday_60m import fetch_intraday_60m
from scripts.utils.config import (
    UNIVERSE_FILE, RISK_PCT, TP_MULTIPLE,
    MAX_POSITION_VALUE, EMA_EXIT_FAST, EMA_EXIT_SLOW
)
from scripts.utils.indicators import ema
from scripts.signals.signal_engine_60m import (
    prepare_60m_indicators, is_signal_candle, compute_trade_levels
)
from scripts.signals.entry_update_logic import (
    load_active_signal, create_initial_signal,
    process_new_candle, clear_active_signal
)
from scripts.filters.weekly_trend_filter import is_weekly_uptrend
from scripts.filters.daily_oversold_filter import is_daily_oversold_at_support
from scripts.data_fetch.fetch_weekly import fetch_weekly
from scripts.sheets.sheets_writer import get_sheet_client

# ── Config ──
FT_CAPITAL_PULLBACK = 1_000_000
FT_CAPITAL_ORB      = 1_000_000
FT_RISK_PULLBACK    = FT_CAPITAL_PULLBACK * RISK_PCT
FT_RISK_ORB         = FT_CAPITAL_ORB * RISK_PCT

NIFTY50_FILE        = "data/universe/nifty50.csv"

# ORB Parameters
ORB_MIN_RANGE_PCT   = 0.003
ORB_MAX_RANGE_PCT   = 0.03
ORB_MAX_GAP_PCT     = 0.05
ORB_VOLUME_MULT     = 1.5
ORB_ENTRY_BUFFER    = 0.001


# ── Sheets helpers ──

def get_ft_pullback():
    return get_sheet_client("FT Pullback")

def get_ft_orb():
    return get_sheet_client("FT ORB")

def get_ft_summary():
    return get_sheet_client("FT Summary")


def log_pullback_trade(trade, status="OPEN"):
    ws  = get_ft_pullback()
    row = [
        trade.get('entry_date', ''),
        trade.get('symbol', ''),
        trade.get('sector', ''),
        trade.get('entry_price', ''),
        trade.get('sl', ''),
        trade.get('tp', ''),
        trade.get('quantity', ''),
        trade.get('risk_amount', ''),
        status,
        trade.get('exit_date', ''),
        trade.get('exit_price', ''),
        trade.get('exit_reason', ''),
        trade.get('pnl_rupees', ''),
        trade.get('r_multiple', ''),
        trade.get('holding_days', ''),
        trade.get('notes', '')
    ]
    ws.append_row(row)
    print(f"  📋 [FT Pullback] {trade['symbol']} logged — {status}")


def update_pullback_exit(symbol, exit_data):
    ws      = get_ft_pullback()
    records = ws.get_all_records()
    for idx, record in enumerate(records):
        if (record['symbol'] == symbol and
                record['status'] == 'OPEN'):
            row_num = idx + 2
            ws.update(f"I{row_num}",  [["CLOSED"]])
            ws.update(f"J{row_num}",  [[exit_data['exit_date']]])
            ws.update(f"K{row_num}",  [[exit_data['exit_price']]])
            ws.update(f"L{row_num}",  [[exit_data['exit_reason']]])
            ws.update(f"M{row_num}",  [[exit_data['pnl_rupees']]])
            ws.update(f"N{row_num}",  [[exit_data['r_multiple']]])
            ws.update(f"O{row_num}",  [[exit_data['holding_days']]])
            print(f"  ✅ [FT Pullback] {symbol} closed — "
                  f"{exit_data['exit_reason']} "
                  f"₹{exit_data['pnl_rupees']:,.0f}")
            return


def log_orb_trade(trade, status="OPEN"):
    ws  = get_ft_orb()
    row = [
        trade.get('trade_date', ''),
        trade.get('symbol', ''),
        trade.get('sector', ''),
        trade.get('or_high', ''),
        trade.get('or_low', ''),
        trade.get('range_pct', ''),
        trade.get('entry_price', ''),
        trade.get('sl', ''),
        trade.get('tp', ''),
        trade.get('quantity', ''),
        trade.get('risk_amount', ''),
        status,
        trade.get('exit_time', ''),
        trade.get('exit_price', ''),
        trade.get('exit_reason', ''),
        trade.get('pnl_rupees', ''),
        trade.get('r_multiple', ''),
        trade.get('notes', '')
    ]
    ws.append_row(row)
    print(f"  📋 [FT ORB] {trade['symbol']} logged — {status}")


def update_orb_exit(symbol, trade_date, exit_data):
    ws      = get_ft_orb()
    records = ws.get_all_records()
    for idx, record in enumerate(records):
        if (record['symbol'] == symbol and
                str(record['trade_date']) == str(trade_date) and
                record['status'] == 'OPEN'):
            row_num = idx + 2
            ws.update(f"L{row_num}",  [["CLOSED"]])
            ws.update(f"M{row_num}",  [[exit_data['exit_time']]])
            ws.update(f"N{row_num}",  [[exit_data['exit_price']]])
            ws.update(f"O{row_num}",  [[exit_data['exit_reason']]])
            ws.update(f"P{row_num}",  [[exit_data['pnl_rupees']]])
            ws.update(f"Q{row_num}",  [[exit_data['r_multiple']]])
            icon = "✅" if exit_data['exit_reason'] == 'TP_HIT' \
                else "❌"
            print(f"  {icon} [FT ORB] {symbol} closed — "
                  f"{exit_data['exit_reason']} "
                  f"₹{exit_data['pnl_rupees']:,.0f}")
            return


def write_summary():
    """Writes daily summary for both systems to FT Summary sheet."""
    ws      = get_ft_summary()
    today   = str(date.today())

    for system, sheet_name, capital in [
        ('Pullback', 'FT Pullback', FT_CAPITAL_PULLBACK),
        ('ORB',      'FT ORB',      FT_CAPITAL_ORB)
    ]:
        try:
            sws     = get_sheet_client(sheet_name)
            records = sws.get_all_records()
            if not records:
                continue
            df      = pd.DataFrame(records)
            total   = len(df)
            open_t  = len(df[df['status'] == 'OPEN'])
            closed  = len(df[df['status'] == 'CLOSED'])

            if closed > 0:
                closed_df = df[df['status'] == 'CLOSED'].copy()
                closed_df['pnl_rupees'] = pd.to_numeric(
                    closed_df['pnl_rupees'], errors='coerce'
                ).fillna(0)
                closed_df['r_multiple'] = pd.to_numeric(
                    closed_df['r_multiple'], errors='coerce'
                ).fillna(0)
                wins      = len(closed_df[
                    closed_df['r_multiple'] > 0
                ])
                losses    = closed - wins
                win_rate  = round(wins / closed * 100, 1)
                gross_pnl = round(
                    closed_df['pnl_rupees'].sum(), 2
                )
                net_pnl   = gross_pnl - (closed * 75)
                ret_pct   = round(net_pnl / capital * 100, 2)

                cum       = closed_df['pnl_rupees'].cumsum()
                rm        = cum.cummax()
                dd        = cum - rm
                max_dd    = round(dd.min(), 2)
            else:
                wins = losses = 0
                win_rate = gross_pnl = net_pnl = ret_pct = max_dd = 0

            ws.append_row([
                today, system, total, open_t, closed,
                wins, losses, win_rate,
                gross_pnl, net_pnl, capital,
                ret_pct, max_dd
            ])
            print(f"  📊 [FT Summary] {system} — "
                  f"{closed} closed | "
                  f"Net ₹{net_pnl:,.0f} | "
                  f"{ret_pct}%")
        except Exception as e:
            print(f"  ⚠️ Summary error for {system}: {e}")


# ── Pullback Forward Test ──

def run_pullback_forward_test(kite, imap):
    """
    Runs the pullback system forward test scan.
    Checks existing open FT trades for exits,
    then scans WL for new signals.
    """
    print(f"\n--- FT Pullback Scan ---")

    # Load active watchlist
    watchlist_dir = "data/processed/watchlist"
    if not os.path.exists(watchlist_dir):
        print("  No watchlist found.")
        return

    files = sorted([
        f for f in os.listdir(watchlist_dir)
        if f.startswith('watchlist_') and f.endswith('.csv')
    ])
    if not files:
        print("  No watchlist file found.")
        return

    wl_df      = pd.read_csv(
        os.path.join(watchlist_dir, files[-1])
    )
    sector_map = wl_df.set_index('symbol')['sector'].to_dict()

    # Check exits on open FT Pullback trades
    try:
        ws      = get_ft_pullback()
        records = ws.get_all_records()
        open_trades = [r for r in records
                       if r['status'] == 'OPEN']

        for trade in open_trades:
            symbol = trade['symbol']
            try:
                df_60m = fetch_intraday_60m(
                    symbol, kite=kite, instrument_map=imap
                )
                df     = prepare_60m_indicators(df_60m)
                df.index = df.index.tz_localize(None) \
                    if df.index.tzinfo else df.index

                latest     = df.iloc[-2]
                entry      = float(trade['entry_price'])
                sl         = float(trade['sl'])
                tp         = float(trade['tp'])
                qty        = int(trade['quantity'])
                entry_date = pd.Timestamp(trade['entry_date'])

                # Check SL
                if float(latest['low']) <= sl:
                    pnl  = round((sl - entry) * qty, 2)
                    days = (pd.Timestamp.now() - entry_date).days
                    update_pullback_exit(symbol, {
                        'exit_date':    str(date.today()),
                        'exit_price':   sl,
                        'exit_reason':  'SL_HIT',
                        'pnl_rupees':   pnl,
                        'r_multiple':   -1.0,
                        'holding_days': days
                    })
                    continue

                # Check TP
                if float(latest['high']) >= tp:
                    pnl  = round((tp - entry) * qty, 2)
                    r    = round(TP_MULTIPLE, 2)
                    days = (pd.Timestamp.now() - entry_date).days
                    update_pullback_exit(symbol, {
                        'exit_date':    str(date.today()),
                        'exit_price':   tp,
                        'exit_reason':  'TP_HIT',
                        'pnl_rupees':   pnl,
                        'r_multiple':   r,
                        'holding_days': days
                    })
                    continue

                # Check EMA exit alert
                df['ema9_x']  = ema(df['close'], EMA_EXIT_FAST)
                df['ema21_x'] = ema(df['close'], EMA_EXIT_SLOW)
                i = len(df) - 2
                ema9_prev  = df['ema9_x'].iloc[i-1]
                ema21_prev = df['ema21_x'].iloc[i-1]
                ema9_curr  = df['ema9_x'].iloc[i]
                ema21_curr = df['ema21_x'].iloc[i]
                if (ema9_prev >= ema21_prev and
                        ema9_curr < ema21_curr):
                    print(f"  ⚠️  [FT Pullback] EMA EXIT alert "
                          f"for {symbol} — consider closing")

                print(f"  📊 [FT Pullback] {symbol} open — "
                      f"Entry ₹{entry} | "
                      f"SL ₹{sl} | TP ₹{tp}")

            except Exception as e:
                print(f"  ⚠️ Exit check error {symbol}: {e}")

    except Exception as e:
        print(f"  ⚠️ Could not check open trades: {e}")

    # Scan WL for new signals
    for _, row in wl_df.iterrows():
        symbol = row['symbol']
        sector = sector_map.get(symbol, '')

        # Skip if already have open FT trade for this symbol
        try:
            ws      = get_ft_pullback()
            records = ws.get_all_records()
            if any(r['symbol'] == symbol and
                   r['status'] == 'OPEN'
                   for r in records):
                continue
        except Exception:
            pass

        try:
            df_60m = fetch_intraday_60m(
                symbol, kite=kite, instrument_map=imap
            )
            df     = prepare_60m_indicators(df_60m)
            df.index = df.index.tz_localize(None) \
                if df.index.tzinfo else df.index

            # Check last completed candle for signal
            i = len(df) - 2
            if i < 1:
                continue
            if not is_signal_candle(df, i):
                continue

            candle  = df.iloc[i]
            atr_val = float(candle['atr14'])
            levels  = compute_trade_levels(
                candle, atr_val, FT_RISK_PULLBACK
            )
            if levels is None:
                continue

            trade = {
                'entry_date':  str(date.today()),
                'symbol':      symbol,
                'sector':      sector,
                'entry_price': levels['entry'],
                'sl':          levels['sl'],
                'tp':          levels['tp'],
                'quantity':    levels['quantity'],
                'risk_amount': levels['risk_amount'],
                'notes':       'Forward test — no real order'
            }
            log_pullback_trade(trade, status='OPEN')
            print(f"  🎯 [FT Pullback] NEW signal: {symbol} | "
                  f"Entry ₹{levels['entry']} | "
                  f"SL ₹{levels['sl']} | "
                  f"TP ₹{levels['tp']}")

        except Exception as e:
            print(f"  ⚠️ Signal scan error {symbol}: {e}")


# ── ORB Forward Test ──

def run_orb_forward_test(kite, imap):
    """
    Runs the ORB system forward test.
    Checks open ORB trades for exits (EOD, TP, SL),
    then scans Nifty 50 for new ORB signals.
    """
    print(f"\n--- FT ORB Scan ---")

    if not os.path.exists(NIFTY50_FILE):
        print("  Nifty 50 file not found.")
        return

    nifty50    = pd.read_csv(NIFTY50_FILE)
    symbols    = nifty50[
        nifty50['active'] == True
    ]['symbol'].tolist()
    sector_map = nifty50.set_index('symbol')['sector'].to_dict()

    now      = datetime.now()
    is_eod   = now.hour >= 15 and now.minute >= 15

    # Check exits on open ORB trades
    try:
        ws      = get_ft_orb()
        records = ws.get_all_records()
        open_orb = [r for r in records
                    if r['status'] == 'OPEN']

        for trade in open_orb:
            symbol     = trade['symbol']
            trade_date = trade['trade_date']

            try:
                df_60m = fetch_intraday_60m(
                    symbol, kite=kite, instrument_map=imap
                )
                df     = df_60m.copy()
                df.index = df.index.tz_localize(None) \
                    if df.index.tzinfo else df.index

                today_c = df[
                    df.index.date == date.today()
                ].sort_index()

                entry = float(trade['entry_price'])
                sl    = float(trade['sl'])
                tp    = float(trade['tp'])
                qty   = int(trade['quantity'])

                exited = False
                for _, candle in today_c.iterrows():
                    # SL hit
                    if float(candle['low']) <= sl:
                        pnl = round((sl - entry) * qty, 2)
                        update_orb_exit(symbol, trade_date, {
                            'exit_time':   str(candle.name),
                            'exit_price':  sl,
                            'exit_reason': 'SL_HIT',
                            'pnl_rupees':  pnl,
                            'r_multiple':  -1.0
                        })
                        exited = True
                        break

                    # TP hit
                    if float(candle['high']) >= tp:
                        pnl = round((tp - entry) * qty, 2)
                        update_orb_exit(symbol, trade_date, {
                            'exit_time':   str(candle.name),
                            'exit_price':  tp,
                            'exit_reason': 'TP_HIT',
                            'pnl_rupees':  pnl,
                            'r_multiple':  round(TP_MULTIPLE, 2)
                        })
                        exited = True
                        break

                # EOD exit
                if not exited and is_eod and len(today_c) > 0:
                    last      = today_c.iloc[-1]
                    exit_price = float(last['close'])
                    pnl        = round(
                        (exit_price - entry) * qty, 2
                    )
                    r          = round(
                        (exit_price - entry) / (entry - sl), 2
                    ) if (entry - sl) > 0 else 0
                    update_orb_exit(symbol, trade_date, {
                        'exit_time':   str(last.name),
                        'exit_price':  exit_price,
                        'exit_reason': 'EOD_EXIT',
                        'pnl_rupees':  pnl,
                        'r_multiple':  r
                    })

                if not exited and not is_eod:
                    print(f"  📊 [FT ORB] {symbol} open — "
                          f"Entry ₹{entry} | "
                          f"SL ₹{sl} | TP ₹{tp}")

            except Exception as e:
                print(f"  ⚠️ ORB exit error {symbol}: {e}")

    except Exception as e:
        print(f"  ⚠️ Could not check ORB open trades: {e}")

    # Scan for new ORB signals (only in morning window)
    is_morning = (now.hour == 9 and now.minute >= 30) or \
                 (now.hour == 10 and now.minute <= 30)

    if not is_morning:
        print(f"  Outside ORB signal window "
              f"(9:30-10:30 AM) — skipping new signal scan")
        return

    print(f"  Scanning Nifty 50 for ORB signals...")
    for symbol in symbols:
        try:
            if symbol not in imap.index:
                continue

            daily_df = fetch_daily_kite(
                symbol, kite=kite, instrument_map=imap
            )
            df_60m   = fetch_intraday_60m(
                symbol, kite=kite, instrument_map=imap
            )

            daily_df.index = daily_df.index.tz_localize(None) \
                if daily_df.index.tzinfo else daily_df.index
            df_60m_c = df_60m.copy()
            df_60m_c.index = df_60m_c.index.tz_localize(None) \
                if df_60m_c.index.tzinfo else df_60m_c.index

            today_c  = df_60m_c[
                df_60m_c.index.date == date.today()
            ].sort_index()

            if len(today_c) < 2:
                continue

            or_candle = today_c.iloc[0]
            or_high   = float(or_candle['high'])
            or_low    = float(or_candle['low'])
            or_open   = float(or_candle['open'])
            or_close  = float(or_candle['close'])
            or_vol    = float(or_candle['volume'])

            # Prev close
            prev_days = daily_df[
                daily_df.index.date < date.today()
            ]
            if len(prev_days) < 20:
                continue
            prev_close = float(prev_days['close'].iloc[-1])
            avg_vol    = float(
                prev_days['volume'].iloc[-20:].mean()
            )

            # Filters
            gap_pct   = (or_open - prev_close) / prev_close
            if gap_pct > ORB_MAX_GAP_PCT:
                continue
            range_pct = (or_high - or_low) / or_low
            if (range_pct < ORB_MIN_RANGE_PCT or
                    range_pct > ORB_MAX_RANGE_PCT):
                continue
            if or_close <= or_open:
                continue

            # Breakout candle
            bo_candle = today_c.iloc[1]
            if float(bo_candle['high']) <= or_high:
                continue
            if float(bo_candle['volume']) < or_vol * ORB_VOLUME_MULT:
                continue

            # Weekly trend
            weekly     = daily_df['close'].resample('W').last()
            weekly_ema = weekly.ewm(span=20, adjust=False).mean()
            if len(weekly) < 30:
                continue
            if float(weekly.iloc[-1]) <= float(weekly_ema.iloc[-1]):
                continue

            # Compute levels
            entry    = round(or_high * (1 + ORB_ENTRY_BUFFER), 2)
            sl       = round(or_low, 2)
            rps      = entry - sl
            if rps <= 0:
                continue
            qty_risk = math.floor(FT_RISK_ORB / rps)
            qty_cap  = math.floor(MAX_POSITION_VALUE / entry)
            qty      = min(qty_risk, qty_cap)
            if qty == 0:
                continue
            tp = round(entry + TP_MULTIPLE * rps, 2)

            trade = {
                'trade_date':  str(date.today()),
                'symbol':      symbol,
                'sector':      sector_map.get(symbol, ''),
                'or_high':     round(or_high, 2),
                'or_low':      round(or_low, 2),
                'range_pct':   round(range_pct * 100, 2),
                'entry_price': entry,
                'sl':          sl,
                'tp':          tp,
                'quantity':    qty,
                'risk_amount': round(rps * qty, 2),
                'notes':       'Forward test — no real order'
            }
            log_orb_trade(trade, status='OPEN')
            print(f"  🚀 [FT ORB] NEW signal: {symbol} | "
                  f"Entry ₹{entry} | SL ₹{sl} | TP ₹{tp}")

        except Exception as e:
            print(f"  ⚠️ ORB scan error {symbol}: {e}")


# ── Main ──

def run_forward_test():
    print(f"\n{'='*55}")
    print(f"FORWARD TEST — "
          f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Pullback capital: ₹{FT_CAPITAL_PULLBACK:,} | "
          f"ORB capital: ₹{FT_CAPITAL_ORB:,}")
    print(f"{'='*55}")

    now = datetime.now()
    if now.weekday() > 4:
        print("Weekend — no scan.")
        return
    market_open  = now.replace(hour=9, minute=15, second=0)
    market_close = now.replace(hour=15, minute=30, second=0)
    if not (market_open <= now <= market_close):
        print("Outside market hours — no scan.")
        return

    kite = load_kite_client()
    imap = load_instrument_map()

    run_pullback_forward_test(kite, imap)
    run_orb_forward_test(kite, imap)
    write_summary()

    print(f"\n{'='*55}")
    print(f"FORWARD TEST COMPLETE")
    print(f"Check FT Pullback, FT ORB, FT Summary in Sheets")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    run_forward_test()