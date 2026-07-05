import os
import requests
from dotenv import load_dotenv
load_dotenv()

TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

response = requests.get(
    f"https://api.telegram.org/bot{TOKEN}/sendMessage",
    params={
        "chat_id":    CHAT_ID,
        "text":       "✅ Test alert from Nifty Trading System",
        "parse_mode": "Markdown"
    }
)
print(f"Status: {response.status_code}")
print(f"Response: {response.json()}")