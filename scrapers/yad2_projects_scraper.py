"""
סורק פרויקטים חדשים (בנייה מקבלן) ביד2 — https://www.yad2.co.il/yad1/newprojects
קטגוריה נפרדת לגמרי מיד שנייה (/realestate/forsale): כל "מודעה" היא בניין
שלם עם טווח חדרים/שטח ומחיר "החל מ-" (היחידה הזולה בפרויקט), לא דירה ספציפית.

בגלל זה נשמר תחת source נפרד ("yad2_project") ולא מתערבב עם יד2 רגיל -
מחיר/חדרים/גודל כאן הם קירוב (המינימום בטווח), לא נתונים מדויקים של דירה אחת.
"""
import re
import json
import time
import yaml
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout
from core.database import save_apartment
from core.image_utils import download_images


def load_config() -> dict:
    with open("config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _locations(config: dict) -> list[str]:
    """"מיקום" ב-config יכול להיות עיר בודדת (str) או רשימת ערים - כדי
    לתמוך בחיפוש בכמה ערים במקביל (למשל גבעתיים + רמת גן) בלי לשבור את
    הפורמט הישן (עיר בודדת)."""
    loc = config.get("חיפוש", {}).get("מיקום") or "גבעתיים"
    return loc if isinstance(loc, list) else [loc]


# ר' אותה הערה ב-yad2_scraper.py - city היה מקובע בקוד, לא נגזר מ-"מיקום".
YAD2_CITY_IDS = {
    "גבעתיים": 6300,
    "רמת גן": 8600,
}


def build_search_url(config: dict, city: str) -> str:
    city_id = YAD2_CITY_IDS.get(city, YAD2_CITY_IDS["גבעתיים"])
    return f"https://www.yad2.co.il/yad1/newprojects?topArea=2&area=3&city={city_id}"


def _parse_price(text: str) -> int | None:
    m = re.search(r"([\d,]{6,})", text or "")
    return int(m.group(1).replace(",", "")) if m else None


def _parse_range(text: str, unit_pattern: str) -> tuple[float, float] | None:
    """מחלץ טווח כמו '3-5' או ערך בודד '6' לפני unit_pattern (למשל 'חדרים')."""
    m = re.search(rf"(\d+\.?\d*)\s*-\s*(\d+\.?\d*)\s*{unit_pattern}", text or "")
    if m:
        return float(m.group(1)), float(m.group(2))
    m = re.search(rf"(\d+\.?\d*)\s*{unit_pattern}", text or "")
    if m:
        v = float(m.group(1))
        return v, v
    return None


def _passes_city_filter(text: str, config: dict) -> bool:
    return any(loc in text for loc in _locations(config))


def _ranges_overlap(a: tuple[float, float] | None, b_min, b_max) -> bool:
    """True אם אין קונפליקט - או שאין לנו טווח, או שהטווח שלנו חופף לחיפוש."""
    if a is None or (b_min is None and b_max is None):
        return True
    lo, hi = a
    if b_min and hi < b_min:
        return False
    if b_max and lo > b_max:
        return False
    return True


def _scrape_yad2_projects_city(page: Page, config: dict, city: str, log=None) -> int:
    new_count = 0

    def _log(msg):
        if log:
            log(msg)
        else:
            print(msg, flush=True)

    try:
        from playwright_stealth import Stealth
        Stealth().apply_stealth_sync(page)
    except Exception:
        pass

    url = build_search_url(config, city)
    _log(f"יד2 פרויקטים [{city}]: נכנס לדף {url}")

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(5)
    except PlaywrightTimeout:
        _log("יד2 פרויקטים: timeout בטעינת הדף")
        return 0

    if "radware" in (page.title() or "").lower():
        _log("יד2 פרויקטים: חסימת Radware - מדלג (אותו פתרון כמו ביד2 הרגיל)")
        return 0

    cards = page.query_selector_all("[data-testid='feed-project-item']")
    _log(f"יד2 פרויקטים: {len(cards)} פרויקטים נמצאו")

    cfg_price = config.get("מחיר", {})
    cfg_rooms = config.get("חדרים", {})
    cfg_size = config.get("גודל_במטר", {})

    for card in cards:
        try:
            card_text = card.inner_text()
            if not _passes_city_filter(card_text, config):
                continue

            label_el = card.query_selector("[data-testid='feed-project-label']")
            subtitle_el = card.query_selector("[data-testid='feed-project-subtitle']")
            details_el = card.query_selector("[data-testid='feed-project-details']")
            value_el = card.query_selector("[data-testid='feed-project-value']")
            link_el = card.query_selector("a[href]")
            img_el = card.query_selector("img")

            label = label_el.inner_text().strip() if label_el else ""
            address = subtitle_el.inner_text().strip() if subtitle_el else ""
            details = details_el.inner_text() if details_el else ""
            price = _parse_price(value_el.inner_text()) if value_el else None

            rooms_range = _parse_range(details, "חדרים")
            size_range = _parse_range(details, "מ[\"״]?ר")

            if price and cfg_price.get("מקסימום") and price > cfg_price["מקסימום"]:
                continue  # אפילו היחידה הזולה בפרויקט יקרה מדי
            if not _ranges_overlap(rooms_range, cfg_rooms.get("מינימום"), cfg_rooms.get("מקסימום")):
                continue
            if not _ranges_overlap(size_range, cfg_size.get("מינימום"), cfg_size.get("מקסימום")):
                continue

            href = link_el.get_attribute("href") if link_el else ""
            post_url = href.split("?")[0] if href else ""
            pm = re.search(r"/project/(\d+)", href or "")
            project_id = pm.group(1) if pm else None
            if not project_id:
                continue
            post_id = f"yad2project_{project_id}"

            img_src = img_el.get_attribute("src") if img_el else None
            local_imgs = download_images(post_id, [img_src], referer="https://www.yad2.co.il") if img_src else []

            post_data = {
                "post_id": post_id,
                "group_name": "יד2 - פרויקטים חדשים",
                "group_id": "yad2_project",
                "text": f"{label} — פרויקט חדש מקבלן. {details}".strip(),
                "price": price,
                "rooms": rooms_range[0] if rooms_range else None,
                "size_sqm": int(size_range[0]) if size_range else None,
                "floor": None,
                "source": "yad2_project",
                "address": address,
                "post_url": post_url,
                "images_json": json.dumps(local_imgs) if local_imgs else None,
            }

            if save_apartment(post_data):
                new_count += 1

        except Exception as e:
            _log(f"יד2 פרויקטים: שגיאה בכרטיסייה - {e}")
            continue

    _log(f"יד2 פרויקטים [{city}]: סה\"כ {new_count} פרויקטים חדשים נשמרו")
    return new_count


def scrape_yad2_projects(page: Page, log=None) -> int:
    config = load_config()
    new_count = 0
    for city in _locations(config):
        new_count += _scrape_yad2_projects_city(page, config, city, log=log)
    return new_count
