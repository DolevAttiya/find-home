"""
איתור ומיזוג דירות זהות שמופיעות כמה פעמים (מקורות שונים, או אותה מודעה
שהופצה לכמה קבוצות פייסבוק).

מחיר+חדרים זהים הם התנאי הבסיסי המחייב לכל התאמה כשאין כתובת אמינה -
זה חוסם מיזוגים שגויים כשכתובת אינה אמינה (למשל כתובת שם-רחוב-בלבד בלי
מספר בית ביד2, שיכולה להתאים לכמה דירות שונות באותו רחוב; או כתובת "רעש"
שחולצה בטעות מטקסט חופשי בפייסבוק). בתוך אותה קבוצת מחיר+חדרים, כתובת
תואמת (עם מספר בית) או גודל קרוב (עד ~5 מ"ר הפרש, בלי "שרשור" מעבר
לסטייה) מספיקים כדי לאחד.

כשכן יש כתובת חזקה (עם מספר בית) זהה + מספר חדרים זהה, מאחדים גם אם
המחיר שונה קצת (עד PRICE_TOLERANCE_PCT) - כדי לתפוס ירידת מחיר שהתעדכנה
במקור אחד (למשל מדלן) אבל עדיין לא בשני (למשל יד2).
"""
import json
import re

SIZE_TOLERANCE_SQM = 5
PRICE_TOLERANCE_PCT = 0.05


def _normalize_address(addr: str | None) -> str | None:
    if not addr:
        return None
    s = addr.strip()
    s = s.split(",")[0]  # רק רחוב+מספר בית - שכונה/עיר בסוף משתנות בין מקורות (מדלן/דורין מוסיפים, יד2 לא)
    s = re.sub(r'["\'׳״]', "", s)
    s = re.sub(r"^(רחוב|רח)\s+", "", s)
    s = re.sub(r"\s+", " ", s).strip(" ,.")
    return s or None


def _address_key(addr: str | None) -> str | None:
    """כתובת "חזקה" רק אם יש בה מספר בית - כתובת של שם רחוב בלבד (נפוץ
    ביד2 מטעמי פרטיות) לא מספיקה כדי לזהות דירה ספציפית באותו רחוב."""
    norm = _normalize_address(addr)
    if norm and re.search(r"\d", norm):
        return norm
    return None


def _street_name(addr: str | None) -> str | None:
    """שם הרחוב בלבד (גם בלי מספר בית) - חלש מכדי לאשר זהות (לא _address_key),
    אבל מספיק כדי לשלול איחוד בין שתי דירות שמפורש נמצאות ברחובות שונים."""
    norm = _normalize_address(addr)
    if not norm:
        return None
    name = re.match(r"([^\d]+)", norm).group(1).strip()
    return name or None


class _UnionFind:
    def __init__(self, keys):
        self.parent = {k: k for k in keys}

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def _merge_cluster(members: list[dict]) -> dict:
    with_addr = [m for m in members if m.get("address")]
    primary_pool = with_addr or members
    primary = max(primary_pool, key=lambda m: m.get("scraped_at") or "")

    merged = dict(primary)
    merged["_member_post_ids"] = [m["post_id"] for m in members]
    merged["_members"] = members
    merged["source_list"] = sorted({m.get("source") for m in members if m.get("source")})
    merged["group_size"] = len(members)

    for field in ("address", "phone", "lat", "lon", "floor"):
        if not merged.get(field):
            for m in members:
                if m.get(field):
                    merged[field] = m[field]
                    break

    # נוחיות (has_mamad/has_parking/has_balcony/has_elevator) - 0/1/None
    # (ראה _bool3 ב-database.py), אז לא ניתן להשתמש ב"not merged.get(field)"
    # כמו למעלה - 0 הוא falsy אבל הוא תשובה ודאית ("אין"), לא "לא ידוע".
    # ממלאים ממקור אחר רק כשה-primary עדיין None (לא ידוע) - לעולם לא דורסים
    # "אין" מפורש עם "יש" ממקור פחות אמין. אומת ידנית: מודעה שמוזגה עם עותק
    # שאיבד את הנתון (יד2 בד"כ) הייתה מציגה נוחיות ריקות למרות שהעותק השני
    # (מדלן) כן ידע עליהן.
    for field in ("has_mamad", "has_parking", "has_balcony", "has_elevator"):
        if merged.get(field) is None:
            for m in members:
                if m.get(field) is not None:
                    merged[field] = m[field]
                    break

    # מחיר - הנמוך מבין החברים (ייתכן שמקור אחד עדיין לא עדכן ירידת מחיר),
    # ותאריך פרסום - המוקדם מביניהם (כך ש"ימים בשוק" משקף מתי היא באמת עלתה)
    prices = [m["price"] for m in members if m.get("price")]
    if prices:
        merged["price"] = min(prices)
        peak_prices = [m.get("original_price") or m.get("price") for m in members if m.get("original_price") or m.get("price")]
        if peak_prices and max(peak_prices) > merged["price"]:
            merged["original_price"] = max(peak_prices)

    posted_dates = [m["posted_at"] for m in members if m.get("posted_at")]
    if posted_dates:
        merged["posted_at"] = min(posted_dates)

    all_images, seen_paths = [], set()
    for m in members:
        if not m.get("images_json"):
            continue
        try:
            for p in json.loads(m["images_json"]):
                if p not in seen_paths:
                    seen_paths.add(p)
                    all_images.append(p)
        except (json.JSONDecodeError, TypeError):
            pass
    merged["images_json"] = json.dumps(all_images) if all_images else None

    merged["seen"] = 1 if any(m.get("seen") for m in members) else 0
    merged["is_active"] = 1 if any(m.get("is_active", 1) for m in members) else 0
    merged["not_relevant"] = 1 if any(m.get("not_relevant") for m in members) else 0

    return merged


def _cluster_price_rooms_bucket(uf: _UnionFind, group: list[dict]) -> None:
    """מאחד דירות בתוך קבוצת מחיר+חדרים זהים, לפי כתובת תואמת (עם מספר
    בית) ו/או גודל קרוב."""
    by_addr: dict[str, list[dict]] = {}
    for apt in group:
        addr = _address_key(apt.get("address"))
        if addr:
            by_addr.setdefault(addr, []).append(apt)
    for same_addr in by_addr.values():
        for other in same_addr[1:]:
            uf.union(same_addr[0]["post_id"], other["post_id"])

    street_of = {apt["post_id"]: _street_name(apt.get("address")) for apt in group}

    concrete = sorted(
        (m for m in group if m.get("size_sqm") is not None),
        key=lambda m: m["size_sqm"],
    )
    unknown = [m for m in group if m.get("size_sqm") is None]

    # לאחד דירות עם גודל ידוע, בחלונות נגררים שהטווח הכולל שלהם (מהעוגן
    # הראשון) לא חורג מהסטייה המותרת - כדי למנוע "שרשור" שמצטבר מעבר
    # לסטייה (למשל 80→85→90→95, כל זוג סמוך קרוב אבל הקצוות רחוקים).
    # שתי דירות עם רחובות מפורשים ושונים לעולם לא מתאחדות רק כי הגודל
    # קרוב במקרה - רחוב מוצהר גובר על התאמת גודל. משווים מול *כל* הרחובות
    # שכבר ידועים בשרשור הנוכחי (לא רק מול העוגן) - אחרת פריט בלי כתובת
    # יכול "לבלוע" בשקט כמה רחובות שונים בזה אחר זה בלי שהם יתנגשו זה בזה.
    anchor = None
    anchor_streets: set[str] = set()
    for m in concrete:
        if anchor is not None and m["size_sqm"] - anchor["size_sqm"] > SIZE_TOLERANCE_SQM:
            anchor = None
            anchor_streets = set()
        if anchor is None:
            anchor = m
            anchor_streets = {street_of[m["post_id"]]} if street_of[m["post_id"]] else set()
            continue
        m_street = street_of[m["post_id"]]
        if m_street and anchor_streets and m_street not in anchor_streets:
            anchor = m  # רחוב מפורש שלא ידוע בשרשור הזה - לא מאחדים, ממשיכים לשרשר מכאן
            anchor_streets = {m_street}
            continue
        uf.union(anchor["post_id"], m["post_id"])
        if m_street:
            anchor_streets.add(m_street)

    if not concrete:
        # אף אחד לא מציין גודל - אין מידע סותר, מאחדים הכל
        for other in unknown[1:]:
            uf.union(unknown[0]["post_id"], other["post_id"])
    else:
        # דירה בלי גודל מצטרפת לאשכול-גודל רק אם יש אשכול יחיד וחד-משמעי -
        # לא "מגשרת" בין שני גדלים שונים וסותרים
        concrete_roots = {uf.find(m["post_id"]) for m in concrete}
        if len(concrete_roots) == 1:
            anchor_id = concrete[0]["post_id"]
            for m in unknown:
                uf.union(anchor_id, m["post_id"])


def _cluster_by_strong_address(uf: _UnionFind, apartments: list[dict]) -> None:
    """מאחד לפי כתובת חזקה (עם מספר בית) + חדרים זהים, גם כשהמחיר שונה
    קצת - כתובת מדויקת זהה היא סימן חזק מספיק גם בלי התאמת מחיר מלאה."""
    by_addr_rooms: dict[tuple, list[dict]] = {}
    for apt in apartments:
        addr = _address_key(apt.get("address"))
        if addr is None or apt.get("rooms") is None:
            continue
        by_addr_rooms.setdefault((addr, apt["rooms"]), []).append(apt)

    for group in by_addr_rooms.values():
        if len(group) < 2:
            continue
        prices = [m["price"] for m in group if m.get("price")]
        if prices and (max(prices) - min(prices)) / max(prices) > PRICE_TOLERANCE_PCT:
            continue  # פער מחיר גדול מדי - כנראה לא באמת אותה דירה
        for other in group[1:]:
            uf.union(group[0]["post_id"], other["post_id"])


def group_apartments(apartments: list[dict]) -> list[dict]:
    """מקבץ דירות זהות לכדי שורה אחת. מחזיר רשימה חדשה, לא משנה את המקור."""
    if not apartments:
        return []

    uf = _UnionFind(a["post_id"] for a in apartments)

    # איחוד ידני (המשתמש קבע בעצמו שאלה אותה דירה) - קודם לכל היוריסטיקה,
    # תמיד מכבדים אותו בלי תנאים
    by_manual_group: dict[str, list[dict]] = {}
    for apt in apartments:
        mg = apt.get("manual_group")
        if mg:
            by_manual_group.setdefault(mg, []).append(apt)
    for group in by_manual_group.values():
        for other in group[1:]:
            uf.union(group[0]["post_id"], other["post_id"])

    _cluster_by_strong_address(uf, apartments)

    by_price_rooms: dict[tuple, list[dict]] = {}
    for apt in apartments:
        if apt.get("price") is None or apt.get("rooms") is None:
            continue
        by_price_rooms.setdefault((apt["price"], apt["rooms"]), []).append(apt)
    for group in by_price_rooms.values():
        _cluster_price_rooms_bucket(uf, group)

    clusters: dict[str, list[dict]] = {}
    for apt in apartments:
        root = uf.find(apt["post_id"])
        clusters.setdefault(root, []).append(apt)

    return [_merge_cluster(members) for members in clusters.values()]
