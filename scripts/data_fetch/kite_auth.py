import os
import json
from datetime import datetime
from kiteconnect import KiteConnect
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("KITE_API_KEY")
API_SECRET = os.getenv("KITE_API_SECRET")
SESSION_FILE = "data/.kite_session.json"


def get_login_url():
    """
    Step 1 of daily auth: generates the login URL.
    Open this URL in your browser every morning before market open.
    """
    kite = KiteConnect(api_key=API_KEY)
    url = kite.login_url()
    print("\n--- KITE LOGIN ---")
    print("Open this URL in your browser:")
    print(url)
    print("\nAfter logging in, copy the full redirect URL from")
    print("your browser address bar and paste it when prompted.\n")
    return kite


def extract_request_token(redirect_url):
    """
    Pulls the request_token out of the redirect URL you paste in.
    The URL looks like: http://127.0.0.1/?request_token=xxxx&action=login&status=success
    """
    token = redirect_url.split("request_token=")[1].split("&")[0]
    return token


def generate_session(kite, request_token):
    """
    Step 2 of daily auth: exchanges request_token for access_token.
    Saves the session to a local file for use by all other scripts.
    """
    data = kite.generate_session(request_token, api_secret=API_SECRET)
    access_token = data["access_token"]

    session = {
        "access_token": access_token,
        "date": datetime.now().strftime("%Y-%m-%d")
    }
    with open(SESSION_FILE, "w") as f:
        json.dump(session, f)

    print("Session generated successfully.")
    print(f"Access token saved to {SESSION_FILE}")
    return access_token


def load_kite_client():
    """
    Used by all other scripts to get a ready-to-use Kite client.
    Reads today's saved access token from the session file.
    """
    if not os.path.exists(SESSION_FILE):
        raise FileNotFoundError(
            "No session file found. Run kite_auth.py first to generate today's session."
        )

    with open(SESSION_FILE, "r") as f:
        session = json.load(f)

    today = datetime.now().strftime("%Y-%m-%d")
    if session["date"] != today:
        raise ValueError(
            f"Session is from {session['date']}, not today ({today}). "
            "Run kite_auth.py again to refresh."
        )

    kite = KiteConnect(api_key=API_KEY)
    kite.set_access_token(session["access_token"])
    return kite


if __name__ == "__main__":
    kite = get_login_url()
    redirect_url = input("Paste the full redirect URL here: ").strip()
    request_token = extract_request_token(redirect_url)
    generate_session(kite, request_token)