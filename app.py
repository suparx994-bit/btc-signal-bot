from flask import Flask, request, jsonify
import os, requests, json
import psycopg2
from psycopg2.extras import RealDictCursor
import pandas as pd
import pandas_ta as ta

app = Flask(__name__)

# ------- ENV -------
TELEGRAM_TOKEN  = os.environ.get("TELEGRAM_TOKEN")
SUBSCRIBERS_KEY = os.environ.get("SUBSCRIBERS_KEY", "change-me")
DATABASE_URL    = os.environ.get("DATABASE_URL")  # postgres://...
TRC20_ADDRESS   = os.environ.get("TRC20_ADDRESS", "")  # your fixed TRON address
BEP20_ADDRESS   = os.environ.get("BEP20_ADDRESS", "")  # your fixed BSC address

# ------- DB helpers -------
def get_conn():
    return psycopg2.connect(DATABASE_URL, sslmode="require")

def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS subscribers (
                    chat_id TEXT PRIMARY KEY
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS payments (
                    id SERIAL PRIMARY KEY,
                    chain TEXT NOT NULL,
                    tx_hash TEXT NOT NULL UNIQUE,
                    token TEXT NOT NULL,
                    to_address TEXT NOT NULL,
                    from_address TEXT,
                    amount NUMERIC(38, 12) NOT NULL,
                    ts TIMESTAMPTZ DEFAULT NOW(),
                    note TEXT
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS kv (
                    k TEXT PRIMARY KEY,
                    v TEXT
                );
            """)
            conn.commit()

def add_subscriber(chat_id: str):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO subscribers (chat_id) VALUES (%s) ON CONFLICT DO NOTHING", (chat_id,))
            conn.commit()

def get_subscribers():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT chat_id FROM subscribers")
            return [row[0] for row in cur.fetchall()]

# ------- Market signal (unchanged) -------
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
    price = last["close"]; rsi = last["RSI_14"]
    macd_line = last["MACD_12_26_9"]; macd_signal = last["MACDs_12_26_9"]; ema = last["EMA_50"]
    return (
        f"Price: {price:.2f} USD\n"
        f"RSI(14): {rsi:.2f}\n"
        f"MACD: {macd_line:.2f} vs Signal {macd_signal:.2f}\n"
        f"EMA(50): {ema:.2f}\n"
        f"TF: 5m (Kraken)"
    )

# ------- Routes -------
@app.get("/")
def root():
    return "BTC signal bot is running (public + payments)."

@app.get("/signal")
def signal():
    return build_signal()

@app.get("/subscribers")
def subscribers():
    key = request.args.get("key")
    if key != SUBSCRIBERS_KEY:
        return "forbidden", 403
    return jsonify(get_subscribers())

# Telegram webhook: save user + reply to /pay
@app.post("/webhook")
def telegram_webhook():
    data = request.get_json(silent=True) or {}
    msg = data.get("message") or data.get("edited_message") or {}
    chat = msg.get("chat") or {}
    cid = chat.get("id")
    text = (msg.get("text") or "").strip().lower()

    if cid:
        add_subscriber(str(cid))

        if text == "/pay":
            pay_msg = (
                "💳 *USDT Payment Addresses*\n"
                f"• TRC20 (TRON): `{TRC20_ADDRESS}`\n"
                f"• BEP20 (BSC): `{BEP20_ADDRESS}`\n\n"
                "Send and reply here with your TX hash if needed."
            )
            try:
                requests.post(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                    json={"chat_id": cid, "text": pay_msg, "parse_mode": "Markdown"},
                    timeout=15,
                )
            except Exception as e:
                print("send /pay error:", e)
        elif text in ("/start", "start"):
            welcome = "Welcome! You are subscribed to BTC signals ✅\nType /pay to see payment addresses."
            try:
                requests.post(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                    json={"chat_id": cid, "text": welcome},
                    timeout=15,
                )
            except Exception as e:
                print("welcome send error:", e)

    return "ok"

# init DB on cold start
init_db()
