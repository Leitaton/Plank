"""
Plank — SQLite database layer.
Manages users, credits, plans, redeem codes, and proxies.
"""

import sqlite3
import time
import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

from config import DATABASE_PATH, DEFAULT_PLAN, PLANS

_local = threading.local()
_db_executor = ThreadPoolExecutor(max_workers=40, thread_name_prefix="db")


def _get_conn() -> sqlite3.Connection:
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA busy_timeout=5000")
        _local.conn.execute("PRAGMA synchronous=NORMAL")
        _local.conn.execute("PRAGMA cache_size=-8000")
    return _local.conn


async def run_in_db(func, *args):
    """Run a synchronous DB function in the thread pool to avoid blocking the event loop."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_db_executor, func, *args)


@contextmanager
def get_db():
    conn = _get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def init_db():
    with get_db() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id       INTEGER PRIMARY KEY,
                username      TEXT DEFAULT '',
                plan          TEXT DEFAULT 'dirt',
                credits       INTEGER DEFAULT 500,
                plan_expires  REAL DEFAULT 0,
                last_daily    REAL DEFAULT 0,
                joined_at     REAL DEFAULT 0,
                banned        INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS redeem_codes (
                code          TEXT PRIMARY KEY,
                plan          TEXT NOT NULL,
                duration_sec  INTEGER NOT NULL,
                created_by    INTEGER NOT NULL,
                created_at    REAL NOT NULL,
                redeemed_by   INTEGER DEFAULT NULL,
                redeemed_at   REAL DEFAULT NULL
            );
            CREATE TABLE IF NOT EXISTS proxies (
                proxy TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                added_at REAL,
                alive INTEGER DEFAULT 1,
                PRIMARY KEY (proxy, user_id)
            );
            CREATE TABLE IF NOT EXISTS hit_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER,
                gate        TEXT,
                card        TEXT,
                response    TEXT,
                amount      TEXT,
                site        TEXT,
                timestamp   REAL
            );
            CREATE TABLE IF NOT EXISTS mass_sessions (
                session_id    TEXT PRIMARY KEY,
                user_id       INTEGER NOT NULL,
                username      TEXT,
                gate          TEXT NOT NULL,
                total         INTEGER NOT NULL,
                processed     INTEGER NOT NULL,
                charged       INTEGER NOT NULL,
                approved      INTEGER NOT NULL,
                dead          INTEGER NOT NULL,
                error         INTEGER NOT NULL,
                stopped       INTEGER DEFAULT 0,
                site          TEXT,
                workers       INTEGER,
                cooldown      REAL,
                last_active   REAL NOT NULL,
                msg_id        INTEGER,
                chat_id       INTEGER,
                checker_name  TEXT,
                cards_json    TEXT,
                results_json  TEXT,
                proxies_json  TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_hit_log_gate ON hit_log (gate);
            CREATE INDEX IF NOT EXISTS idx_hit_log_user_id ON hit_log (user_id);
        """)


# ── User helpers ──────────────────────────────────────

def get_user(user_id: int) -> dict | None:
    with get_db() as db:
        row = db.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            return None
        user = dict(row)
        if user["plan"] != "dirt" and user["plan_expires"] > 0 and time.time() > user["plan_expires"]:
            db.execute(
                "UPDATE users SET plan='dirt', plan_expires=0, credits=? WHERE user_id=?",
                (PLANS["dirt"]["credits"], user_id),
            )
            user["plan"] = "dirt"
            user["plan_expires"] = 0
            user["credits"] = PLANS["dirt"]["credits"]
        return user


def ensure_user(user_id: int, username: str = "") -> dict:
    with get_db() as db:
        row = db.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        if row:
            user = dict(row)
            if user["plan"] != "dirt" and user["plan_expires"] > 0 and time.time() > user["plan_expires"]:
                db.execute(
                    "UPDATE users SET plan='dirt', plan_expires=0, credits=? WHERE user_id=?",
                    (PLANS["dirt"]["credits"], user_id),
                )
                user["plan"] = "dirt"
                user["plan_expires"] = 0
                user["credits"] = PLANS["dirt"]["credits"]
            
            if username and user["username"] != username:
                db.execute("UPDATE users SET username=? WHERE user_id=?", (username, user_id))
                user["username"] = username
            return user
        plan_info = PLANS[DEFAULT_PLAN]
        now = time.time()
        db.execute(
            "INSERT INTO users (user_id, username, plan, credits, joined_at) VALUES (?,?,?,?,?)",
            (user_id, username, DEFAULT_PLAN, plan_info["credits"], now),
        )
        return {
            "user_id": user_id, "username": username, "plan": DEFAULT_PLAN,
            "credits": plan_info["credits"], "plan_expires": 0,
            "last_daily": 0, "joined_at": now, "banned": 0,
        }


def set_plan(user_id: int, plan: str, duration_sec: int = 0) -> tuple[float, int, bool]:
    plan_info = PLANS.get(plan)
    if not plan_info:
        return 0.0, 0, False
    
    with get_db() as db:
        row = db.execute("SELECT plan, plan_expires, credits FROM users WHERE user_id=?", (user_id,)).fetchone()
        is_stacked = False
        if row:
            curr_plan = row["plan"]
            curr_expires = row["plan_expires"]
            curr_credits = row["credits"]
            
            if curr_plan == plan and curr_expires > time.time():
                expires = curr_expires + duration_sec
                is_stacked = True
                if plan_info["credits"] == -1 or curr_credits == -1:
                    new_credits = -1
                else:
                    new_credits = curr_credits + plan_info["credits"]
            else:
                expires = time.time() + duration_sec if duration_sec > 0 else 0
                new_credits = plan_info["credits"]
        else:
            expires = time.time() + duration_sec if duration_sec > 0 else 0
            new_credits = plan_info["credits"]
            
        db.execute(
            "UPDATE users SET plan=?, credits=?, plan_expires=? WHERE user_id=?",
            (plan, new_credits, expires, user_id),
        )
        return expires, new_credits, is_stacked


def add_credits(user_id: int, amount: int):
    with get_db() as db:
        row = db.execute("SELECT credits FROM users WHERE user_id=?", (user_id,)).fetchone()
        if row and row["credits"] == -1:
            return
        db.execute("UPDATE users SET credits = credits + ? WHERE user_id=?", (amount, user_id))


def deduct_credits(user_id: int, amount: int) -> bool:
    with get_db() as db:
        row = db.execute("SELECT credits FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            return False
        if row["credits"] == -1:
            return True
        if row["credits"] < amount:
            return False
        db.execute("UPDATE users SET credits = credits - ? WHERE user_id=?", (amount, user_id))
        return True


def get_credits(user_id: int) -> int:
    user = get_user(user_id)
    if not user:
        return 0
    return user["credits"]


def set_last_daily(user_id: int):
    with get_db() as db:
        db.execute("UPDATE users SET last_daily=? WHERE user_id=?", (time.time(), user_id))


def ban_user(user_id: int):
    with get_db() as db:
        db.execute("UPDATE users SET banned=1 WHERE user_id=?", (user_id,))


def unban_user(user_id: int):
    with get_db() as db:
        db.execute("UPDATE users SET banned=0 WHERE user_id=?", (user_id,))


def get_all_users() -> list[dict]:
    with get_db() as db:
        rows = db.execute("SELECT * FROM users").fetchall()
        return [dict(r) for r in rows]


def get_user_count() -> int:
    with get_db() as db:
        return db.execute("SELECT COUNT(*) FROM users").fetchone()[0]


# ── Redeem codes ──────────────────────────────────────

def create_redeem_code(code: str, plan: str, duration_sec: int, created_by: int):
    with get_db() as db:
        db.execute(
            "INSERT INTO redeem_codes (code, plan, duration_sec, created_by, created_at) VALUES (?,?,?,?,?)",
            (code, plan, duration_sec, created_by, time.time()),
        )


def check_redeem_code_validity(code: str) -> dict | None:
    with get_db() as db:
        row = db.execute("SELECT * FROM redeem_codes WHERE code=? AND redeemed_by IS NULL", (code,)).fetchone()
        return dict(row) if row else None


def redeem_code(code: str, user_id: int) -> dict | None:
    with get_db() as db:
        row = db.execute("SELECT * FROM redeem_codes WHERE code=? AND redeemed_by IS NULL", (code,)).fetchone()
        if not row:
            return None
        data = dict(row)
        db.execute(
            "UPDATE redeem_codes SET redeemed_by=?, redeemed_at=? WHERE code=?",
            (user_id, time.time(), code),
        )
        return data


# ── Proxies ───────────────────────────────────────────

def add_proxy(proxy: str, user_id: int):
    with get_db() as db:
        db.execute(
            "INSERT OR REPLACE INTO proxies (proxy, user_id, added_at, alive) VALUES (?,?,?,1)",
            (proxy, user_id, time.time()),
        )


def remove_proxy(proxy: str, user_id: int):
    with get_db() as db:
        db.execute("DELETE FROM proxies WHERE proxy=? AND user_id=?", (proxy, user_id))


def get_user_proxies(user_id: int, alive_only: bool = True) -> list[str]:
    with get_db() as db:
        if alive_only:
            rows = db.execute(
                "SELECT proxy FROM proxies WHERE user_id=? AND alive=1", (user_id,)
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT proxy FROM proxies WHERE user_id=?", (user_id,)
            ).fetchall()
        return [r["proxy"] for r in rows]


def get_all_proxies(alive_only: bool = True) -> list[str]:
    with get_db() as db:
        if alive_only:
            rows = db.execute("SELECT DISTINCT proxy FROM proxies WHERE alive=1").fetchall()
        else:
            rows = db.execute("SELECT DISTINCT proxy FROM proxies").fetchall()
        return [r["proxy"] for r in rows]


def set_proxy_status(proxy: str, user_id: int, alive: bool):
    with get_db() as db:
        db.execute(
            "UPDATE proxies SET alive=? WHERE proxy=? AND user_id=?",
            (1 if alive else 0, proxy, user_id),
        )


# ── Hit log ───────────────────────────────────────────

def log_hit(user_id: int, gate: str, card: str, response: str, amount: str, site: str):
    with get_db() as db:
        db.execute(
            "INSERT INTO hit_log (user_id, gate, card, response, amount, site, timestamp) VALUES (?,?,?,?,?,?,?)",
            (user_id, gate, card, response, amount, site, time.time()),
        )


def get_total_hits(gate: str = None) -> int:
    with get_db() as db:
        if gate:
            return db.execute("SELECT COUNT(*) FROM hit_log WHERE gate=?", (gate,)).fetchone()[0]
        return db.execute("SELECT COUNT(*) FROM hit_log").fetchone()[0]


# ── Mass Session Persistence ──────────────────────────

def save_mass_session(state: dict):
    import json
    with get_db() as db:
        db.execute(
            """
            INSERT OR REPLACE INTO mass_sessions (
                session_id, user_id, username, gate, total, processed, charged, approved, dead, error, stopped,
                site, workers, cooldown, last_active, msg_id, chat_id, checker_name, cards_json, results_json, proxies_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                state["id"],
                state["user_id"],
                state.get("username", ""),
                state["gate"],
                state["total"],
                state["processed"],
                state["charged"],
                state["approved"],
                state["dead"],
                state["error"],
                1 if state.get("stopped", False) else 0,
                state.get("site"),
                state.get("workers", 1),
                state.get("cooldown", 0.0),
                state.get("last_active", time.time()),
                state.get("msg_id"),
                state.get("chat_id"),
                state["checker_fn"].__name__ if hasattr(state.get("checker_fn"), "__name__") else str(state.get("checker_fn")),
                json.dumps(state.get("cards", [])),
                json.dumps(state.get("results", {})),
                json.dumps(state.get("user_proxies", []))
            )
        )


def get_mass_session(session_id: str) -> dict | None:
    import json
    with get_db() as db:
        row = db.execute("SELECT * FROM mass_sessions WHERE session_id=?", (session_id,)).fetchone()
        if not row:
            return None
        r = dict(row)
        return {
            "id": r["session_id"],
            "user_id": r["user_id"],
            "username": r["username"],
            "gate": r["gate"],
            "total": r["total"],
            "processed": r["processed"],
            "charged": r["charged"],
            "approved": r["approved"],
            "dead": r["dead"],
            "error": r["error"],
            "stopped": bool(r["stopped"]),
            "site": r["site"],
            "workers": r["workers"],
            "cooldown": r["cooldown"],
            "last_active": r["last_active"],
            "msg_id": r["msg_id"],
            "chat_id": r["chat_id"],
            "checker_name": r["checker_name"],
            "cards": json.loads(r["cards_json"] or "[]"),
            "results": json.loads(r["results_json"] or "{}"),
            "user_proxies": json.loads(r["proxies_json"] or "[]")
        }

