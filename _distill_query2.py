import sqlite3, json, time

DB = r"C:\Users\IHAN HANSAJA\.local\share\mimocode\mimocode.db"
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# All sessions ever
print("=== ALL SESSIONS ===")
cur.execute("SELECT id, directory, title, time_created FROM session ORDER BY time_created DESC")
for r in cur.fetchall():
    print(dict(r))

# All tasks
print("\n=== ALL TASKS ===")
cur.execute("SELECT id, session_id, status, summary, created_at FROM task ORDER BY created_at DESC LIMIT 30")
for r in cur.fetchall():
    print(dict(r))

# All workflow runs
print("\n=== ALL WORKFLOW RUNS ===")
cur.execute("SELECT id, session_id, name, status, running, succeeded, failed, time_created FROM workflow_run ORDER BY time_created DESC LIMIT 20")
for r in cur.fetchall():
    print(dict(r))

# All todo items
print("\n=== ALL TODOS ===")
cur.execute("SELECT session_id, content, status FROM todo ORDER BY time_created DESC LIMIT 20")
for r in cur.fetchall():
    print(dict(r))

# Actor registry (subagents)
print("\n=== ACTOR REGISTRY ===")
cur.execute("SELECT session_id, actor_id, mode, agent, description, turn_count, last_outcome FROM actor_registry ORDER BY time_created DESC LIMIT 20")
for r in cur.fetchall():
    print(dict(r))

# Projects
print("\n=== PROJECTS ===")
cur.execute("SELECT id, worktree, name, time_created FROM project ORDER BY time_created DESC")
for r in cur.fetchall():
    print(dict(r))

# Memory FTS
print("\n=== MEMORY FTS (index contents) ===")
cur.execute("SELECT id, path, scope, scope_id, type, substr(body, 1, 200) as body_preview FROM memory_fts ORDER BY last_indexed_at DESC LIMIT 20")
for r in cur.fetchall():
    print(dict(r))

# Check all sessions by directory to understand project coverage
print("\n=== SESSIONS BY DIRECTORY ===")
cur.execute("SELECT directory, count(*) as n, min(time_created) as first, max(time_created) as last FROM session GROUP BY directory ORDER BY last DESC")
for r in cur.fetchall():
    print(dict(r))

# User messages (all, not just keyword-matched)
print("\n=== RECENT USER MESSAGES (all sessions) ===")
cur.execute("""
    SELECT m.session_id,
           substr(json_extract(m.data, '$.content'), 1, 300) as text,
           m.time_created
    FROM message m
    WHERE json_extract(m.data, '$.role') = 'user'
    ORDER BY m.time_created DESC
    LIMIT 30
""")
for r in cur.fetchall():
    d = dict(r)
    print(f"[{d['session_id']}] {d['text']}")

conn.close()
