"""
טוען דף רשימה תחילה (session valid), ואז מנווט לדף מודעה בודדת
ומחפש API response עם נתוני הנוחיות.
"""
import sys, io, time, json, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from playwright.sync_api import sync_playwright

MADLAN_PROFILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "madlan_profile")
LIST_URL  = "https://www.madlan.co.il/for-sale/%D7%92%D7%91%D7%A2%D7%AA%D7%99%D7%99%D7%9D-%D7%99%D7%A9%D7%A8%D7%90%D7%9C?dealType=secondHand"

# ID מה-DB שלנו
BUL_ID    = "dj7qyUGkZKV"
ITEM_URL  = f"https://www.madlan.co.il/item/{BUL_ID}"

all_json = []

def on_response(resp):
    ct = resp.headers.get("content-type", "")
    if "json" not in ct:
        return
    if "madlan.co.il" not in resp.url:
        return
    try:
        body = resp.json()
        all_json.append({"url": resp.url, "body": body})
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

    # --- שלב 1: דף רשימה (warm up session) ---
    print("טוען דף רשימה...")
    page.goto(LIST_URL, wait_until="domcontentloaded", timeout=40000)
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        pass
    time.sleep(2)
    print(f"  HTML: {len(page.content())} תווים")
    print(f"  JSON responses עד כה: {len(all_json)}")

    # --- שלב 2: דף מודעה בודדת ---
    print(f"\nמנווט ל: {ITEM_URL}")
    all_json.clear()
    page.goto(ITEM_URL, wait_until="domcontentloaded", timeout=40000)
    try:
        page.wait_for_load_state("networkidle", timeout=12000)
    except Exception:
        pass
    time.sleep(3)
    print(f"  HTML: {len(page.content())} תווים")
    print(f"  JSON responses שנלכדו: {len(all_json)}")

    context.close()

print("\n=== JSON Responses ===")
for item in all_json:
    print(f"\nURL: {item['url']}")
    body = item['body']
    if isinstance(body, dict):
        data = body.get('data', {})
        if isinstance(data, dict):
            for k, v in data.items():
                print(f"  operation: {k}")
                if isinstance(v, dict):
                    for fk, fv in v.items():
                        fv_str = json.dumps(fv, ensure_ascii=False)
                        print(f"    {fk}: {fv_str[:200]}")
        else:
            print(json.dumps(body, ensure_ascii=False)[:500])
