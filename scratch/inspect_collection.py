import sqlite3

db_path = r"c:\Users\coope\Documents\Riftbound Test\riftbound-deck-platform-v2\data\deck_platform.db"
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

print("User Collection Cards Row Count:")
count = cur.execute("SELECT COUNT(*) FROM user_collection_cards").fetchone()[0]
print(count)

print("Unique User IDs in user_collection_cards:")
user_ids = cur.execute("SELECT DISTINCT user_id FROM user_collection_cards").fetchall()
for uid in user_ids:
    print(dict(uid))

print("First 10 collection cards:")
rows = cur.execute("SELECT * FROM user_collection_cards LIMIT 10").fetchall()
for row in rows:
    print(dict(row))

conn.close()
