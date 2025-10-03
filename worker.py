import os
import time
import requests
import psycopg2
from datetime import datetime

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
WEB_URL = os.environ.get("WEB_URL", "")
SUBSCRIBERS_KEY = os.environ.get("SUBSCRIBERS_KEY", "")
DATABASE_URL = os.environ.get("DATABASE_URL", "")
FREQUENCY = int(os.environ.get("FREQUENCY", "60"))

TRC20_ADDRESS = os.environ.get("TRC20_ADDRESS", "")
BEP20_ADDRESS = os.environ.get("BEP20_ADDRESS", "")
TRON_API_KEY = os.environ.get("TRON_API_KEY", "")
BSCSCAN_API_KEY = os.environ.get("BSCSCAN_API_KEY", "")
ADMIN_CHAT_IDS = [c.strip() for c in os.environ.get("ADMIN_CHAT_IDS", "").split(",") if c.strip()]

# Contracts
USDT_TRC20_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
USDT_BEP20_CONTRACT = "0x55d398326f99059fF775485246999027B3197955"

def get_conn():
    return psycopg2.connect(DATABASE_URL, sslmode="require")

def get_subscribers():
    try:
        url = f"{WEB_URL}/subscribers?key={SUBSCRIBERS_KEY}"
        r = requests.get(url, timeout=10)
        print("Fetch subscribers response:", r.text)
        return r.json()
    except Exception as e:
        print("fetch_subscribers error:", e)
        return []

def send_message(cid, text):
    resp = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={"chat_id": cid, "text": text}
    )
    print(f"Send to {cid}, response:", resp.text)

def build_signal():
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    return f"📊 BTC SIGNAL TEST at {now}"

def save_payment(tx_hash, network, from_addr, to_addr, amount):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO payments (tx_hash, network, from_addr, to_addr, amount)
                VALUES (%s,%s,%s,%s,%s)
                ON CONFLICT DO NOTHING;
            """, (tx_hash, network, from_addr, to_addr, amount))
        conn.commit()

def check_trc20_usdt():
    if not TRC20_ADDRESS or not TRON_API_KEY:
        return
    print("Checking TRC20 for", TRC20_ADDRESS)
    url = f"https://api.trongrid.io/v1/accounts/{TRC20_ADDRESS}/transactions/trc20"
    params = {"limit": 5, "contract_address": USDT_TRC20_CONTRACT}
    headers = {"TRON-PRO-API-KEY": TRON_API_KEY}
    r = requests.get(url, params=params, headers=headers, timeout=15)
    print("TRON API response:", r.text)
    data = r.json()
    for tx in data.get("data", []):
        txid = tx.get("transaction_id")
        to_addr = tx.get("to")
        from_addr = tx.get("from")
        value = int(tx.get("value", 0))
        amount = value / (10**6)
        if to_addr.lower() == TRC20_ADDRESS.lower():
            save_payment(txid, "TRC20", from_addr, to_addr, amount)
            for admin in ADMIN_CHAT_IDS:
                send_message(admin, f"✅ New TRC20 Payment: {amount} USDT\nFrom: {from_addr}\nTx: {txid}")

def check_bep20_usdt():
    if not BEP20_ADDRESS or not BSCSCAN_API_KEY:
        return
    print("Checking BEP20 for", BEP20_ADDRESS)
    url = "https://api.bscscan.com/api/v2/account/tokentx"
    params = {
        "contractaddress": USDT_BEP20_CONTRACT,
        "address": BEP20_ADDRESS,
        "page": 1,
        "offset": 5,
        "sort": "desc",
        "apikey": BSCSCAN_API_KEY
    }
    r = requests.get(url, params=params, timeout=15)
    print("BSC API response:", r.text)
    data = r.json()
    for tx in data.get("result", []):
        txid = tx.get("hash")
        to_addr = tx.get("to")
        from_addr = tx.get("from")
        value = int(tx.get("value", "0"))
        decimals = int(tx.get("tokenDecimal", "6"))
        amount = value / (10 ** decimals)
        if to_addr.lower() == BEP20_ADDRESS.lower():
            save_payment(txid, "BEP20", from_addr, to_addr, amount)
            for admin in ADMIN_CHAT_IDS:
                send_message(admin, f"✅ New BEP20 Payment: {amount} USDT\nFrom: {from_addr}\nTx: {txid}")

def main():
    while True:
        print("Worker cycle running...")
        subs = get_subscribers()
        if subs:
            signal = build_signal()
            for cid in subs:
                send_message(cid, signal)
        else:
            print("No subscribers yet.")

        # check payments
        try:
            check_trc20_usdt()
            check_bep20_usdt()
        except Exception as e:
            print("Payment check error:", e)

        time.sleep(FREQUENCY)

if __name__ == "__main__":
    main()
