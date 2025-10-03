import os
import json
import requests
import psycopg2
from flask import Flask, request, jsonify

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
SUBSCRIBERS_KEY = os.environ.get("SUBSCRIBERS_KEY", "")
DATABASE_URL = os.environ.get("DATABASE_URL")
TRC20_ADDRESS = os.environ.get("TRC20_ADDRESS", "")
BEP20_ADDRESS = os.environ.get("BEP20_ADDRESS", "")

# DB connect
def get_conn():
    return psycopg2.connect(DATABASE_URL, sslmode="require")

# Ensure tables
with get_conn() as conn:
    with conn.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS subscribers (
            chat_id TEXT PRIMARY KEY
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            tx_hash TEXT PRIMARY KEY,
            network TEXT,
            from_addr TEXT,
            to_addr TEXT,
            amount NUMERIC,
            ts TIMESTAMP DEFAULT NOW()
        );
        """)
    conn.commit()

# Save subscriber
def add_subscriber(chat_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO subscribers (chat_id) VALUES (%s) ON CONFLICT DO NOTHING;", (chat_id,))
        conn.commit()

@app.post("/webhook")
def telegram_webhook():
    data = request.get_json(silent=True) or {}
    print("Incoming JSON:", json.dumps(data, indent=2))  # 👈 log full payload

    msg = data.get("message") or {}
    chat = msg.get("chat") or {}
    cid = chat.get("id")
    text = (msg.get("text") or "").strip().lower()

    if cid:
        add_subscriber(str(cid))

        if text.startswith("/pay"):
            pay_msg = (
                "💳 *USDT Payment Addresses*\n"
                f"• TRC20 (TRON): `{TRC20_ADDRESS}`\n"
                f"• BEP20 (BSC): `{BEP20_ADDRESS}`\n\n"
                "Send and reply here with your TX hash if needed."
            )
            resp = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": cid, "text": pay_msg, "parse_mode": "Markdown"}
            )
            print("Telegram /pay response:", resp.text)

        elif text.startswith("/start"):
            welcome = "👋 Welcome! You are subscribed to BTC signals."
            resp = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": cid, "text": welcome}
            )
            print("Telegram /start response:", resp.text)

    return "ok"

@app.get("/subscribers")
def subscribers():
    key = request.args.get("key")
    if key != SUBSCRIBERS_KEY:
        return "forbidden", 403
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT chat_id FROM subscribers;")
            rows = cur.fetchall()
    return jsonify([r[0] for r in rows])

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
