import sqlite3, json

DB = r"C:\Users\IHAN HANSAJA\.local\share\mimocode\mimocode.db"
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# Get all messages from Rivelo.gg sessions
print("=== RIVELO.GG SESSION MESSAGES ===")
cur.execute("""
    SELECT m.session_id, m.id, json_extract(m.data, '$.role') as role,
           json_extract(m.data, '$.content') as content,
           m.time_created
    FROM message m
    WHERE m.session_id IN (
        SELECT id FROM session WHERE directory LIKE '%Rivelo%' OR directory LIKE '%SaaS%'
    )
    ORDER BY m.time_created
""")
for r in cur.fetchall():
    d = dict(r)
    content = d.get('content')
    if content and content != 'None':
        print(f"[{d['session_id']}] {d['role']}: {str(content)[:200]}")
    else:
        # Try to get from parts
        cur2 = conn.cursor()
        cur2.execute("""
            SELECT json_extract(data, '$.type') as ptype, 
                   json_extract(data, '$.text') as text,
                   json_extract(data, '$.tool') as tool
            FROM part WHERE message_id = ?
        """, (d['id'],))
        parts = cur2.fetchall()
        if parts:
            for p in parts:
                p = dict(p)
                if p['text']:
                    print(f"[{d['session_id']}] {d['role']}: {str(p['text'])[:200]}")
                elif p['tool']:
                    print(f"[{d['session_id']}] {d['role']}: [tool: {p['tool']}]")

# Check immersive-portfolio session
print("\n=== IMMERSIVE-PORTFOLIO SESSION MESSAGES ===")
cur.execute("""
    SELECT m.session_id, m.id, json_extract(m.data, '$.role') as role,
           json_extract(m.data, '$.content') as content,
           m.time_created
    FROM message m
    WHERE m.session_id = 'ses_115a82a53ffedy7SrbQNsNNMLn'
    ORDER BY m.time_created
""")
for r in cur.fetchall():
    d = dict(r)
    content = d.get('content')
    if content and content != 'None':
        print(f"[{d['session_id']}] {d['role']}: {str(content)[:200]}")
    else:
        cur2 = conn.cursor()
        cur2.execute("""
            SELECT json_extract(data, '$.type') as ptype, 
                   json_extract(data, '$.text') as text,
                   json_extract(data, '$.tool') as tool
            FROM part WHERE message_id = ?
        """, (d['id'],))
        parts = cur2.fetchall()
        if parts:
            for p in parts:
                p = dict(p)
                if p['text']:
                    print(f"[{d['session_id']}] {d['role']}: {str(p['text'])[:200]}")
                elif p['tool']:
                    print(f"[{d['session_id']}] {d['role']}: [tool: {p['tool']}]")

# Check all user messages with actual content
print("\n=== ALL USER MESSAGES WITH CONTENT ===")
cur.execute("""
    SELECT m.session_id, json_extract(m.data, '$.role') as role,
           json_extract(m.data, '$.content') as content,
           m.time_created
    FROM message m
    WHERE json_extract(m.data, '$.role') = 'user'
    AND json_extract(m.data, '$.content') IS NOT NULL
    AND json_extract(m.data, '$.content') != 'None'
    ORDER BY m.time_created
""")
for r in cur.fetchall():
    d = dict(r)
    print(f"[{d['session_id']}] {d['role']}: {str(d['content'])[:300]}")

# Check all assistant messages with content
print("\n=== ALL ASSISTANT MESSAGES WITH TEXT PARTS ===")
cur.execute("""
    SELECT m.session_id, p.id as part_id,
           json_extract(p.data, '$.type') as ptype,
           json_extract(p.data, '$.text') as text
    FROM message m
    JOIN part p ON p.message_id = m.id
    WHERE json_extract(m.data, '$.role') = 'assistant'
    AND json_extract(p.data, '$.type') = 'text'
    AND json_extract(p.data, '$.text') IS NOT NULL
    AND json_extract(p.data, '$.text') != ''
    ORDER BY m.time_created
    LIMIT 30
""")
for r in cur.fetchall():
    d = dict(r)
    print(f"[{d['session_id']}] assistant text: {str(d['text'])[:300]}")

# Check all tool calls
print("\n=== ALL TOOL CALLS ===")
cur.execute("""
    SELECT m.session_id, 
           json_extract(p.data, '$.tool') as tool,
           substr(json_extract(p.data, '$.state.input'), 1, 200) as input_preview
    FROM message m
    JOIN part p ON p.message_id = m.id
    WHERE json_extract(m.data, '$.role') = 'assistant'
    AND json_extract(p.data, '$.type') = 'tool'
    ORDER BY m.time_created
""")
for r in cur.fetchall():
    d = dict(r)
    print(f"[{d['session_id']}] {d['tool']}: {d['input_preview']}")

conn.close()
