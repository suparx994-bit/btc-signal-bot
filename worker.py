import os, time, requests, json
import pandas as pd
import pandas_ta as ta

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")   # same token
WEB_URL        = os.environ.get("WEB_URL")          # e.g. https://your-app.onrender.com (no trailing slash)
SUBSCRIBERS_KEY= os.environ.get("SUBSCRIBERS_KEY")  # must match the Web service

def fetch_subscribers():
    try:
        r = requests.get(f"{WEB_URL}/subscribers", params={"key": SUBSCRIBERS_KEY}, timeout=10)
        r.raise_for_status()
        return r.json()  # list of chat_id strings
    except Exception as e:
        print("fetch_subscribers error:", e)
        return []

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
        f"TF: 5m (Kraken)"
    )
    return text

def send_telegram(chat_id, text):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=15,
        )
    except Exception as e:
        print("Telegram send error:", e)

if __name__ == "__main__":
    while True:
        try:
            subs = fetch_subscribers()
            if not subs:
                print("No subscribers yet.")
            else:
                text = build_signal()
                print(f"Sending to {len(subs)} subs")
                for cid in subs:
                    send_telegram(cid, text)
        except Exception as e:
            print("Worker error:", e)
        time.sleep(60)  # every 1 minute
