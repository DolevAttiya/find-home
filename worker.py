"""
Worker process - מריץ משימת סריקה בודדת.
Usage:
  python worker.py facebook <group_json>
  python worker.py madlan
  python worker.py yad2
"""
import sys
import json
import time
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
from playwright.sync_api import sync_playwright

SESSION_PATH = "fb_session.json"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"


def log(msg):
    print(msg, flush=True)


def make_browser(p, use_session=False, session_path=None):
    browser = p.chromium.launch(headless=False)
    kwargs = dict(
        user_agent=UA,
        viewport={"width": 1280, "height": 800},
    )
    if use_session:
        kwargs["storage_state"] = session_path or SESSION_PATH
    return browser, browser.new_context(**kwargs)


def run_facebook(group: dict):
    from scraper import scrape_group, load_config
    from database import init_db

    init_db()
    config = load_config()
    log(f"[FB] סורק: {group['group_name']}")

    with sync_playwright() as p:
        browser, context = make_browser(p, use_session=True)
        page = context.new_page()
        try:
            new = scrape_group(page, group, config)
            log(f"[FB] {group['group_name']}: {new} דירות חדשות")
            print(f"__RESULT__:{new}", flush=True)
        except Exception as e:
            log(f"[FB] שגיאה: {e}")
            print("__RESULT__:0", flush=True)
        finally:
            browser.close()


def run_madlan():
    from database import init_db
    from madlan_scraper import scrape_madlan
    import os, socket

    MADLAN_PROFILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "madlan_profile")
    CDP_PORT = 9222

    STEALTH_SCRIPT = """
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        window.chrome = { runtime: {} };
    """

    def _cdp_alive():
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                return s.connect_ex(("127.0.0.1", CDP_PORT)) == 0
        except Exception:
            return False

    init_db()
    with sync_playwright() as p:
        # אם CDP לא פעיל — מנסה להפעיל Chrome אמיתי אוטומטית
        if not _cdp_alive():
            try:
                from madlan_captcha_solver import PerimeterXSolver
                _solver = PerimeterXSolver(profile_dir=MADLAN_PROFILE, cdp_port=CDP_PORT)
                if _solver.chrome_path:
                    log("[מדלן] מפעיל Chrome אמיתי...")
                    _solver.launch_chrome()
                    time.sleep(4)
            except Exception as e:
                log(f"[מדלן] לא הצליח להפעיל Chrome: {e}")

        if _cdp_alive():
            # --- עדיפות: התחבר לדפדפן הפתוח (start_madlan_browser.py) ---
            log("[מדלן] מתחבר לדפדפן הקיים (CDP)...")
            try:
                browser = p.chromium.connect_over_cdp(f"http://localhost:{CDP_PORT}")
                ctx = browser.contexts[0] if browser.contexts else browser.new_context(
                    user_agent=UA, viewport={"width": 1440, "height": 900}
                )
                page = ctx.new_page()
                page.add_init_script(STEALTH_SCRIPT)
                try:
                    new = scrape_madlan(page, log=log)
                    print(f"__RESULT__:{new}", flush=True)
                except Exception as e:
                    log(f"[מדלן] שגיאה: {e}")
                    print("__RESULT__:0", flush=True)
                finally:
                    page.close()   # סוגרים רק את הטאב, לא את הדפדפן!
                return
            except Exception as e:
                log(f"[מדלן] חיבור CDP נכשל ({e}), עובר לפרופיל...")

        if os.path.isdir(MADLAN_PROFILE):
            # --- גיבוי: פרופיל קבוע ---
            context = p.chromium.launch_persistent_context(
                user_data_dir=MADLAN_PROFILE,
                headless=False,
                user_agent=UA,
                viewport={"width": 1440, "height": 900},
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
                ignore_default_args=["--enable-automation"],
            )
            page = context.new_page()
            page.add_init_script(STEALTH_SCRIPT)
            try:
                new = scrape_madlan(page, log=log)
                print(f"__RESULT__:{new}", flush=True)
            except Exception as e:
                log(f"[מדלן] שגיאה: {e}")
                print("__RESULT__:0", flush=True)
            finally:
                context.close()
        else:
            # --- ללא פרופיל ---
            browser, context = make_browser(p)
            page = context.new_page()
            page.add_init_script(STEALTH_SCRIPT)
            try:
                new = scrape_madlan(page, log=log)
                print(f"__RESULT__:{new}", flush=True)
            except Exception as e:
                log(f"[מדלן] שגיאה: {e}")
                print("__RESULT__:0", flush=True)
            finally:
                browser.close()

    # ג'יאוקודינג — ממיר כתובות ל-lat/lon עבור כל הדירות שעדיין חסרות קואורדינטות
    try:
        from geocoder import geocode_pending
        log("[מדלן] ממיר כתובות ל-lat/lon...")
        geocode_pending(city="גבעתיים")
    except Exception as e:
        log(f"[מדלן] geocoding שגיאה: {e}")


def run_yad2():
    from yad2_scraper import scrape_yad2
    from database import init_db

    init_db()
    with sync_playwright() as p:
        browser, context = make_browser(p)
        page = context.new_page()
        try:
            new = scrape_yad2(page, log=log)
            print(f"__RESULT__:{new}", flush=True)
        except Exception as e:
            log(f"[יד2] שגיאה: {e}")
            print("__RESULT__:0", flush=True)
        finally:
            browser.close()


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""

    if mode == "facebook":
        group = json.loads(sys.argv[2])
        run_facebook(group)
    elif mode == "madlan":
        run_madlan()
    elif mode == "yad2":
        run_yad2()
    else:
        print(f"Unknown mode: {mode}", flush=True)
        sys.exit(1)
