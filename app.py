import os
import json
import requests
import psycopg2
from flask import Flask, request, jsonify

app = Flask(__name__)

# Environment variables
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
SUBSCRIBERS_KEY = os.environ.get("SUBSCRIBERS_KEY", "")
DATABASE_URL = os.environ.get("DATABASE_URL")
TRC20_ADDRESS = os.environ.get("TRC20_ADDRESS", "")
BEP20_ADDRESS = os.environ.get("BEP20_ADDRESS", "")

# Payment plans
PRICES_MONTHLY_USD = int(os.environ.get("PRICES_MONTHLY_USD", "70"))
PRICES_YEARLY_USD = int(os.environ.get("PRICES_YEARLY_USD", "500"))

# --- DB connection
def get_conn():
    return psycopg2.connect(DATABASE_URL, sslmode="require")

# --- Ensure tables exist
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
        cur.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            chat_id TEXT PRIMARY KEY,
            plan TEXT NOT NULL,                -- 'monthly' or 'yearly'
            status TEXT NOT NULL,              -- 'active', 'pending', 'expired'
            started_at TIMESTAMPTZ,
            expires_at TIMESTAMPTZ
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS assets (
            symbol TEXT PRIMARY KEY,           -- e.g. BTCUSDT
            base TEXT NOT NULL,                -- e.g. BTC
            quote TEXT NOT NULL DEFAULT 'USDT',
            rank INTEGER                       -- CMC/Coingecko rank
        );
        """)
    conn.commit()

# --- Helpers
def add_subscriber(chat_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO subscribers (chat_id) VALUES (%s) ON CONFLICT DO NOTHING;", (chat_id,))
        conn.commit()

def mark_subscription_pending(cid, plan):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO subscriptions (chat_id, plan, status, started_at, expires_at)
                VALUES (%s, %s, 'pending', NULL, NULL)
                ON CONFLICT (chat_id) DO UPDATE SET plan = EXCLUDED.plan, status='pending', started_at=NULL, expires_at=NULL
            """, (str(cid), plan))
        conn.commit()

def load_subscription_status(cid):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT plan,status,started_at,expires_at FROM subscriptions WHERE chat_id=%s", (str(cid),))
            row = cur.fetchone()
    if not row:
        return "No subscription yet. Use /plans to subscribe."
    plan, status, s, e = row
    if status == "active":
        return f"Your plan: {plan}. Status: ACTIVE. Expires: {e}."
    return f"Your plan: {plan}. Status: {status.upper()}."

def send_plans_message(cid):
    txt = (
        f"📦 *Plans*\n"
        f"• Monthly: *${PRICES_MONTHLY_USD}*\n"
        f"• Yearly: *${PRICES_YEARLY_USD}*\nChoose one:"
    )
    kb = {
        "inline_keyboard": [
            [{"text": f"Subscribe Monthly (${PRICES_MONTHLY_USD})", "callback_data": "subscribe_monthly"}],
            [{"text": f"Subscribe Yearly (${PRICES_YEARLY_USD})", "callback_data": "subscribe_yearly"}],
        ]
    }
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={"chat_id": cid, "text": txt, "parse_mode": "Markdown", "reply_markup": kb}
    )

def send_pay_message(cid):
    txt = (
        "💳 *USDT Payment Addresses*\n"
        f"• TRC20 (TRON): `{TRC20_ADDRESS}`\n"
        f"• BEP20 (BSC): `{BEP20_ADDRESS}`\n\n"
        "BTC/ETH (temporary): send to one of your own wallets we monitor.\n"
        "After payment, status changes to *active* automatically on detection."
    )
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={"chat_id": cid, "text": txt, "parse_mode": "Markdown"}
    )

# --- Telegram webhook
@app.post("/webhook")
def telegram_webhook():
    data = request.get_json(silent=True) or {}
    print("Incoming JSON:", json.dumps(data, indent=2))

    if "message" in data:
        msg = data["message"]
        chat = msg.get("chat", {})
        cid = chat.get("id")
        text = (msg.get("text") or "").strip().lower()

        if cid:
            add_subscriber(str(cid))

            if text.startswith("/start"):
                kb = {
                    "inline_keyboard": [
                        [{"text": "📦 Plans", "callback_data": "plans"}],
                        [{"text": "💳 Pay", "callback_data": "pay"}],
                        [{"text": "ℹ️ Status", "callback_data": "status"}],
                    ]
                }
                requests.post(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                    json={"chat_id": cid, "text": "👋 Welcome! Choose an option:", "reply_markup": kb}
                )

            elif text.startswith("/pay"):
                send_pay_message(cid)

            elif text.startswith("/plans"):
                send_plans_message(cid)

            else:
                requests.post(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                    json={"chat_id": cid, "text": "Type /plans or /pay to continue."}
                )

    if "callback_query" in data:
        cq = data["callback_query"]
        cid = cq["message"]["chat"]["id"]
        data_key = cq.get("data", "")

        if data_key == "plans":
            send_plans_message(cid)

        elif data_key == "pay":
            send_pay_message(cid)

        elif data_key in ("subscribe_monthly", "subscribe_yearly"):
            plan = "monthly" if data_key.endswith("monthly") else "yearly"
            mark_subscription_pending(cid, plan)
            amount = PRICES_MONTHLY_USD if plan == "monthly" else PRICES_YEARLY_USD
            txt = (
                f"✅ Selected *{plan.title()}* plan.\n"
                f"Price: *${amount}*\n\n"
                "Pay in BTC, ETH, USDT(TRC20) or USDT(BEP20).\n"
                "Once payment is detected, your subscription will activate."
            )
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": cid, "text": txt, "parse_mode": "Markdown"}
            )

        elif data_key == "status":
            st = load_subscription_status(cid)
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": cid, "text": st}
            )

    return "ok"

# --- Subscribers API (for Worker)
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
