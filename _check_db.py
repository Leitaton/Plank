import sqlite3
conn = sqlite3.connect("/root/projects/PlankBot/plankbot.db")
conn.row_factory = sqlite3.Row
rows = conn.execute("SELECT response, COUNT(*) as cnt FROM hit_log GROUP BY response ORDER BY cnt DESC LIMIT 15").fetchall()
for r in rows:
    print(r["response"], r["cnt"])
print("---")
charged = conn.execute("SELECT COUNT(*) FROM hit_log WHERE response IN ('ORDER_PLACED','ORDER_PROCESSING')").fetchone()[0]
print("charged total:", charged)
