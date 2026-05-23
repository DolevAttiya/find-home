from playwright.sync_api import sync_playwright
import time
from dotenv import load_dotenv
import os

load_dotenv()
FB_EMAIL = os.getenv("FB_EMAIL")
FB_PASSWORD = os.getenv("FB_PASSWORD")

print(f"Email loaded: {'yes' if FB_EMAIL else 'NO - check .env'}")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, slow_mo=500)
    page = browser.new_page(viewport={"width": 1280, "height": 800})

    page.goto("https://www.facebook.com/", wait_until="domcontentloaded")
    time.sleep(3)

    page.screenshot(path="debug_1_loaded.png")
    print("צילום מסך נשמר: debug_1_loaded.png")

    # הדפס את כל ה-inputs שנמצאים בדף
    inputs = page.query_selector_all("input")
    print(f"נמצאו {len(inputs)} שדות input:")
    for inp in inputs:
        name = inp.get_attribute("name") or ""
        id_  = inp.get_attribute("id") or ""
        type_ = inp.get_attribute("type") or ""
        print(f"  name={name!r} id={id_!r} type={type_!r}")

    # נסה למלא
    try:
        page.fill('input[name="email"]', FB_EMAIL, timeout=5000)
        page.fill('input[name="pass"]', FB_PASSWORD, timeout=5000)
        page.screenshot(path="debug_2_filled.png")
        print("צילום מסך נשמר: debug_2_filled.png")
        page.click('button[name="login"]', timeout=5000)
        time.sleep(5)
        page.screenshot(path="debug_3_after_login.png")
        print("צילום מסך נשמר: debug_3_after_login.png")
        print("URL אחרי כניסה:", page.url)
    except Exception as e:
        print(f"שגיאה: {e}")
        page.screenshot(path="debug_error.png")
        print("צילום מסך שגיאה נשמר: debug_error.png")

    input("לחץ Enter לסגירה...")
    browser.close()
