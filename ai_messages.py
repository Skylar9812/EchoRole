import sqlite3

conn = sqlite3.connect("echorole.db")
cursor = conn.cursor()

for row in cursor.execute("""
    SELECT session_id, stage_index, user_id, role_name, sender, content, created_at
    FROM ai_messages
    ORDER BY id DESC
    LIMIT 20
"""):
    print(row)

conn.close()