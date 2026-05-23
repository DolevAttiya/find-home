"""
מדפיס את כל שדות ה-bulletin הראשון כדי לאתר שדות נוחיות.
"""
import sys, io, time, json, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from playwright.sync_api import sync_playwright

MADLAN_PROFILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "madlan_profile")
RESALE_URL = "https://www.madlan.co.il/for-sale/%D7%92%D7%91%D7%A2%D7%AA%D7%99%D7%99%D7%9D-%D7%99%D7%A9%D7%A8%D7%90%D7%9C?dealType=secondHand"

bulletins = []

def on_response(resp):
    if "madlan.co.il/api" not in resp.url:
        return
    if "json" not in resp.headers.get("content-type", ""):
        return
    try:
        body = resp.json()
        data = body.get("data", {}) if isinstance(body, dict) else {}
        spv2 = data.get("searchPoiV2", {}) if isinstance(data, dict) else {}
        for poi in (spv2.get("poi") or []):
            if poi.get("type") == "bulletin":
                bulletins.append(poi)
    except Exception:
        pass

with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(
        user_data_dir=MADLAN_PROFILE, headless=False,
        viewport={"width": 1440, "height": 900},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        ignore_default_args=["--enable-automation"],
    )
    page = context.new_page()
    page.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});window.chrome={runtime:{}};")
    page.on("response", on_response)

    page.goto(RESALE_URL, wait_until="domcontentloaded", timeout=40000)
    try:
        page.wait_for_load_state("networkidle", timeout=12000)
    except Exception:
        pass
    time.sleep(2)
    context.close()

print(f"נלכדו {len(bulletins)} bulletins\n")
if bulletins:
    b = bulletins[0]
    print("=== כל המפתחות של bulletin ===")
    print(sorted(b.keys()))
    print()
    # print fields likely related to amenities
    for key in sorted(b.keys()):
        val = b[key]
        # skip large fields
        if key in ('images', 'text', 'description'):
            print(f"  {key}: [...]")
        else:
            print(f"  {key}: {json.dumps(val, ensure_ascii=False)}")
