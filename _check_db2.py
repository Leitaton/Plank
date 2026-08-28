import sqlite3
conn = sqlite3.connect("/root/projects/PlankBot/plankbot.db")
conn.row_factory = sqlite3.Row

# Check responses containing ORDER or CHARGED
rows = conn.execute("SELECT DISTINCT response FROM hit_log WHERE response LIKE '%ORDER%' OR response LIKE '%CHARG%'").fetchall()
print("ORDER/CHARGED responses:", [r["response"] for r in rows])

# Check approved ones
rows2 = conn.execute("SELECT DISTINCT response FROM hit_log WHERE response IN ('3DS_REQUIRED','INSUFFICIENT_FUNDS','INVALID_CVC','DO_NOT_HONOR','PICKUP_CARD','LIMIT_EXCEEDED','AUTHENTICATION_REQUIRED')").fetchall()
print("approved responses found:", [r["response"] for r in rows2])

# Count approved
cnt = conn.execute("SELECT COUNT(*) FROM hit_log WHERE response IN ('3DS_REQUIRED','INSUFFICIENT_FUNDS','INVALID_CVC','DO_NOT_HONOR','PICKUP_CARD','LIMIT_EXCEEDED','AUTHENTICATION_REQUIRED')").fetchone()[0]
print("approved total:", cnt)

# Sample last 5 hits
rows3 = conn.execute("SELECT * FROM hit_log ORDER BY id DESC LIMIT 5").fetchall()
for r in rows3:
    print(dict(r))
