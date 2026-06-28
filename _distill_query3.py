import sqlite3, json

DB = r"C:\Users\IHAN HANSAJA\.local\share\mimocode\mimocode.db"
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# Check message data structure
print("=== MESSAGE DATA SAMPLES ===")
cur.execute("""
    SELECT id, session_id, agent_id, data
    FROM message
    ORDER BY time_created DESC
    LIMIT 10
""")
for r in cur.fetchall():
    d = dict(r)
    data = json.loads(d['data']) if isinstance(d['data'], str) else d['data']
    print(f"\n--- Message {d['id']} (session: {d['session_id']}, agent: {d['agent_id']}) ---")
    print(f"  Role: {data.get('role')}")
    content = data.get('content')
    if content:
        print(f"  Content: {str(content)[:300]}")
    else:
        print(f"  Content keys: {list(data.keys())}")
        # Print first few keys
        for k, v in data.items():
            if k != 'role':
                print(f"  {k}: {str(v)[:200]}")

# Check part data
print("\n\n=== PART DATA SAMPLES ===")
cur.execute("""
    SELECT id, message_id, data
    FROM part
    ORDER BY time_created DESC
    LIMIT 15
""")
for r in cur.fetchall():
    d = dict(r)
    data = json.loads(d['data']) if isinstance(d['data'], str) else d['data']
    print(f"\n--- Part {d['id']} (message: {d['message_id']}) ---")
    ptype = data.get('type')
    print(f"  Type: {ptype}")
    if ptype == 'text':
        print(f"  Text: {str(data.get('text', ''))[:300]}")
    elif ptype == 'tool':
        print(f"  Tool: {data.get('tool')}")
        state = data.get('state', {})
        inp = str(state.get('input', ''))[:200]
        print(f"  Input: {inp}")

# Check if there's any existing .mimocode dir in the project
print("\n\n=== LOOKING FOR EXISTING ASSETS IN PROJECT ===")
import os
project_root = r"F:\Projects\Freya\freyav3"
for root, dirs, files in os.walk(project_root):
    # Skip venv and __pycache__
    dirs[:] = [d for d in dirs if d not in ('venv', '__pycache__', '.git', 'node_modules')]
    for f in files:
        if f.endswith('.md'):
            print(os.path.join(root, f))

conn.close()
