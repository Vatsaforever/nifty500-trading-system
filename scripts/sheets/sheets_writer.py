import sys
import os
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
from dotenv import load_dotenv
sys.path.append(".")

load_dotenv()

SHEET_ID         = os.getenv("GOOGLE_SHEET_ID")
CREDENTIALS_FILE = "google_credentials.json"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]


def get_sheet_client(tab_name):
    """
    Returns a gspread worksheet object for the given tab name.
    Handles both local (google_credentials.json) and
    Streamlit Cloud (st.secrets) environments automatically.
    """
    try:
        # Try Streamlit Cloud secrets first
        import streamlit as st
        if "google_credentials" in st.secrets:
            creds_dict = {
                "type":                        st.secrets["google_credentials"]["type"],
                "project_id":                  st.secrets["google_credentials"]["project_id"],
                "private_key_id":              st.secrets["google_credentials"]["private_key_id"],
                "private_key":                 st.secrets["google_credentials"]["private_key"],
                "client_email":                st.secrets["google_credentials"]["client_email"],
                "client_id":                   st.secrets["google_credentials"]["client_id"],
                "auth_uri":                    st.secrets["google_credentials"]["auth_uri"],
                "token_uri":                   st.secrets["google_credentials"]["token_uri"],
                "auth_provider_x509_cert_url": st.secrets["google_credentials"]["auth_provider_x509_cert_url"],
                "client_x509_cert_url":        st.secrets["google_credentials"]["client_x509_cert_url"]
            }
            creds = Credentials.from_service_account_info(
                creds_dict, scopes=SCOPES
            )
            sheet_id = st.secrets["GOOGLE_SHEET_ID"]
        else:
            raise KeyError("No streamlit secrets found")

    except Exception:
        # Fall back to local credentials file
        creds    = Credentials.from_service_account_file(
            CREDENTIALS_FILE, scopes=SCOPES
        )
        sheet_id = SHEET_ID

    client = gspread.authorize(creds)
    sheet  = client.open_by_key(sheet_id)
    return sheet.worksheet(tab_name)

def get_trading_capital():
    """
    Reads the current trading capital live from the Stats sheet cell B2.
    This is the single source of truth for capital — edit it in Sheets,
    it takes effect on the next signal evaluation automatically.
    """
    sheet   = get_sheet_client("Stats")
    capital = sheet.acell("B2").value
    if not capital:
        raise ValueError(
            "Trading capital not set in Stats sheet cell B2. "
            "Please add your capital value there first."
        )
    return float(str(capital).replace(",", "").replace("₹", "").strip())


def get_risk_amount():
    """Returns 0.25% of current trading capital."""
    from scripts.utils.config import RISK_PCT
    return get_trading_capital() * RISK_PCT


# ---------------------------------------------------------------------------
# Header definitions — one list per tab, order matches write_event() rows
# ---------------------------------------------------------------------------

SIGNALS_HEADERS = [
    "timestamp", "event_type", "symbol", "sector",
    "weekly_close", "weekly_ema20", "rsi5", "support_zone_price",
    "signal_high", "signal_low", "atr",
    "entry", "sl", "tp", "quantity", "notes"
]

TRADES_HEADERS = [
    "trade_id", "symbol", "sector", "entry_time", "entry_price",
    "sl", "tp", "quantity", "risk_amount", "status",
    "trade_taken", "actual_entry_price",
    "ema_exit_alert", "ema_exit_alert_time",
    "exit_time", "exit_price", "exit_reason",
    "pnl_rupees", "r_multiple", "holding_period", "notes"
]


def setup_sheet_headers():
    """
    Writes headers to all three tabs and sets up the Stats sheet layout.
    Run once when setting up the dashboard for the first time.
    """
    # Signals tab
    signals_ws = get_sheet_client("Signals")
    signals_ws.clear()
    signals_ws.append_row(SIGNALS_HEADERS)

    # Trades tab
    trades_ws = get_sheet_client("Trades")
    trades_ws.clear()
    trades_ws.append_row(TRADES_HEADERS)

    # Stats tab
    stats_ws = get_sheet_client("Stats")
    stats_ws.clear()
    stats_ws.update("A1", [
        # Trading Capital Panel
        ["TRADING CAPITAL"],
        ["Trading Capital (₹)",    ""],          # B2 = editable capital value
        ["Risk % per Trade",       "0.25%"],
        ["Risk Amount per Trade",  "=B2*0.0025"],
        ["Last Updated",           ""],
        [""],
        # Universe Status Panel
        ["UNIVERSE STATUS"],
        ["Last Refreshed",         ""],          # B9 = date of last refresh
        ["Next Refresh Due",       "=B9+180"],
        ["Days Till Refresh",      "=B10-TODAY()"],
        ["Status",
         '=IF(B11<=0,"🔴 Overdue",IF(B11<=14,"🟡 Due Soon","🟢 OK"))'],
        [""],
        # Performance Metrics
        ["PERFORMANCE"],
        ["Total Trades",
         "=COUNTA(Trades!A2:A)"],
        ["Win Rate",
         '=IFERROR(COUNTIF(Trades!Q2:Q,">0")/COUNTIF(Trades!J2:J,"CLOSED"),0)'],
        ["Average R",
         "=IFERROR(AVERAGE(Trades!Q2:Q),0)"],
        ["Profit Factor",
         '=IFERROR(SUMIF(Trades!P2:P,">0")/ABS(SUMIF(Trades!P2:P,"<0")),0)'],
        ["Expectancy (₹)",
         "=IFERROR(AVERAGE(Trades!P2:P),0)"],
        ["Total P&L (₹)",
         "=IFERROR(SUM(Trades!P2:P),0)"],
    ])

    print("✅ Headers and Stats layout written to all three tabs.")
    print("\nNext steps in the Stats sheet:")
    print("  1. Click cell B2 and enter your trading capital (e.g. 1000000)")
    print("  2. Click cell B9 and enter today's date as the last refresh date")


# ---------------------------------------------------------------------------
# Event writers
# ---------------------------------------------------------------------------

def write_signal_event(event_dict, sector=""):
    """
    Writes a WL, ENTRY_INITIAL, or ENTRY_UPDATED event to the Signals tab.
    """
    ws  = get_sheet_client("Signals")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    et  = event_dict.get("event_type", "")

    row = [
        now,
        et,
        event_dict.get("symbol", ""),
        sector,
        event_dict.get("weekly_close", ""),
        event_dict.get("weekly_ema20", ""),
        event_dict.get("rsi5", ""),
        event_dict.get("support_zone_price", ""),
        event_dict.get("signal_high", ""),
        event_dict.get("signal_low", ""),
        event_dict.get("atr", ""),
        event_dict.get("entry", ""),
        event_dict.get("sl", ""),
        event_dict.get("tp", ""),
        event_dict.get("quantity", ""),
        event_dict.get("notes", "")
    ]
    ws.append_row(row)
    print(f"  📋 [{et}] {event_dict.get('symbol','')} written to Signals tab.")


def write_trade_open(event_dict, sector=""):
    """
  Creates a new PENDING row in the Trades tab when a BUY event fires.
    Status starts as PENDING until you manually confirm YES or NO
    in the trade_taken column.
    """
    ws       = get_sheet_client("Trades")
    symbol   = event_dict.get("symbol", "")
    now      = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    trade_id = f"{symbol}_{now.replace(' ','_').replace(':','-')}"

    row = [
        trade_id,
        symbol,
        sector,
        now,                              # entry_time
        event_dict.get("entry", ""),
        event_dict.get("sl", ""),
        event_dict.get("tp", ""),
        event_dict.get("quantity", ""),
        event_dict.get("risk_amount", ""),
        "PENDING",                        # status — waits for confirmation
        "",                               # trade_taken — YOU fill YES or NO
        "",                               # actual_entry_price — optional
        "FALSE",                          # ema_exit_alert
        "",                               # ema_exit_alert_time
        "",                               # exit_time
        "",                               # exit_price
        "",                               # exit_reason
        "",                               # pnl_rupees
        "",                               # r_multiple
        "",                               # holding_period
        event_dict.get("notes", "")
    ]
    ws.append_row(row)
    print(f"  📈 [BUY] {symbol} trade written as PENDING — "
          f"confirm YES/NO in Trades sheet.")
    return trade_id


def write_trade_exit(symbol, exit_event):
    """
    Finds the confirmed OPEN trade row for a symbol and updates
    it with exit details. Uses actual_entry_price for P&L if available,
    otherwise falls back to the system entry_price.
    """
    ws      = get_sheet_client("Trades")
    records = ws.get_all_records()

    for idx, record in enumerate(records):
        if record["symbol"] == symbol and record["status"] == "OPEN":
            row_number = idx + 2

            entry_time   = record.get("entry_time", "")
            exit_time_dt = datetime.now()
            exit_time    = exit_time_dt.strftime("%Y-%m-%d %H:%M:%S")

            # Use actual entry price if filled in, else system entry
            actual_entry = record.get("actual_entry_price", "")
            entry_price  = float(actual_entry) if actual_entry else \
                           float(record.get("entry_price", 0))
            exit_price   = float(exit_event.get("exit_price", 0))
            quantity     = int(record.get("quantity", 0))

            # Recompute P&L and R using actual entry if available
            sl           = float(record.get("sl", 0))
            pnl          = round((exit_price - entry_price) * quantity, 2)
            r_multiple   = round((exit_price - entry_price) / \
                           (entry_price - sl), 2) if entry_price != sl else 0

            # Holding period
            try:
                entry_dt       = datetime.strptime(entry_time,
                                                    "%Y-%m-%d %H:%M:%S")
                delta          = exit_time_dt - entry_dt
                hours          = int(delta.total_seconds() // 3600)
                holding_period = f"{delta.days}d {hours % 24}h"
            except Exception:
                holding_period = ""

            # Update columns — note shifted column letters due to new columns
            ws.update(f"J{row_number}", [["CLOSED"]])   # status
            ws.update(f"O{row_number}", [[exit_time]])   # exit_time
            ws.update(f"P{row_number}", [[exit_price]])  # exit_price
            ws.update(f"Q{row_number}", [[exit_event.get("exit_reason", "")]])
            ws.update(f"R{row_number}", [[pnl]])         # pnl_rupees
            ws.update(f"S{row_number}", [[r_multiple]])  # r_multiple
            ws.update(f"T{row_number}", [[holding_period]])

            icon = "✅" if exit_event["exit_reason"] == "TP_HIT" else "❌"
            print(f"  {icon} [{exit_event['exit_reason']}] {symbol} "
                  f"closed. P&L: ₹{pnl:,}")
            return

    print(f"  ⚠️  No confirmed OPEN trade found for {symbol}.")

def write_ema_exit_alert(symbol):
    """
    Marks the EMA exit alert on the confirmed OPEN trade row.
    Does not close the trade.
    """
    ws      = get_sheet_client("Trades")
    records = ws.get_all_records()

    for idx, record in enumerate(records):
        if record["symbol"] == symbol and record["status"] == "OPEN":
            row_number = idx + 2
            now        = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ws.update(f"M{row_number}", [["TRUE"]])   # ema_exit_alert
            ws.update(f"N{row_number}", [[now]])       # ema_exit_alert_time
            print(f"  ⚠️  [EMA_EXIT] Alert logged for {symbol}.")
            return

# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------
def confirm_pending_trades():
    """
    Checks all PENDING rows in the Trades sheet.
    - If trade_taken = YES → updates status to OPEN
    - If trade_taken = NO  → updates status to SKIPPED
    - If trade_taken = blank → leaves as PENDING (still waiting)

    Called at the start of every hourly scan.
    """
    ws      = get_sheet_client("Trades")
    records = ws.get_all_records()
    updates = []

    for idx, record in enumerate(records):
        if record["status"] != "PENDING":
            continue

        row_number  = idx + 2
        trade_taken = str(record.get("trade_taken", "")).strip().upper()

        if trade_taken == "YES":
            ws.update(f"J{row_number}", [["OPEN"]])
            print(f"  ✅ [{record['symbol']}] Confirmed OPEN.")
            updates.append(record["symbol"])

        elif trade_taken == "NO":
            ws.update(f"J{row_number}", [["SKIPPED"]])
            print(f"  ⏭️  [{record['symbol']}] Marked SKIPPED.")
            updates.append(record["symbol"])

    if not updates:
        print("  No pending trades to confirm.")

    return updates


def send_buy_notification(symbol, entry, sl, tp, quantity, risk_amount):
    """
    Sends a notification when a BUY event fires so you know
    to check the Trades sheet and confirm YES or NO.

    Currently logs to console and writes to a local notification file.
    Can be extended to email later.
    """
    msg = (
        f"\n{'🔔 '*10}\n"
        f"BUY SIGNAL TRIGGERED\n"
        f"Symbol:   {symbol}\n"
        f"Entry:    ₹{entry}\n"
        f"SL:       ₹{sl}\n"
        f"TP:       ₹{tp}\n"
        f"Quantity: {quantity}\n"
        f"Risk:     ₹{risk_amount}\n"
        f"ACTION:   Open Trades sheet and type YES or NO "
        f"in the trade_taken column\n"
        f"{'🔔 '*10}\n"
    )
    print(msg)

    # Also write to a notifications log file
    os.makedirs("logs", exist_ok=True)
    with open("logs/notifications.log", "a") as f:
        f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} — "
                f"BUY {symbol} @ ₹{entry} | "
                f"SL ₹{sl} | TP ₹{tp} | Qty {quantity}\n")
        
if __name__ == "__main__":
    try:
        print("Setting up sheet headers and Stats layout...")
        setup_sheet_headers()

        print("\nTesting capital read from Stats sheet...")
        print("(Add your capital to cell B2 in the Stats tab first)")
        print("Skipping capital read test until B2 is populated.")

        print("\nTesting a sample signal write to Signals tab...")
        test_signal = {
            "event_type":    "ENTRY_INITIAL",
            "symbol":        "RELIANCE",
            "signal_high":   2965.0,
            "signal_low":    2940.0,
            "atr":           18.5,
            "entry":         2983.5,
            "sl":            2921.5,
            "tp":            3076.5,
            "quantity":      32,
            "notes":         "Test entry"
        }
        write_signal_event(test_signal, sector="Energy")

        print("\nTesting a sample trade open to Trades tab...")
        test_buy = {
            "symbol":      "RELIANCE",
            "entry":       2983.5,
            "sl":          2921.5,
            "tp":          3076.5,
            "quantity":    32,
            "risk_amount": 2500.0,
            "notes":       "Test trade"
        }
        write_trade_open(test_buy, sector="Energy")

        print("\n✅ All writes successful — check your Google Sheet.")

    except Exception as e:
        import traceback
        print(f"ERROR: {e}")
        traceback.print_exc()