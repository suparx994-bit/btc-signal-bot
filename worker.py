import os, time, requests
import pandas as pd
import pandas_ta as ta

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

# -------- Kraken fetch --------
def fetch_kraken():
    url = "https://api.kraken.com/0/public/OHLC"
    params = {"pair": "BTCUSD", "interval": 5}  # 5-minute candles
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    data = r.json()
    closes = [float(c[4]) for c in data["result"]["XXBTZUSD"]]
    return pd.DataFrame({"close": closes})

# -------- Build signal --------
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

    # Decide signal
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

# -------- Telegram --------
def send_telegram(text):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Missing TELEGRAM_TOKEN or CHAT_ID")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": CHAT_ID, "text": text}, timeout=15)
    except Exception as e:
        print("Telegram send error:", e)

# -------- Main loop --------
if __name__ == "__main__":
    while True:
        try:
            text = build_signal()
            print("Sending:", text)
            send_telegram(text)
        except Exception as e:
            print("Worker error:", e)
        time.sleep(300)  # every 5 minutes
