"""
מדפיס bulletin ראשון במלואו ממדלן.
"""
import sys, io, time, json, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from playwright.sync_api import sync_playwright

MADLAN_PROFILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "madlan_profile")
BASE_URL   = "https://www.madlan.co.il/for-sale/%D7%92%D7%91%D7%A2%D7%AA%D7%99%D7%99%D7%9D-%D7%99%D7%A9%D7%A8%D7%90%D7%9C"
RESALE_URL = BASE_URL + "?dealType=secondHand"

all_bulletins = []
all_projects  = []

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
                all_bulletins.append(poi)
            elif poi.get("type") == "project":
                all_projects.append(poi)
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

    # פרויקטים (new construction)
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=40000)
    time.sleep(7)
    for _ in range(5):
        page.keyboard.press("End")
        time.sleep(1.5)
    time.sleep(2)

    # יד שנייה (resale bulletins)
    page.goto(RESALE_URL, wait_until="domcontentloaded", timeout=40000)
    time.sleep(7)
    for _ in range(5):
        page.keyboard.press("End")
        time.sleep(1.5)
    time.sleep(2)

    context.close()

print(f"פרויקטים: {len(all_projects)}  |  bulletins: {len(all_bulletins)}\n")

if all_bulletins:
    print("=== BULLETIN ראשון (מלא) ===")
    print(json.dumps(all_bulletins[0], ensure_ascii=False, indent=2))
    if len(all_bulletins) > 1:
        print("\n=== BULLETIN שני (מלא) ===")
        print(json.dumps(all_bulletins[1], ensure_ascii=False, indent=2))
