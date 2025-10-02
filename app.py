from flask import Flask
import requests, pandas as pd, pandas_ta as ta

app = Flask(__name__)

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
    rsi = last["RSI_14"]
    macd_line = last["MACD_12_26_9"]
    macd_signal = last["MACDs_12_26_9"]
    ema = last["EMA_50"]

    return (
        f"Price: {price:.2f} USD\n"
        f"RSI(14): {rsi:.2f}\n"
        f"MACD: {macd_line:.2f} vs Signal {macd_signal:.2f}\n"
        f"EMA(50): {ema:.2f}\n"
        f"TF: 5m (Kraken)"
    )

@app.get("/")
def root():
    return "BTC signal bot is running (Kraken)."

@app.get("/signal")
def signal():
    return build_signal()
