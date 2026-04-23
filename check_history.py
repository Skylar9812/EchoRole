import sqlite3

conn = sqlite3.connect("echorole.db")
cursor = conn.cursor()

print("=== sessions schema ===")
for row in cursor.execute("PRAGMA table_info(sessions)"):
    print(row)

print("\n=== turn_history schema ===")
for row in cursor.execute("PRAGMA table_info(turn_history)"):
    print(row)

conn.close()