import os, time, requests
import psycopg2
from decimal import Decimal
import pandas as pd
import pandas_ta as ta

# ------- ENV -------
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN")
WEB_URL          = os.environ.get("WEB_URL")              # https://your-app.onrender.com
SUBSCRIBERS_KEY  = os.environ.get("SUBSCRIBERS_KEY")
DATABASE_URL     = os.environ.get("DATABASE_URL")
FREQUENCY        = int(os.environ.get("FREQUENCY", "60")) # seconds, e.g. 60
ADMIN_CHAT_IDS   = [c.strip() for c in os.environ.get("ADMIN_CHAT_IDS", "").split(",") if c.strip()]

TRC20_ADDRESS    = os.environ.get("TRC20_ADDRESS", "")  # your TRON fixed address
BEP20_ADDRESS    = os.environ.get("BEP20_ADDRESS", "")  # your BSC fixed address
BSCSCAN_API_KEY  = os.environ.get("BSCSCAN_API_KEY", "") # free key from bscscan.com (recommended)

# USDT contracts
USDT_TRON = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"              # TRC20 USDT
USDT_BSC  = "0x55d398326f99059fF775485246999027B3197955"      # BEP20 USDT (18 decimals)

# ------- DB -------
def get_conn():
    return psycopg2.connect(DATABASE_URL, sslmode="require")

def save_payment(chain, tx_hash, token, to_addr, from_addr, amount, note=None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO payments (chain, tx_hash, token, to_address, from_address, amount, note)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (tx_hash) DO NOTHING
            """, (chain, tx_hash, token, to_addr, from_addr, Decimal(amount), note))
            conn.commit()
            return cur.rowcount  # 1 if new, 0 if duplicate

# ------- Subs -------
def fetch_subscribers():
    try:
        r = requests.get(f"{WEB_URL}/subscribers", params={"key": SUBSCRIBERS_KEY}, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print("fetch_subscribers error:", e)
        return []

# ------- Market signal -------
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
    df["RSI_14"] = pd.Series(pd.to_numeric(pd.Series(df["close"]))).ta.rsi(length=14)
    macd = df["close"].ta.macd(fast=12, slow=26, signal=9)
    df = pd.concat([df, macd], axis=1)
    df["EMA_50"] = df["close"].ta.ema(length=50)
    last = df.dropna().iloc[-1]
    price = last["close"]; rsi = last["RSI_14"]
    macd_line = last["MACD_12_26_9"]; macd_signal = last["MACDs_12_26_9"]; ema = last["EMA_50"]

    if rsi < 30 and macd_line > macd_signal and price > ema:
        direction, emoji = "BUY", "✅"
    elif rsi > 70 and macd_line < macd_signal and price < ema:
        direction, emoji = "SELL", "❌"
    else:
        direction, emoji = "NO SIGNAL", "⚪"

    return (
        f"{emoji} {direction}\n"
        f"Price: {price:.2f} USD\n"
        f"RSI(14): {rsi:.2f}\n"
        f"MACD: {macd_line:.2f} vs Signal {macd_signal:.2f}\n"
        f"EMA(50): {ema:.2f}\n"
        f"TF: 5m (Kraken)"
    )

def send_telegram(chat_id, text, markdown=False):
    payload = {"chat_id": chat_id, "text": text}
    if markdown: payload["parse_mode"] = "Markdown"
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json=payload, timeout=15)
    except Exception as e:
        print("Telegram send error:", e)

# ------- Payment checks -------
def check_trc20_usdt():
    """TronScan TRC20 transfers to our address for USDT."""
    if not TRC20_ADDRESS:
        return 0
    url = "https://apilist.tronscanapi.com/api/token_trc20/transfers"
    headers = {"User-Agent": "Mozilla/5.0"}
    params = {
        "limit": 20,
        "toAddress": TRC20_ADDRESS,
        "contract_address": USDT_TRON
    }
    try:
        r = requests.get(url, params=params, headers=headers, timeout=15)
        r.raise_for_status()
        data = r.json()
        transfers = data.get("token_transfers") or data.get("data") or []
        new_count = 0
        for t in transfers:
            tx = t.get("transaction_id") or t.get("hash") or ""
            to_addr = (t.get("to_address") or t.get("to") or "").strip()
            from_addr = (t.get("from_address") or t.get("from") or "").strip()
            # amount handling: prefer normalized if present
            amount_str = t.get("amount_str")
            if amount_str:
                amount = Decimal(amount_str)
            else:
                # raw value with decimals
                raw = t.get("value") or t.get("quant") or "0"
                dec = int(t.get("tokenDecimal") or t.get("token_info", {}).get("decimals") or 6)
                amount = Decimal(raw) / (Decimal(10) ** dec)

            if to_addr.lower() == TRC20_ADDRESS.lower() and tx:
                inserted = save_payment("TRC20", tx, "USDT", to_addr, from_addr, amount)
                if inserted:
                    new_count += 1
                    note = f"🟢 New USDT deposit (TRC20)\nAmount: {amount} USDT\nFrom: {from_addr}\nTo: {to_addr}\nTX: {tx}"
                    for admin in ADMIN_CHAT_IDS or []:
                        send_telegram(admin, note)
        return new_count
    except Exception as e:
        print("TRC20 check error:", e)
        return 0

def check_bep20_usdt():
    """BscScan BEP20 transfers to our address for USDT (18 decimals)."""
    if not BEP20_ADDRESS:
        return 0
    if not BSCSCAN_API_KEY:
        print("BEP20 check skipped: missing BSCSCAN_API_KEY")
        return 0
    url = "https://api.bscscan.com/api"
    params = {
        "module": "account",
        "action": "tokentx",
        "contractaddress": USDT_BSC,
        "address": BEP20_ADDRESS,
        "page": 1,
        "offset": 20,
        "sort": "desc",
        "apikey": BSCSCAN_API_KEY
    }
    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        js = r.json()
        txs = js.get("result") or []
        new_count = 0
        for t in txs:
            tx = t.get("hash")
            to_addr = (t.get("to") or "").strip()
            from_addr = (t.get("from") or "").strip()
            raw = t.get("value", "0")
            dec = int(t.get("tokenDecimal") or 18)  # USDT on BSC uses 18 decimals
            amount = Decimal(raw) / (Decimal(10) ** dec)
            if to_addr.lower() == BEP20_ADDRESS.lower() and tx:
                inserted = save_payment("BEP20", tx, "USDT", to_addr, from_addr, amount)
                if inserted:
                    new_count += 1
                    note = f"🟢 New USDT deposit (BEP20)\nAmount: {amount} USDT\nFrom: {from_addr}\nTo: {to_addr}\nTX: {tx}"
                    for admin in ADMIN_CHAT_IDS or []:
                        send_telegram(admin, note)
        return new_count
    except Exception as e:
        print("BEP20 check error:", e)
        return 0

# ------- Main loop -------
if __name__ == "__main__":
    print("Worker starting; WEB_URL:", WEB_URL)
    while True:
        try:
            # 1) Send market status every minute
            subs = fetch_subscribers()
            if subs:
                text = build_signal()
                for cid in subs:
                    send_telegram(cid, text)
            else:
                print("No subscribers yet.")

            # 2) Check payments on both chains each cycle
            n1 = check_trc20_usdt()
            n2 = check_bep20_usdt()
            if (n1 + n2) > 0:
                print(f"New payments recorded: {n1 + n2}")
        except Exception as e:
            print("Worker error:", e)

        time.sleep(FREQUENCY)
