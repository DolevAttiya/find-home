import os
import re
import json
import time
import random
import yaml
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout
from core.database import save_apartment, update_amenities
from core.image_utils import download_images

MADLAN_PROFILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "madlan_profile")

RESALE_URL   = "https://www.madlan.co.il/for-sale/%D7%92%D7%91%D7%A2%D7%AA%D7%99%D7%99%D7%9D-%D7%99%D7%A9%D7%A8%D7%90%D7%9C?dealType=secondHand"
PROJECTS_URL = "https://www.madlan.co.il/for-sale/%D7%92%D7%91%D7%A2%D7%AA%D7%99%D7%99%D7%9D-%D7%99%D7%A9%D7%A8%D7%90%D7%9C"
IMG_BASE     = "https://images2.madlan.co.il/t:nonce:v=2/"


class CaptchaBlocked(Exception):
    """נזרק כאשר דף מודעה מוחזר עם CAPTCHA והsolver לא הצליח לפתור."""
    pass


def _notify_captcha():
    """שולח התראת Windows כשמוצג CAPTCHA"""
    try:
        import subprocess
        subprocess.Popen([
            "powershell", "-WindowStyle", "Hidden", "-Command",
            "[void][System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms');"
            "$n=New-Object System.Windows.Forms.NotifyIcon;"
            "$n.Icon=[System.Drawing.SystemIcons]::Warning;"
            "$n.Visible=$true;"
            "$n.BalloonTipTitle='סריקת דירות — מדלן';"
            "$n.BalloonTipText='CAPTCHA מוצג! לחץ והחזק בחלון הדפדפן כדי להמשיך.';"
            "$n.BalloonTipIcon='Warning';"
            "$n.ShowBalloonTip(10000);"
            "Start-Sleep 12; $n.Dispose()"
        ], creationflags=0x08000000)  # CREATE_NO_WINDOW
    except Exception:
        pass


def _wait_for_captcha_solve(page: Page, log, timeout_min: int = 5) -> bool:
    """
    ממתין עד timeout_min דקות שהמשתמש יפתור CAPTCHA בחלון הדפדפן.

    שתי שלבים:
    1. 30 שניות ראשונות — בדיקה ללא reload, כדי לא להפריע לפתרון ידני בטאב הנוכחי.
    2. לאחר מכן — reload כל 10 שניות (לתפוס cookies שנשמרו בטאב אחר).
    """
    _notify_captcha()
    log("⚠️  מדלן: CAPTCHA מוצג — פתרו בחלון הדפדפן (לחץ והחזק)")
    log(f"   ממתין עד {timeout_min} דקות...")

    deadline   = time.time() + timeout_min * 60
    grace_end  = time.time() + 30      # 30s grace — no reload
    last_log   = time.time()

    while time.time() < deadline:
        time.sleep(2)
        try:
            if len(page.content()) >= 50000:
                log("✓  מדלן: CAPTCHA נפתר — ממשיך בסריקה")
                return True

            # After grace period — reload to pick up cookies from other tabs
            if time.time() > grace_end:
                page.reload(wait_until="domcontentloaded", timeout=15000)
                try:
                    page.wait_for_load_state("networkidle", timeout=6000)
                except Exception:
                    pass

            if time.time() - last_log > 30:
                remaining = int((deadline - time.time()) / 60)
                log(f"   עדיין ממתין... ({remaining} דקות נותרו)")
                last_log = time.time()
        except Exception:
            pass

    log("✗  מדלן: timeout — CAPTCHA לא נפתר")
    return False


def load_config() -> dict:
    with open("config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def passes_config_filters(data: dict, config: dict) -> bool:
    cfg_rooms = config.get("חדרים", {})
    cfg_price = config.get("מחיר", {})
    cfg_size  = config.get("גודל_במטר", {})

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


def _safe_id(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", str(s))[:40]


# ---------------------------------------------------------------------------
# שלב 1 — איסוף קישורים מדף תוצאות החיפוש
# ---------------------------------------------------------------------------

def _collect_urls(page: Page, search_url: str, log, max_listings=60) -> list[str]:
    """גולל דף תוצאות ואוסף קישורים למודעות בודדות"""
    try:
        page.goto(search_url, wait_until="domcontentloaded", timeout=35000)
        try:
            page.wait_for_load_state("networkidle", timeout=12000)
        except Exception:
            pass
        time.sleep(3)
    except PlaywrightTimeout:
        log("מדלן: timeout בטעינת דף תוצאות")
        return []

    html_size = len(page.content())
    if html_size < 50000:
        log("מדלן: CAPTCHA — מנסה לפתור אוטומטית...")
        try:
            from scrapers.madlan_captcha_solver import PerimeterXSolver
            solver = PerimeterXSolver(profile_dir=MADLAN_PROFILE)
            solved = solver.solve(page, log=log)
        except Exception as e:
            log(f"מדלן: solver שגיאה ({e}) — ממתין לפתרון ידני")
            solved = False
        if not solved:
            if not _wait_for_captcha_solve(page, log, timeout_min=5):
                return []
        html_size = len(page.content())
    log(f"מדלן: דף נטען ({html_size:,} תווים)")

    # גלילה איטית להטעינת כל התוצאות (lazy loading)
    prev_count = 0
    for _ in range(15):
        page.keyboard.press("End")
        time.sleep(1.5)
        count = page.evaluate("""() =>
            document.querySelectorAll('a[href*="/item/"], a[href*="/listings/"]').length
        """) or 0
        if count == prev_count and count > 0:
            break   # אין תוצאות חדשות — סיימנו
        prev_count = count
    time.sleep(1)

    # איסוף כל הקישורים למודעות
    hrefs = page.evaluate("""() => {
        const links = new Set();
        document.querySelectorAll('a[href]').forEach(a => {
            const h = a.getAttribute('href');
            if (h && (h.includes('/item/') || h.includes('/listings/'))) {
                links.add(h.startsWith('http') ? h : 'https://www.madlan.co.il' + h);
            }
        });
        return [...links];
    }""")

    urls = [u for u in (hrefs or []) if isinstance(u, str)][:max_listings]
    log(f"מדלן: נמצאו {len(urls)} קישורים")
    return urls


# ---------------------------------------------------------------------------
# שלב 2 — חילוץ נתונים מדף מודעה בודדת
# ---------------------------------------------------------------------------

def _extract_number(text: str, pattern: str):
    m = re.search(pattern, text)
    if not m:
        return None
    try:
        return re.sub(r"[^\d.]", "", m.group(1))
    except Exception:
        return None


def _scrape_listing_page(page: Page, url: str, log,
                         _solver=None) -> dict | None:
    """מבקר בדף מודעה ומחלץ את כל הנתונים מה-DOM"""
    try:
        page.goto(url,
                  wait_until="domcontentloaded",
                  timeout=25000,
                  referer=RESALE_URL)   # referrer = דף החיפוש, כמו לחיצה אמיתית
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
        time.sleep(1.0)
    except Exception as e:
        log(f"מדלן: שגיאה בטעינת {url}: {e}")
        return None

    html_size = len(page.content())
    if html_size < 30000:
        # CAPTCHA על דף בודד — מנסה solver אוטומטי (2 ניסיונות מהירים).
        # אם נכשל → זורק CaptchaBlocked כדי שה-loop הראשי יטפל בזה פעם אחת גלובלית.
        solved = False
        if _solver is not None:
            solved = _solver.solve(page, log=log)
        if not solved:
            raise CaptchaBlocked(url)
        html_size = len(page.content())

    # קריאת כל הטקסט של הדף
    try:
        body_text = page.inner_text("body")
    except Exception:
        return None

    # --- כתובת ---
    # Strategy 1: הכתובת האמיתית מופיעה ממש לפני "דירה למכירה" / "דירה להשכרה"
    # זה pattern עקבי ב-Madlan — price/rooms/floor/size → כתובת → "דירה למכירה"
    KNOWN_CITIES_RE = r"(?:גבעתיים|רמת גן|תל אביב|בני ברק|פתח תקווה|רמת השרון|חולון|בת ים)"
    address = ""
    for sale_marker in ["דירה למכירה", "דירה להשכרה", "דירה לקנייה"]:
        idx = body_text.find(sale_marker)
        if idx > 20:
            before = body_text[:idx].strip()
            lines = [l.strip() for l in before.split("\n") if l.strip()]
            # חפש בשורות האחרונות — הכתובת היא השורה עם שם עיר
            for line in reversed(lines[-6:]):
                if re.search(KNOWN_CITIES_RE, line) and len(line) > 5:
                    address = line
                    break
            if address:
                break

    # Strategy 2: שם רחוב + מספר + עיר (ללא קידומת ב) — אדרס אמיתי
    if not address:
        addr_m = re.search(
            r"([א-ת][א-ת\s'\"]{2,25}\s+\d{1,3})\s*,\s*(?:[א-ת\s]{1,20},\s*)?" + KNOWN_CITIES_RE,
            body_text
        )
        if addr_m:
            address = addr_m.group(0).strip()

    # Strategy 3: "בשכונת X, עיר" / "בעת X, עיר" — fallback (עלול להיות שם שכונה)
    if not address:
        addr_m = re.search(
            r"ב(?:שכונת|רחוב|פרויקט|עת)?\s*([^\n]{5,60}),\s*" + KNOWN_CITIES_RE,
            body_text
        )
        if addr_m:
            address = addr_m.group(0).strip()

    # Strategy 4: CSS selectors fallback
    if not address:
        for sel in ["h1", "[class*='address' i]", "[class*='Address' i]",
                    "[data-testid*='address' i]"]:
            try:
                el = page.query_selector(sel)
                if el:
                    t = el.inner_text().strip()
                    if t and len(t) > 4:
                        address = t
                        break
            except Exception:
                pass

    # --- ניקוי RTL marks לפני חילוץ מחיר ---
    # Madlan embeds U+200F (RTL mark) and U+00A0 (NBSP) around prices
    body_clean = body_text.replace("‏", "").replace("‎", "").replace("\xa0", " ")

    # --- מחיר ---
    price = None
    price_m = re.search(r"([\d,]{5,})\s*₪", body_clean)
    if price_m:
        try:
            price = int(re.sub(r"[^\d]", "", price_m.group(1)))
            if price < 100_000:   # מספרים קטנים = שגיאה
                price = None
        except Exception:
            price = None

    # --- חדרים ---
    # Madlan format: "5\nחדרים" (value before label)
    rooms = None
    r_m = re.search(r"(\d+(?:\.\d)?)\s*\n?חד", body_text)
    if r_m:
        try:
            rooms = float(r_m.group(1))
        except Exception:
            pass

    # --- מ"ר ---
    # Madlan format: "274\nמ״ר" (value before label, with special quote char)
    size_sqm = None
    s_m = re.search(r"(\d{2,4}(?:\.\d)?)\s*\n?מ[״׳\"״׳]?\s*ר", body_text)
    if s_m:
        try:
            size_sqm = int(float(s_m.group(1)))
        except Exception:
            pass

    # --- קומה ---
    # Madlan format: "1\nקומה" (value before label)
    floor = None
    f_m = re.search(r"(\d+)\s*\nקומה", body_text)
    if f_m:
        floor = f_m.group(1).strip()
    else:
        # fallback: "קומה N" format
        f_m2 = re.search(r"קומה\s*([^\s\n,]{1,5})", body_text)
        if f_m2:
            v = f_m2.group(1).strip()
            # sanity: floor should not look like a size (e.g. 274)
            try:
                if int(v) < 50:
                    floor = v
            except Exception:
                floor = v

    # --- נוחיות ---
    # Madlan lists amenities as plain text in "מפרט מלא" section (no ✓/✗).
    # Presence of keyword anywhere in page = has it.
    # ✓/✗ marks (Facebook-style) are also supported as fallback.
    def _amenity(keywords: list) -> int | None:
        for kw in keywords:
            idx = body_text.find(kw)
            if idx == -1:
                continue
            surrounding = body_text[max(0, idx - 30): idx + 30]
            if "✓" in surrounding or "✔" in surrounding:
                return 1
            if "✗" in surrounding or "✘" in surrounding or "×" in surrounding:
                return 0
            # No checkmarks → presence of keyword = has amenity
            return 1
        return None  # לא נמצא כלל

    has_parking  = _amenity(["חניה", "חנייה", "פרקינג"])
    has_mamad    = _amenity(['ממ"ד', "ממד", "מרחב מוגן"])
    has_balcony  = _amenity(["מרפסת", "מרפסת שמש", "טרסה"])
    has_elevator = _amenity(["מעלית"])

    # --- תמונות ---
    img_urls = page.evaluate("""() => {
        const imgs = new Set();
        document.querySelectorAll('img[src]').forEach(img => {
            const s = img.src || img.getAttribute('src') || '';
            if (s.includes('madlan') || s.includes('cloudinary') ||
                s.includes('.jpg') || s.includes('.webp')) {
                imgs.add(s);
            }
        });
        return [...imgs].slice(0, 10);
    }""") or []

    # --- post_id מה-URL ---
    uid_m = re.search(r"/(?:item|listings)/([A-Za-z0-9_-]+)", url)
    raw_id = uid_m.group(1) if uid_m else _safe_id(url)
    post_id = f"madlan_bul_{raw_id}"

    # --- תאריך ---
    date_m = re.search(r"(\d{1,2})[./](\d{1,2})[./](\d{4})", body_text)
    posted_at = None
    if date_m:
        try:
            d, mo, y = date_m.groups()
            posted_at = f"{y}-{int(mo):02d}-{int(d):02d}"
        except Exception:
            pass

    # --- הורדת תמונות ---
    local_imgs = download_images(
        f"madlan_bul_{_safe_id(raw_id)}", img_urls,
        referer="https://www.madlan.co.il"
    ) if img_urls else []

    return {
        "post_id":     post_id,
        "group_name":  "מדלן",
        "group_id":    "madlan",
        "text":        body_text[:500],
        "price":       price,
        "rooms":       rooms,
        "size_sqm":    size_sqm,
        "floor":       floor,
        "has_mamad":   has_mamad,
        "has_parking": has_parking,
        "has_balcony": has_balcony,
        "has_elevator":has_elevator,
        "post_url":    url,
        "posted_at":   posted_at,
        "source":      "madlan",
        "address":     address,
        "lat":         None,
        "lon":         None,
        "images_json": json.dumps(local_imgs) if local_imgs else None,
        "phone":       None,
    }


# ---------------------------------------------------------------------------
# Main scrape function
# ---------------------------------------------------------------------------

def scrape_madlan(page: Page, log=None) -> int:
    config = load_config()
    new_count = 0

    def _log(msg):
        if log: log(msg)
        else:   print(msg, flush=True)

    try:
        from playwright_stealth import Stealth
        Stealth().apply_stealth_sync(page)
    except Exception:
        pass

    # יוצרים solver פעם אחת — משתמשים בו בכל הדפים
    solver = None
    try:
        from scrapers.madlan_captcha_solver import PerimeterXSolver
        solver = PerimeterXSolver(profile_dir=MADLAN_PROFILE)
    except Exception as e:
        pass

    # --- שלב 1: איסוף קישורים ---
    # Use config madlan_url if provided (has pre-applied filters), else fallback
    search_url = config.get("חיפוש", {}).get("madlan_url") or RESALE_URL
    _log(f"מדלן: סורק מודעות ({search_url[:60]}...)")
    urls = _collect_urls(page, search_url, _log, max_listings=60)

    if not urls:
        _log("מדלן: לא נמצאו מודעות")
        return 0

    # --- שלב 2: ביקור בכל מודעה ---
    _log(f"מדלן: פותח {len(urls)} מודעות...")
    visited = 0
    passed  = 0
    session_recovered = False   # האם כבר עשינו המתנה ידנית פעם אחת בסשן הזה

    i = 0
    while i < len(urls):
        url = urls[i]
        try:
            data = _scrape_listing_page(page, url, _log, _solver=solver)
            i += 1
            if data is None:
                continue
            visited += 1

            if passes_config_filters(data, config):
                passed += 1
                if save_apartment(data):
                    new_count += 1
                    _log(f"  ✓ [{i}/{len(urls)}] {data.get('address')} | "
                         f"{data.get('rooms')}חד | {data.get('size_sqm')}מ² | "
                         f"{data.get('price', 0):,}₪")

            time.sleep(random.uniform(2.5, 5.0))   # delay אנושי — מספיק ארוך לא לעורר PX

        except CaptchaBlocked:
            if not session_recovered:
                # פעם ראשונה — ממתין פעם אחת גלובלית ואז מנסה שוב את אותה מודעה
                _log("  PX Solver נכשל — ממתין לפתרון ידני בדפדפן...")
                solved = _wait_for_captcha_solve(page, _log, timeout_min=5)
                if solved:
                    session_recovered = True
                    _log("  מדלן: session שוחזר — ממשיך סריקה")
                    # לא מקדמים את i — ננסה שוב את אותה URL
                else:
                    _log("  מדלן: CAPTCHA לא נפתר — מדלג על שאר המודעות")
                    break
            else:
                # כבר שחזרנו פעם — CAPTCHA חזר, דולגים על מודעה זו
                _log(f"  מדלן: CAPTCHA שוב ב-{url} — דילוג")
                i += 1

        except Exception as e:
            _log(f"מדלן: שגיאה במודעה {url}: {e}")
            i += 1

    _log(f"מדלן: {visited} מודעות נבדקו, {passed} עברו סינון, {new_count} חדשות")
    _log(f'מדלן: סה"כ {new_count} דירות חדשות נשמרו')
    return new_count
