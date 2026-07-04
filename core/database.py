import sqlite3
from datetime import datetime

DB_PATH = "apartments.db"


def _migrate(conn):
    existing = {row[1] for row in conn.execute("PRAGMA table_info(apartments)")}
    migrations = {
        "source":         "ALTER TABLE apartments ADD COLUMN source TEXT DEFAULT 'facebook'",
        "address":        "ALTER TABLE apartments ADD COLUMN address TEXT",
        "lat":            "ALTER TABLE apartments ADD COLUMN lat REAL",
        "lon":            "ALTER TABLE apartments ADD COLUMN lon REAL",
        "images_json":    "ALTER TABLE apartments ADD COLUMN images_json TEXT",
        "phone":          "ALTER TABLE apartments ADD COLUMN phone TEXT",
        "notes":          "ALTER TABLE apartments ADD COLUMN notes TEXT",
        "is_active":      "ALTER TABLE apartments ADD COLUMN is_active INTEGER DEFAULT 1",
        "last_seen_at":   "ALTER TABLE apartments ADD COLUMN last_seen_at TEXT",
        "original_price": "ALTER TABLE apartments ADD COLUMN original_price INTEGER",
    }
    for col, sql in migrations.items():
        if col not in existing:
            conn.execute(sql)


def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS apartments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                post_id TEXT UNIQUE,
                group_name TEXT,
                group_id TEXT,
                text TEXT,
                price INTEGER,
                rooms REAL,
                size_sqm INTEGER,
                floor TEXT,
                has_mamad INTEGER DEFAULT 0,
                has_parking INTEGER DEFAULT 0,
                has_balcony INTEGER DEFAULT 0,
                has_elevator INTEGER DEFAULT 0,
                post_url TEXT,
                posted_at TEXT,
                scraped_at TEXT,
                seen INTEGER DEFAULT 0,
                source TEXT DEFAULT 'facebook',
                address TEXT,
                lat REAL,
                lon REAL,
                images_json TEXT,
                phone TEXT,
                notes TEXT,
                is_active INTEGER DEFAULT 1,
                last_seen_at TEXT,
                original_price INTEGER
            )
        """)
        _migrate(conn)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id TEXT UNIQUE,
                group_name TEXT,
                member_count TEXT,
                added_at TEXT,
                active INTEGER DEFAULT 1
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS price_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                post_id TEXT NOT NULL,
                old_price INTEGER,
                new_price INTEGER,
                changed_at TEXT NOT NULL
            )
        """)


def _bool3(val):
    """ממיר ל-1/0/None: True→1, False→0, None→NULL (לא ידוע)"""
    if val is None:
        return None
    return 1 if val else 0


def save_apartment(data: dict) -> bool:
    """שומר דירה. אם קיימת, בודק שינוי מחיר. מחזיר True אם חדשה."""
    now = datetime.now().isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        try:
            conn.execute("""
                INSERT INTO apartments
                (post_id, group_name, group_id, text, price, rooms, size_sqm, floor,
                 has_mamad, has_parking, has_balcony, has_elevator, post_url, posted_at, scraped_at,
                 source, address, lat, lon, images_json, phone, is_active, last_seen_at, original_price)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            """, (
                data.get("post_id"),
                data.get("group_name"),
                data.get("group_id"),
                data.get("text"),
                data.get("price"),
                data.get("rooms"),
                data.get("size_sqm"),
                data.get("floor"),
                _bool3(data.get("has_mamad")),
                _bool3(data.get("has_parking")),
                _bool3(data.get("has_balcony")),
                _bool3(data.get("has_elevator")),
                data.get("post_url"),
                data.get("posted_at"),
                now,
                data.get("source", "facebook"),
                data.get("address"),
                data.get("lat"),
                data.get("lon"),
                data.get("images_json"),
                data.get("phone"),
                now,
                data.get("price"),
            ))
            return True
        except sqlite3.IntegrityError:
            # Existing listing — check for price change, backfill missing images, refresh last_seen_at
            post_id = data.get("post_id")
            new_price = data.get("price")
            new_images = data.get("images_json")
            if post_id:
                row = conn.execute(
                    "SELECT price, original_price, images_json FROM apartments WHERE post_id = ?",
                    (post_id,)
                ).fetchone()
                if row:
                    old_price, orig_price, old_images = row
                    # לא דורסים תמונות קיימות - רק משלימים אם עדיין אין שום תמונה
                    images_to_set = new_images if (new_images and not old_images) else old_images

                    if new_price and old_price is not None and old_price != new_price:
                        if orig_price is None:
                            orig_price = old_price
                        conn.execute(
                            "INSERT INTO price_history (post_id, old_price, new_price, changed_at) VALUES (?, ?, ?, ?)",
                            (post_id, old_price, new_price, now),
                        )
                        conn.execute(
                            "UPDATE apartments SET price = ?, original_price = ?, images_json = ?, last_seen_at = ?, is_active = 1 WHERE post_id = ?",
                            (new_price, orig_price, images_to_set, now, post_id),
                        )
                    else:
                        conn.execute(
                            "UPDATE apartments SET images_json = ?, last_seen_at = ?, is_active = 1 WHERE post_id = ?",
                            (images_to_set, now, post_id),
                        )
            return False


def update_amenities(post_id: str, amenities: dict):
    """מעדכן שדות נוחיות עבור רשומה קיימת (רק ערכים שאינם None)"""
    fields = {k: v for k, v in amenities.items()
              if k in ("has_mamad", "has_parking", "has_balcony", "has_elevator") and v is not None}
    if not fields:
        return
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            f"UPDATE apartments SET {set_clause} WHERE post_id = ?",
            list(fields.values()) + [post_id],
        )


def save_group(data: dict):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            INSERT OR IGNORE INTO groups (group_id, group_name, member_count, added_at)
            VALUES (?, ?, ?, ?)
        """, (data["group_id"], data["group_name"], data.get("member_count", ""), datetime.now().isoformat()))


def mark_seen(post_id: str, seen: bool = True):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE apartments SET seen = ? WHERE post_id = ?", (1 if seen else 0, post_id))


def update_note(post_id: str, note: str):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE apartments SET notes = ? WHERE post_id = ?", (note, post_id))


def mark_inactive(post_id: str, active: bool = False):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE apartments SET is_active = ? WHERE post_id = ?", (1 if active else 0, post_id))


def get_price_history(post_id: str) -> list[dict]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM price_history WHERE post_id = ? ORDER BY changed_at ASC",
            (post_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_apartments(filters: dict = None) -> list[dict]:
    query = """
        SELECT a.*,
            (SELECT MIN(ph.old_price) FROM price_history ph WHERE ph.post_id = a.post_id) AS first_hist_price
        FROM apartments a WHERE 1=1
    """
    params = []

    if filters:
        if filters.get("min_price"):
            query += " AND a.price >= ?"
            params.append(filters["min_price"])
        if filters.get("max_price"):
            query += " AND a.price <= ?"
            params.append(filters["max_price"])
        if filters.get("only_with_price"):
            query += " AND a.price IS NOT NULL"
        if filters.get("min_rooms"):
            query += " AND (a.rooms IS NULL OR a.rooms >= ?)"
            params.append(filters["min_rooms"])
        if filters.get("max_rooms"):
            query += " AND (a.rooms IS NULL OR a.rooms <= ?)"
            params.append(filters["max_rooms"])
        if filters.get("min_size"):
            query += " AND (a.size_sqm IS NULL OR a.size_sqm >= ?)"
            params.append(filters["min_size"])
        if filters.get("max_size"):
            query += " AND (a.size_sqm IS NULL OR a.size_sqm <= ?)"
            params.append(filters["max_size"])
        if filters.get("has_mamad"):
            query += " AND a.has_mamad = 1"
        if filters.get("has_parking"):
            query += " AND a.has_parking = 1"
        if filters.get("has_balcony"):
            query += " AND a.has_balcony = 1"
        if filters.get("source"):
            query += " AND a.source = ?"
            params.append(filters["source"])

    query += " ORDER BY a.scraped_at DESC"

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def get_groups() -> list[dict]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM groups WHERE active = 1").fetchall()
        return [dict(r) for r in rows]


def get_stats() -> dict:
    with sqlite3.connect(DB_PATH) as conn:
        total = conn.execute("SELECT COUNT(*) FROM apartments WHERE is_active = 1").fetchone()[0]
        new_today = conn.execute(
            "SELECT COUNT(*) FROM apartments WHERE date(scraped_at) = date('now') AND is_active = 1"
        ).fetchone()[0]
        groups = conn.execute("SELECT COUNT(*) FROM groups WHERE active = 1").fetchone()[0]
        price_drops = conn.execute("SELECT COUNT(DISTINCT post_id) FROM price_history").fetchone()[0]
        return {"total": total, "new_today": new_today, "groups": groups, "price_drops": price_drops}
