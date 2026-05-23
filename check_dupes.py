import sqlite3, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
con = sqlite3.connect("apartments.db")

print("=== דירות עם post_url זהה (אותה מודעה, post_id שונה) ===")
rows = con.execute("""
    SELECT post_url, COUNT(*) as cnt, GROUP_CONCAT(post_id, ' | ') as ids,
           GROUP_CONCAT(id, ',') as db_ids
    FROM apartments
    WHERE post_url IS NOT NULL
    GROUP BY post_url
    HAVING cnt > 1
    ORDER BY cnt DESC
""").fetchall()
for url, cnt, ids, db_ids in rows:
    print(f"x{cnt}  {url}")
    print(f"  post_ids: {ids}")
    print(f"  db ids:   {db_ids}")
    print()

print(f"סה\"כ URLs כפולים: {len(rows)}")

print("\n=== דירות עם אותה כתובת + מחיר + חדרים (תוכן זהה) ===")
rows2 = con.execute("""
    SELECT address, price, rooms, size_sqm, COUNT(*) as cnt,
           GROUP_CONCAT(id, ',') as db_ids,
           GROUP_CONCAT(post_id, ' | ') as pids
    FROM apartments
    WHERE address IS NOT NULL AND price IS NOT NULL
    GROUP BY address, price, rooms, size_sqm
    HAVING cnt > 1
    ORDER BY cnt DESC
    LIMIT 20
""").fetchall()
for addr, price, rooms, size, cnt, db_ids, pids in rows2:
    print(f"x{cnt}  {addr} | {price}₪ | {rooms}חד | {size}מ²")
    print(f"  ids: {db_ids}")
    print(f"  post_ids: {pids}")
    print()

print(f"סה\"כ קבוצות תוכן כפול: {len(rows2)}")
