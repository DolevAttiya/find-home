"""
מבקר בדף מודעה בודדת ומדפיס את ה-API response המלא — כולל שדות נוחיות.
"""
import sys, io, time, json, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from playwright.sync_api import sync_playwright

MADLAN_PROFILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "madlan_profile")
LISTING_URL = "https://www.madlan.co.il/listings/cZmUZETiIiN"

captured = []

all_urls = []

def on_response(resp):
    all_urls.append(resp.url)
    if "madlan.co.il" not in resp.url:
        return
    ct = resp.headers.get("content-type", "")
    if "json" not in ct:
        return
    try:
        body = resp.json()
        if not isinstance(body, dict):
            return
        data = body.get("data", {})
        if not isinstance(data, dict):
            return
        for k, v in data.items():
            captured.append((k, v))
    except Exception as e:
        print(f"err: {e}")

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

    page.goto(LISTING_URL, wait_until="domcontentloaded", timeout=40000)
    try:
        page.wait_for_load_state("networkidle", timeout=12000)
    except Exception:
        pass
    time.sleep(6)
    context.close()

print(f"\nסה\"כ URLs: {len(all_urls)}")
print("madlan URLs:")
for u in all_urls:
    if "madlan" in u:
        print(" ", u[:120])

print(f"\nנלכדו {len(captured)} תשובות API JSON\n")
for op_name, data_val in captured:
    print(f"\n=== {op_name} ===")
    if isinstance(data_val, dict):
        # print all keys + short values
        for k, v in data_val.items():
            if isinstance(v, (list, dict)) and str(v)[:200]:
                print(f"  {k}: {json.dumps(v, ensure_ascii=False)[:300]}")
            else:
                print(f"  {k}: {v}")
    else:
        print(json.dumps(data_val, ensure_ascii=False)[:500])
