import os, time, requests, pandas as pd, pandas_ta as ta

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

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
    return f"Price {last['close']:.2f} | RSI {last['RSI_14']:.2f}"

def send_telegram(text):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Missing TELEGRAM_TOKEN or CHAT_ID")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": CHAT_ID, "text": text}, timeout=15)

if __name__ == "__main__":
    while True:
        try:
            text = build_signal()
            print("Sending:", text)
            send_telegram(text)
        except Exception as e:
            print("Worker error:", e)
        time.sleep(300)  # every 5 minutes
