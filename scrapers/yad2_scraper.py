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


def build_search_url(config: dict) -> str:
    cfg_rooms = config.get("חדרים", {})

    min_rooms = cfg_rooms.get("מינימום") or 0
    max_rooms = cfg_rooms.get("מקסימום") or 0

    # city=6300 = Givataim, topArea=2, area=3, property=1 = apartments
    params = "?topArea=2&area=3&city=6300&property=1"
    if min_rooms and max_rooms:
        params += f"&rooms={min_rooms}-{max_rooms}"
    elif min_rooms:
        params += f"&rooms={min_rooms}-"

    return f"https://www.yad2.co.il/realestate/forsale{params}"


def parse_price(text: str) -> int | None:
    text = text.replace(",", "").replace("₪", "").replace("שח", "").strip()
    m = re.search(r"(\d{6,8})", text)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+\.?\d*)\s*מיליון", text)
    if m:
        return int(float(m.group(1)) * 1_000_000)
    return None


def passes_city_filter(card_text: str, config: dict) -> bool:
    location = config.get("חיפוש", {}).get("מיקום", "")
    if not location:
        return True
    return location in card_text


def passes_config_filters(data: dict, config: dict) -> bool:
    cfg_rooms = config.get("חדרים", {})
    cfg_price = config.get("מחיר", {})
    cfg_size = config.get("גודל_במטר", {})

    if data.get("price"):
        if cfg_price.get("מינימום") and data["price"] < cfg_price["מינימום"]:
            return False
        if cfg_price.get("מקסימום") and data["price"] > cfg_price["מקסימום"]:
            return False
    elif config.get("מחיר", {}).get("רק_פוסטים_עם_מחיר"):
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


def _radware_challenge_active(page: Page) -> bool:
    try:
        return "radware" in (page.title() or "").lower()
    except Exception:
        return False


def _wait_out_radware(page: Page, log, timeout_s: int = 25) -> bool:
    """Radware מציג challenge אוטומטי מבוסס JS (לא אינטראקטיבי כמו PerimeterX
    במדלן) - נפתר לבד תוך כמה שניות אם הדפדפן עובר את בדיקות ה-fingerprint.
    מחזיר True אם החסימה נעלמה, False אם זו חסימה קשה שדורשת פתרון ידני."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        time.sleep(1.5)
        if not _radware_challenge_active(page):
            try:
                page.wait_for_load_state("networkidle", timeout=10_000)
            except Exception:
                pass
            return True
    return False


def scrape_yad2(page: Page, log=None) -> int:
    config = load_config()
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

    url = build_search_url(config)
    _log(f"יד2: נכנס לדף {url}")

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(5)
    except PlaywrightTimeout:
        _log("יד2: timeout בטעינת הדף")
        return 0

    if _radware_challenge_active(page):
        _log("יד2: זוהתה חסימת Radware ('Verifying your browser...') - ממתין לפתרון אוטומטי...")
        if _wait_out_radware(page, _log):
            _log("יד2: החסימה נפתרה, ממשיך")
        else:
            _log("יד2: החסימה לא נפתרה - כנראה חסימה קשה. "
                  "הרץ setup/start_yad2_browser.py ופתור ידנית בדפדפן שם.")
            return 0

    html_size = len(page.content())
    if html_size < 20000:
        _log(f"יד2: דף קטן ({html_size} תווים) - ייתכן חסימת בוט, מדלג")
        return 0

    CARD_SEL = "[data-testid='item-basic'], [data-testid='agency-item']"
    max_pages = 10

    # מפת token → גלריית תמונות מלאה, מתוך __NEXT_DATA__. זהו snapshot סטטי
    # מהטעינה הראשונית של הדף (Next.js לא מעדכן אותו בניווט/גלילה מצד הלקוח),
    # אז זה בעצם מכסה רק את הכרטיסיות שהיו ב-SSR הראשוני - לא עמוד 2+.
    # לכן זה fallback טוב (גלריה מלאה) כשקיים, ולא המקור היחיד לתמונות -
    # לכל כרטיסייה יש גם תמונה בודדת ב-DOM עצמו (card_img_src בהמשך) שעובדת
    # בכל עמוד בלי תלות ב-token.
    token_images: dict = {}
    try:
        nd = page.evaluate("() => window.__NEXT_DATA__")
        def _collect(obj, depth=0):
            if depth > 15:
                return
            if isinstance(obj, dict):
                t = obj.get("token")
                imgs = obj.get("metaData", {}).get("images")
                if t and imgs:
                    token_images[str(t)] = imgs
                for v in obj.values():
                    _collect(v, depth + 1)
            elif isinstance(obj, list):
                for item in obj:
                    _collect(item, depth + 1)
        _collect(nd)
        _log(f"יד2: נמצאו גלריות מלאות ל-{len(token_images)} מודעות (מהטעינה הראשונית) מ-__NEXT_DATA__")
    except Exception as e:
        _log(f"יד2: לא ניתן לחלץ __NEXT_DATA__: {e}")

    for page_num in range(1, max_pages + 1):
        # גלול לטעינת כל הכרטיסיות בעמוד
        for _ in range(3):
            page.keyboard.press("End")
            time.sleep(1.5)

        cards = page.query_selector_all(CARD_SEL)
        _log(f"יד2: עמוד {page_num} — {len(cards)} כרטיסיות")

        if not cards:
            break

        for card in cards:
            try:
                card_text = card.inner_text()

                # מחיר
                price_el = card.query_selector("[data-testid='price']")
                price = parse_price(price_el.inner_text() if price_el else card_text)

                # תאריך פרסום — מחולץ מ-URL התמונה הראשית: /Pic/YYYYMM/DD/
                posted_at = None
                card_img_src = None
                img_el = card.query_selector("img[data-testid='image']")
                if img_el:
                    card_img_src = img_el.get_attribute("src") or None
                    dm = re.search(r"/Pic/(\d{4})(\d{2})/(\d{2})/", card_img_src or "")
                    if dm:
                        posted_at = f"{dm.group(1)}-{dm.group(2)}-{dm.group(3)}"

                # חדרים, מ"ר וקומה מ-info-line-2nd (פורמט: "5 חדרים • קומה ‎6‏ • 130 מ״ר")
                rooms = None
                size_sqm = None
                floor = None

                info2_el = card.query_selector("[data-testid='item-info-line-2nd']")
                info2 = info2_el.inner_text() if info2_el else ""

                # חדרים
                m = re.search(r"(\d+\.?\d*)\s*חד", info2 or card_text)
                if m:
                    rooms = float(m.group(1))

                # מ"ר — מ״ר משתמש ב-U+05F4 (gershayim עברי)
                m = re.search(r"(\d+)\s*מ[\"״׳″׳]?ר", info2 or card_text)
                if m:
                    size_sqm = int(m.group(1))

                # קומה — יש סימני כיוון Unicode (‎ ‏) סביב המספר
                m = re.search(r"קומה[\s‎‏]+(\d+)[‎‏]*"
                              r"(?:[\s‎‏]*מתוך[\s‎‏]+(\d+))?",
                              info2 or card_text)
                if m:
                    floor = f"{m.group(1)}/{m.group(2)}" if m.group(2) else m.group(1)

                # כתובת
                address = ""
                addr_el = card.query_selector("[data-testid='street-name'], [data-testid='address-line']")
                if addr_el:
                    address = addr_el.inner_text().strip()

                # לינק + token
                post_url = ""
                token = ""
                link_el = card.query_selector("a[href]")
                if link_el:
                    href = link_el.get_attribute("href") or ""
                    full_url = href if href.startswith("http") else f"https://www.yad2.co.il{href}"
                    # נקה query params — ה-URL הנקי הוא המזהה היציב
                    post_url = full_url.split("?")[0]
                    tm = re.search(r"/item/[^/]+/(\w+)", href)
                    if tm:
                        token = tm.group(1)

                # תכונות מה-tags — כל tag הוא span נפרד ב-item-tags-box
                tags = []
                tags_el = card.query_selector("[data-testid='item-tags-box']")
                if tags_el:
                    tags = [s.inner_text().strip() for s in tags_el.query_selector_all("span")]

                # יד2: tag קיים = True, לא קיים = None (הכרטיסייה מציגה רק מה שיש)
                def _tag(keywords):
                    return True if any(w in t for t in tags for w in keywords) else None

                has_mamad    = _tag(['ממ"ד', 'ממד', 'מרחב מוגן'])
                has_parking  = _tag(['חניה', 'חנייה', 'פרקינג'])
                has_balcony  = _tag(['מרפסת'])
                has_elevator = _tag(['מעלית'])

                # תמונות — מ-__NEXT_DATA__ (גלריה מלאה, קיים רק לעמוד הראשון בפועל
                # כי זה snapshot סטטי מהטעינה הראשונית) - ואם אין, לפחות התמונה
                # הבודדת שמוצגת בכרטיסייה עצמה (עובד בכל עמוד, בלי תלות ב-token)
                img_urls = token_images.get(token) or ([card_img_src] if card_img_src else [])
                local_imgs = download_images(
                    f"yad2_{token or hash(post_url)}",
                    img_urls,
                    referer="https://www.yad2.co.il",
                ) if img_urls else []
                images_json = json.dumps(local_imgs) if local_imgs else None

                # טלפון — fetch מתוך הדפדפן (עם session) ללא ניווט לדף נוסף
                phone = None
                if token:
                    try:
                        result = page.evaluate(f"""
                            async () => {{
                                const r = await fetch(
                                    'https://gw.yad2.co.il/realestate-item/{token}/customer',
                                    {{credentials: 'include', headers: {{'Accept': 'application/json'}}}}
                                );
                                if (r.ok) return await r.json();
                                return null;
                            }}
                        """)
                        if result and isinstance(result, dict):
                            phone = (result.get("phone") or
                                     result.get("phoneNumber") or
                                     result.get("mobile") or
                                     result.get("contactPhone"))
                    except Exception:
                        pass

                post_data = {
                    "post_id": f"yad2_{token}" if token else f"yad2_{post_url}",
                    "group_name": "יד2",
                    "group_id": "yad2",
                    "text": card_text,
                    "price": price,
                    "rooms": rooms,
                    "size_sqm": size_sqm,
                    "floor": floor,
                    "has_mamad": has_mamad,
                    "has_parking": has_parking,
                    "has_balcony": has_balcony,
                    "has_elevator": has_elevator,
                    "post_url": post_url,
                    "posted_at": posted_at,
                    "source": "yad2",
                    "address": address,
                    "images_json": images_json,
                    "phone": str(phone) if phone else None,
                }

                if passes_city_filter(card_text, config) and passes_config_filters(post_data, config):
                    if save_apartment(post_data):
                        new_count += 1

            except Exception as e:
                _log(f"יד2: שגיאה בכרטיסייה - {e}")
                continue

        # עמוד הבא
        next_btn = page.query_selector("[data-testid='pagination-item-link'][aria-label='עמוד הבא'], "
                                       "a[aria-label='עמוד הבא'], "
                                       "[data-testid='next-page']")
        if not next_btn:
            _log("יד2: אין עמוד הבא")
            break
        try:
            next_btn.click(timeout=5000)
            time.sleep(3)
        except Exception:
            break

    _log(f"יד2: סה\"כ {new_count} דירות חדשות נשמרו")
    return new_count
