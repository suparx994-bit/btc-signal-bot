import os, time, requests, psycopg2
from datetime import datetime, timedelta

# --- Environment vars
TELEGRAM_TOKEN  = os.environ.get("TELEGRAM_TOKEN", "")
WEB_URL         = os.environ.get("WEB_URL", "")
SUBSCRIBERS_KEY = os.environ.get("SUBSCRIBERS_KEY", "")
DATABASE_URL    = os.environ.get("DATABASE_URL", "")
FREQUENCY       = int(os.environ.get("FREQUENCY", "60"))

BINANCE_BASE_URL = os.environ.get("BINANCE_BASE_URL", "https://api.binance.com")

TRC20_ADDRESS   = os.environ.get("TRC20_ADDRESS", "")
BEP20_ADDRESS   = os.environ.get("BEP20_ADDRESS", "")
TRON_API_KEY    = os.environ.get("TRON_API_KEY", "")
BSCSCAN_API_KEY = os.environ.get("BSCSCAN_API_KEY", "")

ADMIN_CHAT_IDS  = [c.strip() for c in os.environ.get("ADMIN_CHAT_IDS", "").split(",") if c.strip()]

USDT_BEP20 = "0x55d398326f99059fF775485246999027B3197955"
USDT_TRC20 = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"

# Minimal watchlist (expand later to top 100)
WATCH_SYMBOLS = ["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT"]

# --- DB
def get_conn():
    return psycopg2.connect(DATABASE_URL, sslmode="require")

# --- Subscribers
def active_subscribers():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT chat_id FROM subscriptions WHERE status='active' AND expires_at>NOW()")
            rows = cur.fetchall()
    return [r[0] for r in rows]

def pending_subscribers():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT chat_id, plan FROM subscriptions WHERE status='pending'")
            rows = cur.fetchall()
    return rows

def set_active(cid, plan):
    days = 30 if plan == "monthly" else 365
    now = datetime.utcnow()
    exp = now + timedelta(days=days)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE subscriptions
                   SET status='active', started_at=%s, expires_at=%s
                 WHERE chat_id=%s
            """, (now, exp, str(cid)))
        conn.commit()
    for admin in ADMIN_CHAT_IDS:
        send(admin, f"🎉 Subscription activated for {cid}: {plan} until {exp.date()}")

# --- Payments
def save_payment(tx_hash, network, to_addr, from_addr, amount):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
              INSERT INTO payments (tx_hash, network, to_addr, from_addr, amount)
              VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING
            """, (tx_hash, network, to_addr, from_addr, amount))
        conn.commit()

def check_bep20():
    if not (BEP20_ADDRESS and BSCSCAN_API_KEY):
        return []
    print("Checking BEP20 for", BEP20_ADDRESS)
    url = "https://api.bscscan.com/api/v2/account/tokentx"
    params = {
        "contractaddress": USDT_BEP20,
        "address": BEP20_ADDRESS,
        "page": 1, "offset": 10, "sort": "desc",
        "apikey": BSCSCAN_API_KEY
    }
    r = requests.get(url, params=params, timeout=20)
    print("BSC API response:", r.text)
    data = r.json()
    results = []
    for tx in data.get("result", []):
        if tx.get("to","").lower() == BEP20_ADDRESS.lower():
            amount = int(tx.get("value", "0")) / (10 ** int(tx.get("tokenDecimal","6")))
            results.append(("BEP20", tx["hash"], tx["to"], tx["from"], amount))
    return results

def check_trc20():
    if not (TRC20_ADDRESS and TRON_API_KEY):
        return []
    print("Checking TRC20 for", TRC20_ADDRESS)
    url = f"https://api.trongrid.io/v1/accounts/{TRC20_ADDRESS}/transactions/trc20"
    params = {"limit": 10, "contract_address": USDT_TRC20}
    headers = {"TRON-PRO-API-KEY": TRON_API_KEY}
    r = requests.get(url, params=params, headers=headers, timeout=20)
    print("TRON API response:", r.text)
    data = r.json()
    results = []
    for tx in data.get("data", []):
        if tx.get("to","").lower() == TRC20_ADDRESS.lower():
            amount = int(tx.get("value", 0))/1_000_000
            results.append(("TRC20", tx["transaction_id"], tx["to"], tx["from"], amount))
    return results

def try_activate_subscribers(new_payments):
    pendings = pending_subscribers()
    if not pendings:
        return
    for net, tx, to_addr, from_addr, amount in new_payments:
        save_payment(tx, net, to_addr, from_addr, amount)
        # simple rule: activate all pendings (MVP)
        for cid, plan in pendings:
            set_active(cid, plan)
            for admin in ADMIN_CHAT_IDS:
                send(admin, f"✅ Payment {amount} USDT on {net}\nTX: {tx}\nActivated {cid} ({plan}).")

# --- Telegram
def send(cid, text):
    resp = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={"chat_id": cid, "text": text}
    )
    print(f"Send to {cid}: {resp.text}")

# --- Market data (Binance)
def binance_close(symbol, interval="15m", limit=100):
    url = f"{BINANCE_BASE_URL}/api/v3/klines"
    r = requests.get(url, params={"symbol":symbol, "interval":interval, "limit":limit}, timeout=15)
    r.raise_for_status()
    data = r.json()
    closes = [float(c[4]) for c in data]  # close price = index 4
    return closes

def ema(values, n):
    k = 2/(n+1)
    ema_v = None
    for v in values:
        ema_v = v if ema_v is None else (v - ema_v)*k + ema_v
    return ema_v

def simple_signal(symbol):
    try:
        c15 = binance_close(symbol, "15m", 100)
        c1h = binance_close(symbol, "1h", 100)
    except Exception as e:
        print("binance error:", e)
        return f"{symbol}: data error"

    ema15_fast = ema(c15, 12); ema15_slow = ema(c15, 26)
    ema1h_fast = ema(c1h, 12); ema1h_slow = ema(c1h, 26)

    s15 = "BUY" if ema15_fast > ema15_slow else "SELL"
    s1h = "BUY" if ema1h_fast > ema1h_slow else "SELL"
    return f"{symbol}: 15m {s15} | 1h {s1h}"

# --- Main loop
def main():
    print("Worker starting…")
    while True:
        try:
            # 1) Signals to active subscribers
            actives = active_subscribers()
            if actives:
                lines = []
                for sym in WATCH_SYMBOLS:
                    lines.append(simple_signal(sym))
                text = "📈 Signals\n" + "\n".join(lines)
                for cid in actives:
                    send(cid, text)
                for admin in ADMIN_CHAT_IDS:
                    send(admin, "[mirror] " + text)
            else:
                print("No active subscribers.")

            # 2) Payments
            pays = []
            try:
                pays += check_bep20()
                pays += check_trc20()
            except Exception as e:
                print("Payment check error:", e)

            if pays:
                try_activate_subscribers(pays)

        except Exception as e:
            print("Loop error:", e)

        time.sleep(FREQUENCY)

if __name__ == "__main__":
    main()
