"""
סורק דורין (dorin.app) — בוט חיפוש דירות חיצוני שכבר מרכז ומנקה מודעות
ממדלן, יד2 ופייסבוק (כולל כתובת מדויקת, גם לפוסטים שהגיעו מפייסבוק).

לא דורש דפדפן — קריאות API ישירות עם requests, מזוהות רק לפי userId
המוצפן שמופיע בלינק האישי של המשתמש בדורין (אין login/סשן נפרד).

פילטרים: נשלפים חיים מ-/api/filters/ (מה שהוגדר בפועל באפליקציית דורין),
כדי שלא נצטרך לשכפל/לסנכרן אותם ידנית מול config.yaml.
"""
import os
import sys
import json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import requests
import yaml
from dotenv import load_dotenv
from core.database import save_apartment
from core.image_utils import download_images

load_dotenv()

DORIN_USER_ID = os.getenv("DORIN_USER_ID")
BASE = "https://dorin.app/api"
PAGE_SIZE = 30
ROOM_STEP = 0.5
PRICE_STEP = 250_000

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

HEADERS = {
    "accept": "*/*",
    "content-type": "application/json",
    "origin": "https://dorin.app",
    "user-agent": UA,
}

IMAGE_REFERERS = {
    "madlan": "https://www.madlan.co.il",
    "yad2": "https://www.yad2.co.il",
}


def _load_config() -> dict:
    with open("config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _get_saved_filters() -> dict:
    """שולף את הפילטרים ששמורים בפועל בחשבון דורין של המשתמש."""
    r = requests.get(f"{BASE}/filters/", params={"userId": DORIN_USER_ID}, headers=HEADERS, timeout=15)
    r.raise_for_status()
    data = r.json()
    return data.get("filters", data)


def _fetch_page(filters: dict, page: int) -> dict:
    r = requests.post(
        f"{BASE}/filters/apartments",
        params={"page": page, "pageSize": PAGE_SIZE, "userId": DORIN_USER_ID},
        headers=HEADERS,
        json=filters,
        timeout=20,
    )
    r.raise_for_status()
    return r.json()


def _to_apartment(item: dict) -> dict:
    street = (item.get("street") or "").strip()
    city = (item.get("city") or "").strip()
    address = ", ".join(p for p in (street, city) if p) or None

    # groupId יציב לאורך זמן (דורין מקבץ בעצמה מודעות חוזרות תחתיו);
    # ה-id הפרטני משתנה בכל הופעה מחדש של אותה מודעה, לכן לא מתאים כ-post_id
    post_id = f"dorin_{item.get('groupId') or item['id']}"

    referer = IMAGE_REFERERS.get(item.get("source", ""))
    images = download_images(post_id, item.get("images") or [], referer=referer or "")

    return {
        "post_id": post_id,
        "text": item.get("description"),
        "price": item.get("price") or None,
        "rooms": item.get("bedrooms"),
        "size_sqm": item.get("squareFeet"),
        "has_mamad": item.get("hasMamad"),
        "has_parking": item.get("hasParking"),
        "has_balcony": item.get("hasBalcony"),
        "has_elevator": item.get("hasElevator"),
        "post_url": f"https://dorin.app/apartments?userId={DORIN_USER_ID}&drawer={item['id']}",
        "posted_at": item.get("listedDate") or item.get("datePosted"),
        "source": "dorin",
        "address": address,
        "lat": item.get("latitude"),
        "lon": item.get("longitude"),
        "images_json": json.dumps(images) if images else None,
    }


def _save_items(items: list, log) -> int:
    new_count = 0
    for item in items:
        if item.get("hiddenReason"):
            continue  # כבר יורדה מהמקור המקורי — אין טעם לשמור
        if save_apartment(_to_apartment(item)):
            new_count += 1
    return new_count


def _room_values(lo, hi) -> list:
    if lo is None or hi is None:
        return [None]
    values = []
    v = float(lo)
    while v <= float(hi) + 1e-9:
        values.append(v)
        v += ROOM_STEP
    return values


def _price_bands(lo: int, hi: int | None) -> list:
    if hi is None:
        return [(lo, None)]
    bands = []
    start = lo
    while start < hi:
        end = min(start + PRICE_STEP - 1, hi)
        bands.append((start, end))
        start = end + 1
    return bands or [(lo, hi)]


def _scrape_sliced(base_filters: dict, log) -> int:
    """
    חשבון חינמי בדורין חושף רק את העמוד הראשון (עד ~20 דירות) לכל שאילתה.
    כדי לקבל כיסוי מלא, מפצלים את אותו החיפוש לשאילתות צרות בהרבה
    (חדרים בודדים × טווחי מחיר של רבע מיליון) שכל אחת מהן נכנסת בעמוד אחד.
    """
    config = _load_config()
    lo_price = base_filters.get("minPrice") or config.get("מחיר", {}).get("מינימום") or 0
    hi_price = base_filters.get("maxPrice") or config.get("מחיר", {}).get("מקסימום")
    room_values = _room_values(base_filters.get("minBedrooms"), base_filters.get("maxBedrooms"))
    price_bands = _price_bands(lo_price, hi_price)

    log(f"[דורין] מפצל ל-{len(room_values)} ערכי חדרים × {len(price_bands)} טווחי מחיר "
        f"(עד {len(room_values) * len(price_bands)} שאילתות) כדי לעקוף את הגבלת העמוד היחיד")

    new_count = 0
    for rooms in room_values:
        for band_lo, band_hi in price_bands:
            filters = dict(base_filters)
            if rooms is not None:
                filters["minBedrooms"] = rooms
                filters["maxBedrooms"] = rooms
            filters["minPrice"] = band_lo
            if band_hi is not None:
                filters["maxPrice"] = band_hi

            page = 1
            total_pages = 1
            while page <= total_pages:
                data = _fetch_page(filters, page)
                items = data.get("apartments", [])
                total_pages = data.get("totalPages", 1)
                new_count += _save_items(items, log)

                if data.get("pageLimited"):
                    log(f"[דורין] פילוח חדרים={rooms} מחיר={band_lo}-{band_hi} עדיין חוסם עמודים "
                        f"(סה\"כ {data.get('total')} דירות בפילוח הזה) — אולי כדאי לצמצם עוד את הפילטרים")
                    break
                page += 1

    return new_count


def scrape_dorin(log=print) -> int:
    if not DORIN_USER_ID:
        raise Exception("חסר DORIN_USER_ID בקובץ .env — העתק אותו מפרמטר userId בלינק האישי שלך בדורין")

    base_filters = _get_saved_filters()
    new_count = 0
    page = 1
    total_pages = 1
    total_matching = None
    limited = False

    while page <= total_pages:
        data = _fetch_page(base_filters, page)
        items = data.get("apartments", [])
        total_pages = data.get("totalPages", 1)
        if total_matching is None:
            total_matching = data.get("total", len(items))
        log(f"[דורין] עמוד {page}/{total_pages}: {len(items)} דירות")

        new_count += _save_items(items, log)

        if data.get("pageLimited"):
            log(f"[דורין] חשבון חינמי בדורין — לא ניתן לדפדף מעבר לעמוד הראשון "
                f"(סה\"כ {total_matching} דירות תואמות)")
            limited = True
            break

        page += 1

    if limited:
        new_count += _scrape_sliced(base_filters, log)

    return new_count


if __name__ == "__main__":
    from core.database import init_db

    def log(msg):
        print(msg, flush=True)

    init_db()
    n = scrape_dorin(log=log)
    log(f"[דורין] {n} דירות חדשות")
    print(f"__RESULT__:{n}", flush=True)
