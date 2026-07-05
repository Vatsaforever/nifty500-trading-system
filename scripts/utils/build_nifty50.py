import sys
import pandas as pd
sys.path.append(".")

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

# Load sector info from existing Nifty 500 universe
nifty500 = pd.read_csv('data/universe/nifty500.csv')
sector_map = nifty500.set_index('symbol')['sector'].to_dict()
company_map = nifty500.set_index('symbol')['yf_symbol'].to_dict()

rows = []
for symbol in NIFTY50:
    rows.append({
        'symbol':    symbol,
        'yf_symbol': company_map.get(symbol, symbol + '.NS'),
        'exchange':  'NSE',
        'sector':    sector_map.get(symbol, ''),
        'notes':     'Nifty 50',
        'active':    True
    })

df = pd.DataFrame(rows)
df.to_csv('data/universe/nifty50.csv', index=False)
print(f"Nifty 50 universe file created: {len(df)} symbols")
print(df.to_string(index=False))