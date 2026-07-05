import sys
import os
import math
import pandas as pd
from datetime import datetime
sys.path.append(".")

from scripts.data_fetch.kite_auth import load_kite_client
from scripts.data_fetch.fetch_daily import fetch_daily_kite, load_instrument_map
from scripts.data_fetch.fetch_intraday_60m import fetch_intraday_60m
from scripts.backtest.backtest_orb import run_orb_backtest_on_symbol

NIFTY50 = [
    'RELIANCE', 'TCS', 'HDFCBANK', 'BHARTIARTL', 'ICICIBANK',
    'INFY', 'SBIN', 'LICI', 'HINDUNILVR', 'ITC',
    'BAJFINANCE', 'KOTAKBANK', 'LT', 'HCLTECH', 'MARUTI',
    'AXISBANK', 'ASIANPAINT', 'TITAN', 'NTPC', 'ONGC',
    'POWERGRID', 'ULTRACEMCO', 'WIPRO', 'ADANIENT', 'JSWSTEEL',
    'TATAMOTORS', 'INDUSINDBK', 'HINDALCO', 'DRREDDY', 'SUNPHARMA',
    'COALINDIA', 'TECHM', 'BAJAJFINSV', 'TATACONSUM', 'DIVISLAB',
    'GRASIM', 'BRITANNIA', 'APOLLOHOSP', 'CIPLA', 'EICHERMOT',
    'BPCL', 'NESTLEIND', 'HEROMOTOCO', 'BAJAJ-AUTO', 'TATAPOWER',
    'ADANIPORTS', 'SBILIFE', 'HDFCLIFE', 'TATASTEEL', 'M&M'
]

BACKTEST_CAPITAL   = 1_000_000
BACKTEST_RISK      = BACKTEST_CAPITAL * 0.0025
MAX_POSITION_VALUE = 100_000

print(f"\n{'='*60}")
print(f"ORB NIFTY 50 — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print(f"{'='*60}\n")

kite = load_kite_client()
imap = load_instrument_map()

all_trades = []
errors = 0
skipped = 0

for i, symbol in enumerate(NIFTY50):
    try:
        print(f"[{i+1}/{len(NIFTY50)}] {symbol}", end=" ... ")
        if symbol not in imap.index:
            print("Not in map")
            skipped += 1
            continue
        daily_df = fetch_daily_kite(symbol, kite=kite, instrument_map=imap)
        df_60m   = fetch_intraday_60m(symbol, kite=kite, instrument_map=imap)
        if df_60m.empty or len(df_60m) < 10:
            print("Skipped")
            skipped += 1
            continue
        trades = run_orb_backtest_on_symbol(symbol, daily_df, df_60m)
        if trades:
            all_trades.extend(trades)
            w = sum(1 for t in trades if t['r_multiple'] > 0)
            l = len(trades) - w
            p = sum(t['pnl_rupees'] for t in trades)
            print(f"✅ {len(trades)} trades | {w}W {l}L | ₹{p:,.0f}")
        else:
            print("— No trades")
    except Exception as e:
        print(f"ERROR — {e}")
        errors += 1

if not all_trades:
    print("No trades generated.")
else:
    df = pd.DataFrame(all_trades)
    df['entry_time'] = pd.to_datetime(df['entry_time'])
    df['exit_time']  = pd.to_datetime(df['exit_time'])
    df = df.sort_values('entry_time').reset_index(drop=True)

    # ── UNCONSTRAINED ALL ──
    total    = len(df)
    wins     = len(df[df['r_multiple'] > 0])
    losses   = total - wins
    wr       = round(wins/total*100,1)
    pnl      = round(df['pnl_rupees'].sum(),2)
    charges  = total * 75
    net      = pnl - charges
    gw       = df[df['pnl_rupees']>0]['pnl_rupees'].sum()
    gl       = abs(df[df['pnl_rupees']<0]['pnl_rupees'].sum())
    pf       = round(gw/gl,2) if gl>0 else 0

    print(f"\n{'='*60}")
    print(f"UNCONSTRAINED — ALL EXITS (incl EOD)")
    print(f"{'='*60}")
    print(f"Total Trades:  {total} | Wins: {wins} | Losses: {losses}")
    print(f"Win Rate:      {wr}% | Profit Factor: {pf}")
    print(f"Gross P&L:     ₹{pnl:,.2f}")
    print(f"Charges:       ₹{charges:,.0f}")
    print(f"Net P&L:       ₹{net:,.2f}")
    print(f"Net Return:    {round(net/BACKTEST_CAPITAL*100,2)}%")

    by_reason = df.groupby('exit_reason').agg(
        count=('pnl_rupees','count'),
        pnl=('pnl_rupees','sum'),
        avg_r=('r_multiple','mean')
    ).round(2)
    print(f"\nBy Exit Reason:\n{by_reason.to_string()}")

    # ── DAILY CAPITAL ──
    df['trade_date'] = df['entry_time'].dt.date
    daily = df.groupby('trade_date').agg(
        trades=('position_value','count'),
        capital=('position_value','sum'),
        pnl=('pnl_rupees','sum')
    )
    print(f"\nDaily Capital (unconstrained):")
    print(f"  Days:    {len(daily)}")
    print(f"  Avg:     ₹{daily['capital'].mean():,.0f}")
    print(f"  Median:  ₹{daily['capital'].median():,.0f}")
    print(f"  Min:     ₹{daily['capital'].min():,.0f}")
    print(f"  Max:     ₹{daily['capital'].max():,.0f}")
    print(f"  +ve days:{len(daily[daily['pnl']>0])} | "
          f"-ve days:{len(daily[daily['pnl']<0])}")

    # ── CNC ONLY (remove EOD) ──
    df_cnc = df[df['exit_reason'] != 'EOD_EXIT'].copy()
    df_cnc = df_cnc.sort_values('entry_time').reset_index(drop=True)

    ct     = len(df_cnc)
    cw     = len(df_cnc[df_cnc['exit_reason']=='TP_HIT'])
    cl     = len(df_cnc[df_cnc['exit_reason']=='SL_HIT'])
    cwr    = round(cw/ct*100,1) if ct>0 else 0
    cpnl   = round(df_cnc['pnl_rupees'].sum(),2)
    cch    = ct*75
    cnet   = cpnl - cch
    cgw    = df_cnc[df_cnc['pnl_rupees']>0]['pnl_rupees'].sum()
    cgl    = abs(df_cnc[df_cnc['pnl_rupees']<0]['pnl_rupees'].sum())
    cpf    = round(cgw/cgl,2) if cgl>0 else 0
    cavgr  = round(df_cnc['r_multiple'].mean(),3)

    ds     = df_cnc.sort_values('exit_time')
    cum    = ds['pnl_rupees'].cumsum()
    rm     = cum.cummax()
    dd     = cum - rm
    mdd    = round(dd.min(),2)
    mddp   = round(mdd/BACKTEST_CAPITAL*100,2)

    print(f"\n{'='*60}")
    print(f"CNC ONLY — TP/SL EXITS (EOD REMOVED)")
    print(f"{'='*60}")
    print(f"Total Trades:  {ct} | Wins: {cw} | Losses: {cl}")
    print(f"Win Rate:      {cwr}% | Avg R: {cavgr} | PF: {cpf}")
    print(f"Gross P&L:     ₹{cpnl:,.2f}")
    print(f"Charges:       ₹{cch:,.0f}")
    print(f"Net P&L:       ₹{cnet:,.2f}")
    print(f"Net Return:    {round(cnet/BACKTEST_CAPITAL*100,2)}%")
    print(f"Max Drawdown:  ₹{mdd:,.2f} ({mddp}%)")

    # CNC capital constrained
    cur    = BACKTEST_CAPITAL
    open_t = []
    done   = []
    cskip  = 0

    for _, sig in df_cnc.iterrows():
        still = []
        for t in open_t:
            if t['exit_time'] <= sig['entry_time']:
                cur += t['pnl_rupees']
                done.append(t)
            else:
                still.append(t)
        open_t = still

        pcost = float(sig['entry']) * int(sig['quantity'])
        if pcost > cur:
            cskip += 1
            continue
        cur -= pcost
        open_t.append(sig.to_dict())

    for t in open_t:
        cur += t['pnl_rupees']
        done.append(t)

    rd     = pd.DataFrame(done)
    rct    = len(rd)
    rcw    = len(rd[rd['r_multiple']>0]) if rct>0 else 0
    rcl    = rct - rcw
    rcwr   = round(rcw/rct*100,1) if rct>0 else 0
    rcpnl  = round(rd['pnl_rupees'].sum(),2) if rct>0 else 0
    rcch   = rct*75
    rcnet  = rcpnl - rcch
    rcret  = round(rcnet/BACKTEST_CAPITAL*100,2)

    if rct > 0:
        rds    = rd.sort_values('exit_time')
        rcum   = rds['pnl_rupees'].cumsum()
        rrm    = rcum.cummax()
        rdd    = rcum - rrm
        rmdd   = round(rdd.min(),2)
        rmddp  = round(rmdd/BACKTEST_CAPITAL*100,2)
    else:
        rmdd   = 0
        rmddp  = 0

    # Peak capital CNC
    evs = []
    for _, row in df_cnc.iterrows():
        evs.append((row['entry_time'],'entry',row))
        evs.append((row['exit_time'],'exit',row))
    evs.sort(key=lambda x: x[0])
    ot2    = []
    mxtr   = 0
    mxcp   = 0
    for tm, et, row in evs:
        if et=='entry':
            ot2.append(row)
        else:
            ot2 = [t for t in ot2
                   if not (t['symbol']==row['symbol'] and
                           t['entry_time']==row['entry_time'])]
        cp = sum(float(t['entry'])*int(t['quantity']) for t in ot2)
        if len(ot2)>mxtr: mxtr=len(ot2)
        if cp>mxcp: mxcp=cp

    print(f"\n--- CNC Capital Constrained (₹10L) ---")
    print(f"Trades Taken:  {rct} | Skipped: {cskip}")
    print(f"Wins: {rcw} | Losses: {rcl} | Win Rate: {rcwr}%")
    print(f"Net P&L:       ₹{rcnet:,.2f}")
    print(f"Net Return:    {rcret}%")
    print(f"Max Drawdown:  ₹{rmdd:,.2f} ({rmddp}%)")
    print(f"Peak capital:  ₹{mxcp:,.0f} ({mxcp/BACKTEST_CAPITAL*100:.1f}%)")
    print(f"Max concurrent:{mxtr} trades")

    if rct > 0:
        print(f"\nBy Symbol (CNC constrained):")
        bys = rd.groupby('symbol').agg(
            trades=('pnl_rupees','count'),
            pnl=('pnl_rupees','sum'),
            wr=('r_multiple', lambda x: round((x>0).mean()*100,1))
        ).sort_values('pnl',ascending=False)
        print(bys.to_string())

print(f"\nErrors: {errors} | Skipped: {skipped}")