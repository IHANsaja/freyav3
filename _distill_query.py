import sqlite3, json, sys

DB = r"C:\Users\IHAN HANSAJA\.local\share\mimocode\mimocode.db"
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# Phase 0: List tables
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in cur.fetchall()]
print("=== TABLES ===")
print(tables)

# List schemas
for t in tables:
    cur.execute(f"PRAGMA table_info({t})")
    cols = [r[1] for r in cur.fetchall()]
    print(f"\n--- {t} columns: {cols}")

# Sessions in last 30 days
import time
cutoff_ms = int((time.time() - 30*86400) * 1000)
print(f"\n=== SESSIONS (last 30 days, cutoff={cutoff_ms}) ===")
cur.execute("SELECT id, directory, title, time_created FROM session ORDER BY time_created DESC LIMIT 30")
for r in cur.fetchall():
    print(dict(r))

# Count messages per session
print("\n=== MESSAGE COUNT PER SESSION ===")
cur.execute("""
    SELECT m.session_id, count(*) as msg_count,
           min(m.time_created) as first_msg,
           max(m.time_created) as last_msg
    FROM message m
    WHERE m.time_created > ?
    GROUP BY m.session_id
    ORDER BY first_msg DESC
""", (cutoff_ms,))
for r in cur.fetchall():
    print(dict(r))

# Top tool calls across recent sessions
print("\n=== TOP TOOL CALLS (last 30 days) ===")
cur.execute("""
    SELECT json_extract(p.data, '$.tool') as tool,
           count(*) as n
    FROM message m
    JOIN part p ON p.message_id = m.id
    WHERE json_extract(m.data, '$.role') = 'assistant'
      AND json_extract(p.data, '$.type') = 'tool'
      AND m.time_created > ?
    GROUP BY tool
    ORDER BY n DESC
    LIMIT 30
""", (cutoff_ms,))
for r in cur.fetchall():
    print(dict(r))

# Repeated tool input patterns
print("\n=== REPEATED TOOL INPUT PATTERNS (last 30 days) ===")
cur.execute("""
    SELECT json_extract(p.data, '$.tool') as tool,
           substr(json_extract(p.data, '$.state.input'), 1, 200) as input_preview,
           count(*) as n
    FROM message m
    JOIN part p ON p.message_id = m.id
    WHERE json_extract(m.data, '$.role') = 'assistant'
      AND json_extract(p.data, '$.type') = 'tool'
      AND m.time_created > ?
    GROUP BY tool, input_preview
    HAVING n >= 2
    ORDER BY n DESC
    LIMIT 50
""", (cutoff_ms,))
for r in cur.fetchall():
    print(dict(r))

# User messages with repeat keywords
print("\n=== USER MESSAGES WITH REPEAT KEYWORDS ===")
cur.execute("""
    SELECT m.session_id, m.id as msg_id,
           substr(json_extract(m.data, '$.content'), 1, 300) as text
    FROM message m
    WHERE json_extract(m.data, '$.role') = 'user'
      AND m.time_created > ?
      AND (
        lower(json_extract(m.data, '$.content')) LIKE '%again%'
        OR lower(json_extract(m.data, '$.content')) LIKE '%every time%'
        OR lower(json_extract(m.data, '$.content')) LIKE '%like last time%'
        OR lower(json_extract(m.data, '$.content')) LIKE '%the usual%'
        OR lower(json_extract(m.data, '$.content')) LIKE '%repeat%'
        OR lower(json_extract(m.data, '$.content')) LIKE '%same as before%'
        OR lower(json_extract(m.data, '$.content')) LIKE '%always%'
        OR lower(json_extract(m.data, '$.content')) LIKE '%each time%'
        OR lower(json_extract(m.data, '$.content')) LIKE '%workflow%'
        OR lower(json_extract(m.data, '$.content')) LIKE '%routine%'
      )
    ORDER BY m.time_created DESC
    LIMIT 30
""", (cutoff_ms,))
for r in cur.fetchall():
    print(dict(r))

conn.close()
