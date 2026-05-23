import sqlite3, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
con = sqlite3.connect("apartments.db")

print("=== כל הדירות ב-DB (madlan) ===")
rows = con.execute("""
    SELECT id, address, price, rooms, size_sqm, floor, lat, lon, post_url
    FROM apartments WHERE source='madlan'
    ORDER BY address, scraped_at
""").fetchall()
for r in rows:
    id_, addr, price, rooms, size, floor, lat, lon, url = r
    coords = f"({lat:.4f},{lon:.4f})" if lat else "NO_COORDS"
    print(f"[{id_}] {addr} | {price} | {rooms}חד | {size}מ² | קומה {floor} | {coords}")
    print(f"      {url}")
    print()
