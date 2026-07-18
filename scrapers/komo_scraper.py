"""
סורק קומו (komo.co.il) — לוח נדל"ן ישראלי נוסף. הדף מעובד בצד השרת (לא SPA)
ובלי הגנת בוטים נראית לעין - נבדק ידנית מול הדף האמיתי: requests רגיל
מחזיר 200 עם כל התוכן, בלי צורך ב-Playwright/דפדפן.

מבנה הדף: כרטיסי מודעה הם <div class="View_Ad_Details" id="modaaPPC<id>">
(מודעות ממומנות) או id="modaaRowDv<id>" (מודעות רגילות) - שתי הצורות
נפרסות עם אותה מבנה פנימי (תמונה, כותרת עם קישור למודעה, מחיר, תיאור עם
חדרים/מ"ר/קומה), אז מספיק לחפש את שני סוגי ה-id ולפרש טווח טקסט קבוע
אחריהם - בלי לפרסר HTML מלא.
"""
import os
import sys
import re
import json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import requests
import yaml
from core.database import save_apartment
from core.image_utils import download_images

BASE = "https://www.komo.co.il"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
HEADERS = {"User-Agent": UA}
MAX_PAGES = 10
CARD_SLICE = 2000  # תווים אחרי כל id="modaaPPC.../modaaRowDv..." שמכילים כרטיס אחד שלם


def load_config() -> dict:
    with open("config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def passes_config_filters(data: dict, config: dict) -> bool:
    cfg_rooms = config.get("חדרים", {})
    cfg_price = config.get("מחיר", {})
    cfg_size = config.get("גודל_במטר", {})

    if data.get("price"):
        if cfg_price.get("מינימום") and data["price"] < cfg_price["מינימום"]:
            return False
        if cfg_price.get("מקסימום") and data["price"] > cfg_price["מקסימום"]:
            return False
    elif cfg_price.get("רק_פוסטים_עם_מחיר"):
        return False

    if data.get("rooms"):
        if cfg_rooms.get("מינימום") and data["rooms"] < cfg_rooms["מינימום"]:
            return False
        if cfg_rooms.get("מקסימום") and data["rooms"] > cfg_rooms["מקסימום"]:
            return False

    if data.get("size_sqm"):
        if cfg_size.get("מינימום") and data["size_sqm"] < cfg_size["מינימום"]:
            return False
        if cfg_size.get("מקסימום") and data["size_sqm"] > cfg_size["מקסימום"]:
            return False

    return True


def _reorder_address(title: str) -> str | None:
    """קומו מציג כותרת כ"עיר, שכונה, רחוב+מספר" (עיר קודם) - הפוך מהמוסכמה
    שהשאר הסקרייפרים משתמשים בה ושעליה core/dedup.py מסתמך (רחוב+מספר
    קודם, עיר אחרון). מזהים איזה מקטע מכיל מספר (=רחוב עם מספר בית)
    ומעבירים אותו קדימה, בלי קשר למיקום המקורי שלו בכותרת."""
    if not title:
        return None
    parts = [p.strip() for p in title.split(",") if p.strip()]
    if len(parts) < 2:
        return title
    city, rest = parts[0], parts[1:]
    with_digit = [p for p in rest if any(c.isdigit() for c in p)]
    without_digit = [p for p in rest if not any(c.isdigit() for c in p)]
    return ", ".join(with_digit + without_digit + [city])


def _parse_listings(html: str) -> list[dict]:
    listings = []
    seen_ids = set()
    for m in re.finditer(r'id="modaaPPC(\d+)"|id="modaaRowDv(\d+)"', html):
        modaa_id = m.group(1) or m.group(2)
        if modaa_id in seen_ids:
            continue
        seen_ids.add(modaa_id)
        chunk = html[m.start():m.start() + CARD_SLICE]

        price = None
        pm = re.search(r'<div class="price">([\d,]+)&nbsp;', chunk)
        if pm:
            price = int(pm.group(1).replace(",", ""))

        rooms = size_sqm = None
        rm = re.search(r'(\d+\.?\d*)\s*חדרים\s*\((\d+)\s*מ(?:&quot;|")ר\)', chunk)
        if rm:
            rooms = float(rm.group(1))
            size_sqm = int(rm.group(2))

        floor = None
        fm = re.search(r"קומה:?\s*(\d+)\s*מתוך\s*(\d+)", chunk)
        if fm:
            floor = f"{fm.group(1)}/{fm.group(2)}"

        title = None
        tm = re.search(r'<h2 class="title">([^<]+)</h2>', chunk)
        if tm:
            title = tm.group(1).strip()

        img_url = None
        im = re.search(r'src="(/api/modaot/tmunot/showPic/list/\?picNum=\d+[^"]*)"', chunk)
        if im and "picNum=0" not in im.group(1):
            img_url = BASE + im.group(1)

        listings.append({
            "post_id": f"komo_{modaa_id}",
            "text": None,
            "price": price,
            "rooms": rooms,
            "size_sqm": size_sqm,
            "floor": floor,
            "post_url": f"{BASE}/code/nadlan/details/?modaaNum={modaa_id}",
            "source": "komo",
            "address": _reorder_address(title),
            "_image": img_url,
        })
    return listings


def _locations(config: dict) -> list[str]:
    """"מיקום" ב-config יכול להיות עיר בודדת (str) או רשימת ערים - כדי
    לתמוך בחיפוש בכמה ערים במקביל (למשל גבעתיים + רמת גן) בלי לשבור את
    הפורמט הישן (עיר בודדת)."""
    loc = config.get("חיפוש", {}).get("מיקום") or "גבעתיים"
    return loc if isinstance(loc, list) else [loc]


def scrape_komo(log=print) -> int:
    config = load_config()
    new_count = 0

    for city in _locations(config):
        for page in range(1, MAX_PAGES + 1):
            params = {"nehes": 1, "cityName": city}
            if page > 1:
                params["currPage"] = page
            try:
                r = requests.get(f"{BASE}/code/nadlan/apartments-for-sale.asp", params=params,
                                  headers=HEADERS, timeout=20)
                r.raise_for_status()
            except requests.RequestException as e:
                log(f"[קומו] {city}: שגיאת רשת בעמוד {page}: {e}")
                break

            # קומו מגביל צפייה לעמוד 1 בלבד למשתמש לא מחובר - עמוד 2+ מפנה
            # ל-account.komo.co.il/login, גם עם cookies מהבקשה הקודמת (אומת
            # ידנית). זו הגבלת חשבון-חינמי, לא שגיאה - כמו ה-pageLimited של דורין.
            if "account.komo.co.il" in r.url:
                log(f"[קומו] {city}: עמוד {page}: חסום למשתמש לא מחובר (מציג רק עמוד 1)")
                break

            listings = _parse_listings(r.text)
            log(f"[קומו] {city}: עמוד {page}: {len(listings)} מודעות")
            if not listings:
                break

            for item in listings:
                image = item.pop("_image")
                images = download_images(item["post_id"], [image], referer=BASE) if image else []
                item["images_json"] = json.dumps(images) if images else None
                if passes_config_filters(item, config):
                    if save_apartment(item):
                        new_count += 1

    log(f'[קומו] סה"כ {new_count} דירות חדשות נשמרו')
    return new_count


if __name__ == "__main__":
    from core.database import init_db

    def log(msg):
        print(msg, flush=True)

    init_db()
    n = scrape_komo(log=log)
    log(f"[קומו] {n} דירות חדשות")
    print(f"__RESULT__:{n}", flush=True)
