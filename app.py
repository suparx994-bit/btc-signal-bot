import os, time, threading, requests
import pandas as pd
import pandas_ta as ta
from flask import Flask

# ============ CONFIG ============
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID        = os.environ.get("CHAT_ID")
SYMBOL         = "bitcoin"   # CoinGecko ID
FREQUENCY_SECS = int(os.environ.get("FREQUENCY_SECS", "300"))  # every 5 minutes

app = Flask(__name__)

def fetch_coingecko():
    url = f"https://api.coingecko.com/api/v3/coins/{SYMBOL}/market_chart"
    params = {"vs_currency": "usd", "days": "1", "interval": "minute"}
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    data = r.json()
    closes = [p[1] for p in data["prices"]]
    return pd.DataFrame({"close": closes})

def build_signal():
    df = fetch_coingecko()

    # Indicators (RSI + MACD + EMA)
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

    if rsi < 30 and macd_line > macd_signal and price > ema:
        direction, emoji = "BUY", "✅"
    elif rsi > 70 and macd_line < macd_signal and price < ema:
        direction, emoji = "SELL", "❌"
    else:
        direction, emoji = "NO SIGNAL", "⚪"

    text = (
        f"{emoji} {direction}\n"
        f"Price: {price:.2f} USD\n"
        f"RSI(14): {rsi:.2f}\n"
        f"MACD: {macd_line:.2f} vs Signal {macd_signal:.2f}\n"
        f"EMA(50): {ema:.2f}\n"
        f"TF: 1m (CoinGecko)"
    )
    return text, direction

def send_telegram(text):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Missing TELEGRAM_TOKEN or CHAT_ID")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": CHAT_ID, "text": text}, timeout=15)

@app.get("/")
def root():
    return "BTC signal bot is running (CoinGecko)."

@app.get("/signal")
def manual_signal():
    text, _ = build_signal()
    return text

def worker():
    time.sleep(5)
    last_sent = None
    while True:
        try:
            text, direction = build_signal()
            # send updates
            if direction != "NO SIGNAL" or last_sent != direction:
                send_telegram(text)
            last_sent = direction
        except Exception as e:
            print("Worker error:", e)
        time.sleep(FREQUENCY_SECS)

threading.Thread(target=worker, daemon=True).start()
