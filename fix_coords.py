"""
מאפס קואורדינטות שגויות ב-DB:
1. נקודת מרכז העיר גבעתיים (32.0730, 34.8113) — fallback שגוי
2. בוטינסקי 71 (32.0732, 34.8140) — Nominatim שגוי, המיקום ליד התעש
"""
import sqlite3, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

con = sqlite3.connect("apartments.db")

# כל הכתובות שקיבלו את נקודת מרכז העיר כ-fallback
bad_center = con.execute("""
    SELECT id, address FROM apartments
    WHERE round(lat,4)=32.073 AND round(lon,4)=34.8113
""").fetchall()
print(f"נקודת מרכז עיר ({len(bad_center)} רשומות):")
for id_, addr in bad_center:
    print(f"  [{id_}] {addr}")

con.execute("""
    UPDATE apartments SET lat=NULL, lon=NULL
    WHERE round(lat,4)=32.073 AND round(lon,4)=34.8113
""")

# בוטינסקי 71 — קואורדינטות שגויות (ליד התעש)
bad_boti = con.execute("""
    SELECT id, address FROM apartments
    WHERE address LIKE '%בוטינסקי 71%'
""").fetchall()
print(f"\nבוטינסקי 71 ({len(bad_boti)} רשומות) — מאפס קואורדינטות:")
for id_, addr in bad_boti:
    print(f"  [{id_}] {addr}")

con.execute("""
    UPDATE apartments SET lat=NULL, lon=NULL
    WHERE address LIKE '%בוטינסקי 71%'
""")

con.commit()
print("\nסיום — הקואורדינטות השגויות אופסו.")
print("הדירות האלה לא יופיעו על המפה עד שיגיאוקדו מחדש נכון.")
