from flask import Flask, request, jsonify
import os, json, requests
import pandas as pd
import pandas_ta as ta

app = Flask(__name__)

USERS_FILE = "users.json"
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")  # already set on your Web service
SUBSCRIBERS_KEY = os.environ.get("SUBSCRIBERS_KEY", "change-me")  # set this in Render (Web + Worker)

def load_users():
    try:
        with open(USERS_FILE, "r") as f:
            return set(json.load(f))
    except Exception:
        return set()

def save_users(users_set):
    try:
        with open(USERS_FILE, "w") as f:
            json.dump(list(users_set), f)
    except Exception as e:
        print("save_users error:", e)

def fetch_kraken():
    url = "https://api.kraken.com/0/public/OHLC"
    params = {"pair": "BTCUSD", "interval": 5}
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    data = r.json()
    closes = [float(c[4]) for c in data["result"]["XXBTZUSD"]]
    return pd.DataFrame({"close": closes})

def build_signal():
    df = fetch_kraken()
    df["RSI_14"] = ta.rsi(df["close"], length=14)
    macd = ta.macd(df["close"], fast=12, slow=26, signal=9)
    df = pd.concat([df, macd], axis=1)
    df["EMA_50"] = ta.ema(df["close"], length=50)

    last = df.dropna().iloc[-1]
    price = last["close"]
    rsi   = last["RSI_14"]
    macd_line   = last["MACD_12_26_9"]
    macd_signal = last["MACDs_12_26_9"]
    ema   = last["EMA_50"]

    text = (
        f"Price: {price:.2f} USD\n"
        f"RSI(14): {rsi:.2f}\n"
        f"MACD: {macd_line:.2f} vs Signal {macd_signal:.2f}\n"
        f"EMA(50): {ema:.2f}\n"
        f"TF: 5m (Kraken)"
    )
    return text

@app.get("/")
def root():
    return "BTC signal bot is running (Public mode)."

@app.get("/signal")
def signal():
    return build_signal()

# --- Private endpoint the worker uses to get all subscribers
@app.get("/subscribers")
def subscribers():
    key = request.args.get("key")
    if key != SUBSCRIBERS_KEY:
        return "forbidden", 403
    users = list(load_users())
    return jsonify(users)

# --- Telegram webhook: add any user who presses Start or sends a message
@app.post("/webhook")
def telegram_webhook():
    data = request.get_json(silent=True) or {}
    msg = data.get("message") or data.get("edited_message") or {}
    chat = msg.get("chat") or {}
    cid = chat.get("id")

    if not cid:
        return "ok"

    users = load_users()
    if str(cid) not in users:
        users.add(str(cid))
        save_users(users)
        # Welcome message
        try:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": cid, "text": "Welcome! You are subscribed to BTC signals ✅"},
                timeout=15,
            )
        except Exception as e:
            print("welcome send error:", e)

    return "ok"
