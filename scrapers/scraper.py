import re
import time
import yaml
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from core.database import save_apartment, save_group, get_groups, init_db

load_dotenv()

FB_EMAIL = os.getenv("FB_EMAIL")
FB_PASSWORD = os.getenv("FB_PASSWORD")


def load_config() -> dict:
    with open("config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


# --- חילוץ נתונים מטקסט ---

def extract_price(text: str) -> int | None:
    patterns = [
        r"(\d[\d,\.]+)\s*[₪]",
        r"(\d[\d,\.]+)\s*שח",
        r"(\d[\d,\.]+)\s*שקל",
        r"מחיר[:\s]+(\d[\d,\.]+)",
        r"(\d[\d,\.]+)\s*ש[\"']ח",
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            return int(re.sub(r"[,\.]", "", m.group(1)))
    return None


def extract_rooms(text: str) -> float | None:
    patterns = [
        r"(\d+\.?\d*)\s*חדרים",
        r"(\d+\.?\d*)\s*חד['\"]",
        r"דירת\s+(\d+\.?\d*)",
        r"(\d+\.?\d*)\s*rm",
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            return float(m.group(1))
    return None


def extract_size(text: str) -> int | None:
    patterns = [
        r"(\d+)\s*מ[\"']ר",
        r"(\d+)\s*מטר",
        r"(\d+)\s*sqm",
        r"שטח[:\s]+(\d+)",
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            return int(m.group(1))
    return None


def extract_floor(text: str) -> str | None:
    m = re.search(r"קומה\s+(\d+)(?:\s+מתוך\s+(\d+))?", text)
    if m:
        return f"{m.group(1)}/{m.group(2)}" if m.group(2) else m.group(1)
    if "קרקע" in text or "קומת קרקע" in text:
        return "0"
    return None


def extract_address(text: str) -> str | None:
    patterns = [
        r"רחוב\s+([֐-׿\s\"\']+?\d*)",
        r"ברח[\'\"]\s*([֐-׿\s]+?\d*)",
        r"([֐-׿]+\s+\d+(?:\s*[א-ת])?)\s*,?\s*(?:גבעתיים|תל אביב|רמת גן|ר\"ג)",
        r"רח[\'\"]\s*([֐-׿\s]+\d+)",
        r"כתובת[:\s]+([֐-׿\s\d]+)",
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            addr = m.group(1).strip().strip(".,")
            if len(addr) > 2:
                return addr
    return None


def _mentioned(text: str, keywords: list) -> bool | None:
    """True אם מוזכר, None אם לא מוזכר (טקסט חופשי — שתיקה ≠ אין)"""
    return True if any(w in text for w in keywords) else None


def extract_features(text: str) -> dict:
    return {
        "has_mamad":    _mentioned(text, ['ממ"ד', "ממד", "מרחב מוגן"]),
        "has_parking":  _mentioned(text, ["חניה", "חנייה", "פרקינג"]),
        "has_balcony":  _mentioned(text, ["מרפסת", "מרפסות"]),
        "has_elevator": _mentioned(text, ["מעלית"]),
    }


def extract_phone(text: str) -> str | None:
    """מחלץ מספר טלפון ישראלי מטקסט"""
    patterns = [
        r"\+972[-\s]?[5-9]\d[-\s]?\d{3}[-\s]?\d{4}",  # +972-50-1234567
        r"0[5-9]\d[-\s]?\d{3}[-\s]?\d{4}",              # 050-1234567 / 0501234567
        r"0[2-4678][-\s]?\d{3}[-\s]?\d{4}",             # קווי: 03-1234567
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            return m.group(0)
    return None


def passes_filters(data: dict, config: dict) -> bool:
    cfg_rooms = config.get("חדרים", {})
    cfg_price = config.get("מחיר", {})
    cfg_size = config.get("גודל_במטר", {})
    blocked = config.get("מילות_חסימה", [])
    required = config.get("מילות_מפתח_חובה", [])
    text = data.get("text", "")

    if any(w in text for w in blocked):
        return False

    if required and not any(w in text for w in required):
        return False

    if cfg_price.get("רק_פוסטים_עם_מחיר") and data.get("price") is None:
        return False
    if data.get("price"):
        if cfg_price.get("מינימום") and data["price"] < cfg_price["מינימום"]:
            return False
        if cfg_price.get("מקסימום") and data["price"] > cfg_price["מקסימום"]:
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


# --- Playwright ---

SESSION_PATH = "fb_session.json"


def has_session() -> bool:
    return os.path.exists(SESSION_PATH)


def verify_logged_in(page) -> bool:
    page.goto("https://www.facebook.com/", wait_until="domcontentloaded")
    time.sleep(2)
    return "login" not in page.url and page.query_selector('input[name="email"]') is None


def search_groups(page, config: dict) -> list[dict]:
    """מחפש קבוצות רלוונטיות ומחזיר רשימה"""
    found_groups = []
    location = config.get("חיפוש", {}).get("מיקום", "")
    search_terms = config.get("חיפוש", {}).get("מילות_חיפוש_קבוצות", ["דירות להשכרה"])

    for term in search_terms:
        query = f"{term} {location}".strip()
        page.goto(f"https://www.facebook.com/search/groups?q={query}", wait_until="domcontentloaded")
        time.sleep(3)

        for _ in range(3):
            page.keyboard.press("End")
            time.sleep(1.5)

        group_links = page.query_selector_all("a[href*='/groups/']")
        for link in group_links:
            href = link.get_attribute("href") or ""
            m = re.search(r"/groups/([^/?]+)", href)
            if not m:
                continue
            group_id = m.group(1)
            if group_id in ["feed", "discover", "create", "joins"]:
                continue
            name = link.inner_text().strip()
            if name and group_id:
                found_groups.append({"group_id": group_id, "group_name": name or group_id})

    seen = set()
    unique = []
    for g in found_groups:
        if g["group_id"] not in seen:
            seen.add(g["group_id"])
            unique.append(g)

    return unique


def scrape_group(page, group: dict, config: dict) -> int:
    """סורק קבוצה אחת, מחזיר כמה פוסטים חדשים נמצאו"""
    max_posts = config.get("סריקה", {}).get("מקסימום_פוסטים_לקבוצה", 50)
    group_id = group["group_id"]
    group_name = group["group_name"]
    new_count = 0

    try:
        page.goto(f"https://www.facebook.com/groups/{group_id}", wait_until="domcontentloaded")
        time.sleep(3)
    except PlaywrightTimeout:
        return 0

    posts_seen = 0
    scroll_attempts = 0

    while posts_seen < max_posts and scroll_attempts < 20:
        # לחץ על כל כפתורי "ראה עוד" לפני קריאת הטקסט
        see_more_btns = page.query_selector_all(
            "div[role='button']:has-text('ראה עוד'), "
            "div[role='button']:has-text('See more'), "
            "[data-ad-preview='message'] ~ * [role='button']"
        )
        for btn in see_more_btns:
            try:
                btn.click(timeout=2000)
                time.sleep(0.3)
            except Exception:
                pass

        post_elements = page.query_selector_all("[data-ad-preview='message'], [data-testid='post_message']")

        for el in post_elements[posts_seen:]:
            try:
                text = el.inner_text()
            except Exception:
                continue

            post_url = ""
            try:
                post_url = el.evaluate("""el => {
                    let node = el;
                    for (let i = 0; i < 12; i++) {
                        if (!node || !node.parentElement) break;
                        node = node.parentElement;

                        // הדרך הכי אמינה: לינק של הטיימסטמפ
                        const timeLink = node.querySelector('a[href] > abbr, a[href] > span[data-utime]');
                        if (timeLink) {
                            const a = timeLink.closest('a');
                            if (a && a.href && (a.href.includes('/posts/') || a.href.includes('/permalink/'))) {
                                return a.href;
                            }
                        }

                        // fallback: כל לינק לפוסט
                        for (const sel of ['a[href*="/posts/"]', 'a[href*="/permalink/"]', 'a[href*="story_fbid"]']) {
                            const a = node.querySelector(sel);
                            if (a && a.href) return a.href;
                        }
                    }
                    return '';
                }""")
            except Exception:
                pass

            price = extract_price(text)
            rooms = extract_rooms(text)
            size_sqm = extract_size(text)
            floor = extract_floor(text)
            features = extract_features(text)
            address = extract_address(text)
            phone = extract_phone(text)

            post_data = {
                "post_id": f"{group_id}_{hash(text[:100])}",
                "group_id": group_id,
                "group_name": group_name,
                "text": text,
                "price": price,
                "rooms": rooms,
                "size_sqm": size_sqm,
                "floor": floor,
                "post_url": post_url,
                "posted_at": None,
                "source": "facebook",
                "address": address,
                "phone": phone,
                **features,
            }

            if passes_filters(post_data, config):
                if save_apartment(post_data):
                    new_count += 1

        posts_seen = len(post_elements)
        page.keyboard.press("End")
        time.sleep(2)
        scroll_attempts += 1

    return new_count


def _launch_worker(args: list) -> tuple[int, str | None]:
    """מריץ worker subprocess, מחזיר (new_count, error)"""
    import subprocess, sys
    proc = subprocess.Popen(
        [sys.executable, "workers/worker.py"] + args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    new_count = 0
    for line in proc.stdout:
        line = line.strip()
        if line.startswith("__RESULT__:"):
            try:
                new_count = int(line[len("__RESULT__:"):])
            except ValueError:
                pass
        elif line:
            print(line, flush=True)
    proc.wait()
    return new_count, None if proc.returncode == 0 else f"exit code {proc.returncode}"


def run_scrape(status_callback=None) -> dict:
    """מריץ סריקה מלאה במקביל, מחזיר סיכום"""
    import json
    from concurrent.futures import ThreadPoolExecutor, as_completed

    init_db()
    config = load_config()
    results = {"new_apartments": 0, "groups_scanned": 0, "errors": []}
    FB_PARALLEL = 4  # כמה קבוצות פייסבוק במקביל

    def log(msg):
        if status_callback:
            status_callback(msg)
        else:
            print(msg, flush=True)

    if not has_session():
        raise Exception("לא נמצא session - הרץ תחילה: python save_session.py")

    # --- Phase 1: כניסה לפייסבוק + מציאת קבוצות (sequential) ---
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            storage_state=SESSION_PATH,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
        )
        page = context.new_page()
        try:
            log("מאמת חיבור לפייסבוק...")
            if not verify_logged_in(page):
                raise Exception("ה-session פג תוקף - הרץ שוב: python save_session.py")

            log("מחפש קבוצות רלוונטיות...")
            found_groups = search_groups(page, config)
            log(f"נמצאו {len(found_groups)} קבוצות")
            for g in found_groups:
                save_group(g)
        except Exception as e:
            results["errors"].append(str(e))
            browser.close()
            return results
        finally:
            browser.close()

    existing_groups = get_groups()
    all_groups = list({g["group_id"]: g for g in existing_groups}.values())

    # --- Phase 2: סריקה מקבילית ---
    log(f"מתחיל סריקה מקבילית ({FB_PARALLEL} קבוצות + מדלן + יד2)...")

    tasks = {}  # future → label
    with ThreadPoolExecutor(max_workers=FB_PARALLEL + 2) as pool:
        # פייסבוק - 4 קבוצות במקביל
        for group in all_groups:
            f = pool.submit(_launch_worker, ["facebook", json.dumps(group, ensure_ascii=False)])
            tasks[f] = group["group_name"]

        # מדלן ויד2 במקביל לפייסבוק
        tasks[pool.submit(_launch_worker, ["madlan"])] = "מדלן"
        tasks[pool.submit(_launch_worker, ["yad2"])] = "יד2"

        for future in as_completed(tasks):
            label = tasks[future]
            try:
                new, err = future.result()
                results["new_apartments"] += new
                results["groups_scanned"] += 1
                log(f"  ✓ {label}: {new} דירות חדשות")
                if err:
                    results["errors"].append(f"{label}: {err}")
            except Exception as e:
                results["errors"].append(f"{label}: {e}")

    # Geocoding לכתובות חדשות
    if results["new_apartments"] > 0:
        try:
            from geocoder import geocode_pending
            config = load_config()
            city = config.get("חיפוש", {}).get("מיקום", "")
            log("ממיר כתובות לקואורדינטות...")
            geocode_pending(city=city)
        except Exception as e:
            results["errors"].append(f"geocoding: {e}")

    return results


if __name__ == "__main__":
    import json

    def print_status(msg):
        print(msg, flush=True)

    results = run_scrape(status_callback=print_status)
    print("__RESULT__:" + json.dumps(results, ensure_ascii=False), flush=True)
