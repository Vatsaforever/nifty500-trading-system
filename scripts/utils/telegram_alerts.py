import os
import requests
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def send_telegram(message):
    """
    Sends a Telegram message via Bot API.
    Returns True if successful, False otherwise.
    """
    if not TOKEN or not CHAT_ID:
        print("  Telegram not configured — "
              "add TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to .env")
        return False

    try:
        response = requests.get(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            params={
                "chat_id":    CHAT_ID,
                "text":       message,
                "parse_mode": "Markdown"
            },
            timeout=10
        )
        if response.status_code == 200:
            print(f"  ✅ Telegram sent: {message[:60]}...")
            return True
        else:
            print(f"  ❌ Telegram failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"  ❌ Telegram error: {e}")
        return False


# Alias so existing code calling send_whatsapp() still works
def send_whatsapp(message):
    return send_telegram(message)


def _now():
    return datetime.now().strftime("%d %b %Y %H:%M IST")


# ═══════════════════════════════════════════════
# PULLBACK SYSTEM ALERTS
# ═══════════════════════════════════════════════

def alert_wl(symbol, company, rsi, support_zone):
    msg = (
        f"🔍 *PULLBACK — Watchlist Alert*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Symbol:       `{symbol}` ({company})\n"
        f"RSI (5):      {rsi}\n"
        f"Support Zone: ₹{support_zone}\n"
        f"Action:       Monitor for 60m signal\n"
        f"Time:         {_now()}"
    )
    return send_telegram(msg)


def alert_entry_initial(symbol, entry, sl, tp, qty, risk):
    msg = (
        f"🎯 *PULLBACK — Entry Signal*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Symbol:   `{symbol}`\n"
        f"Entry:    ₹{entry}\n"
        f"Stop:     ₹{sl}\n"
        f"Target:   ₹{tp} (1.5R)\n"
        f"Qty:      {qty} shares\n"
        f"Risk:     ₹{risk}\n"
        f"Order:    CNC SL-M in Zerodha\n"
        f"Time:     {_now()}"
    )
    return send_telegram(msg)


def alert_entry_updated(symbol, old_entry, new_entry,
                         old_sl, new_sl, new_tp, new_qty):
    msg = (
        f"🔄 *PULLBACK — Entry Updated*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Symbol:  `{symbol}`\n"
        f"Entry:   ₹{old_entry} → ₹{new_entry}\n"
        f"Stop:    ₹{old_sl} → ₹{new_sl}\n"
        f"Target:  ₹{new_tp}\n"
        f"Qty:     {new_qty} shares\n"
        f"Action:  Modify your Zerodha CNC order\n"
        f"Time:    {_now()}"
    )
    return send_telegram(msg)


def alert_buy_confirmed(symbol, fill_price, sl, tp, qty):
    msg = (
        f"✅ *PULLBACK — Trade Confirmed Open*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Symbol:  `{symbol}`\n"
        f"Fill:    ₹{fill_price}\n"
        f"Stop:    ₹{sl}\n"
        f"Target:  ₹{tp}\n"
        f"Qty:     {qty} shares\n"
        f"Time:    {_now()}"
    )
    return send_telegram(msg)


def alert_tp_hit(symbol, exit_price, pnl, r_multiple):
    msg = (
        f"🏆 *PULLBACK — Take Profit Hit*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Symbol:  `{symbol}`\n"
        f"Exit:    ₹{exit_price}\n"
        f"P&L:     ₹{pnl:,.0f}\n"
        f"R:       {r_multiple}R\n"
        f"Action:  Close position in Zerodha\n"
        f"Time:    {_now()}"
    )
    return send_telegram(msg)


def alert_sl_hit(symbol, exit_price, pnl):
    msg = (
        f"🛑 *PULLBACK — Stop Loss Hit*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Symbol:  `{symbol}`\n"
        f"Exit:    ₹{exit_price}\n"
        f"P&L:     ₹{pnl:,.0f}\n"
        f"R:       -1.0R\n"
        f"Action:  Close position in Zerodha\n"
        f"Time:    {_now()}"
    )
    return send_telegram(msg)


def alert_ema_exit(symbol, ema9, ema21, current_price):
    msg = (
        f"⚠️ *PULLBACK — EMA Exit Alert*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Symbol:  `{symbol}`\n"
        f"EMA9:    {ema9} crossed below EMA21: {ema21}\n"
        f"Price:   ₹{current_price}\n"
        f"Action:  Consider closing position\n"
        f"Note:    Advisory only — no auto-close\n"
        f"Time:    {_now()}"
    )
    return send_telegram(msg)


def alert_order_gap_up(symbol, entry, open_price):
    msg = (
        f"❌ *PULLBACK — Setup Invalidated*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Symbol:  `{symbol}`\n"
        f"Reason:  Gap up above entry\n"
        f"Entry:   ₹{entry}\n"
        f"Opened:  ₹{open_price}\n"
        f"Action:  Cancel your Zerodha CNC order\n"
        f"Time:    {_now()}"
    )
    return send_telegram(msg)


def alert_dropped_from_wl(symbol):
    msg = (
        f"🚫 *PULLBACK — Dropped from Watchlist*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Symbol:  `{symbol}`\n"
        f"Reason:  No longer qualifies for weekly scan\n"
        f"Action:  Cancel pending Zerodha order if any\n"
        f"Time:    {_now()}"
    )
    return send_telegram(msg)


# ═══════════════════════════════════════════════
# ORB SYSTEM ALERTS
# ═══════════════════════════════════════════════

def alert_orb_signal(symbol, entry, sl, tp, qty,
                      risk, or_high, or_low, range_pct):
    msg = (
        f"🚀 *ORB — Entry Signal*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Symbol:    `{symbol}`\n"
        f"OR High:   ₹{or_high} | OR Low: ₹{or_low}\n"
        f"Range:     {range_pct}%\n"
        f"Entry:     ₹{entry} (MIS SL-M)\n"
        f"Stop:      ₹{sl}\n"
        f"Target:    ₹{tp} (1.5R)\n"
        f"Qty:       {qty} shares\n"
        f"Risk:      ₹{risk}\n"
        f"Exit by:   3:15 PM today\n"
        f"Order:     MIS SL-M in Zerodha\n"
        f"Time:      {_now()}"
    )
    return send_telegram(msg)


def alert_orb_tp_hit(symbol, exit_price, pnl, r_multiple):
    msg = (
        f"🏆 *ORB — Take Profit Hit*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Symbol:  `{symbol}`\n"
        f"Exit:    ₹{exit_price}\n"
        f"P&L:     ₹{pnl:,.0f}\n"
        f"R:       {r_multiple}R\n"
        f"Action:  Close MIS position in Zerodha\n"
        f"Time:    {_now()}"
    )
    return send_telegram(msg)


def alert_orb_sl_hit(symbol, exit_price, pnl):
    msg = (
        f"🛑 *ORB — Stop Loss Hit*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Symbol:  `{symbol}`\n"
        f"Exit:    ₹{exit_price}\n"
        f"P&L:     ₹{pnl:,.0f}\n"
        f"R:       -1.0R\n"
        f"Action:  Close MIS position in Zerodha\n"
        f"Time:    {_now()}"
    )
    return send_telegram(msg)


def alert_orb_eod_exit(symbol, exit_price, pnl, r_multiple):
    msg = (
        f"🕒 *ORB — EOD Exit*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Symbol:  `{symbol}`\n"
        f"Exit:    ₹{exit_price} (3:15 PM close)\n"
        f"P&L:     ₹{pnl:,.0f}\n"
        f"R:       {r_multiple}R\n"
        f"Action:  MIS auto-squares at 3:20 PM\n"
        f"Time:    {_now()}"
    )
    return send_telegram(msg)


def alert_orb_gap_up(symbol, entry, open_price):
    msg = (
        f"❌ *ORB — Signal Invalidated*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Symbol:  `{symbol}`\n"
        f"Reason:  Opened above entry level\n"
        f"Entry:   ₹{entry}\n"
        f"Opened:  ₹{open_price}\n"
        f"Action:  Do not place order today\n"
        f"Time:    {_now()}"
    )
    return send_telegram(msg)


# ═══════════════════════════════════════════════
# SYSTEM ALERTS
# ═══════════════════════════════════════════════

def alert_kite_auth_reminder():
    msg = (
        f"⏰ *Daily Reminder*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Run kite\\_auth.py before market open\n"
        f"Command: `python scripts\\data_fetch\\kite_auth.py`\n"
        f"Market opens: 9:15 AM IST"
    )
    return send_telegram(msg)


def alert_universe_refresh_due(days_left):
    msg = (
        f"🌐 *Universe Refresh Due*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Days remaining: {days_left}\n"
        f"Action: Download latest Nifty 500 list from NSE\n"
        f"        and run build\\_universe.py"
    )
    return send_telegram(msg)


# ═══════════════════════════════════════════════
# TEST
# ═══════════════════════════════════════════════

if __name__ == "__main__":
    print("Testing Telegram alerts...\n")

    print("1. Pullback WL alert:")
    alert_wl("LT", "Larsen & Toubro", 20.16, 3987.76)

    print("2. Pullback entry alert:")
    alert_entry_initial("LT", 4050.0, 3980.0, 4155.0, 35, 2500)

    print("3. ORB entry alert:")
    alert_orb_signal(
        "HDFCBANK", 1820.0, 1805.0, 1842.5,
        13, 2500, 1818.0, 1805.0, 0.72
    )

    print("4. ORB EOD exit:")
    alert_orb_eod_exit("HDFCBANK", 1835.0, 1950.0, 0.83)

    print("\nCheck your Telegram for 4 messages.")