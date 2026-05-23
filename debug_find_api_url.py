"""
מדפיס את כל ה-API URLs שנשלחים בזמן טעינת דף הרשימה + גוף הבקשות.
"""
import sys, io, time, json, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from playwright.sync_api import sync_playwright

MADLAN_PROFILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "madlan_profile")
LIST_URL = "https://www.madlan.co.il/for-sale/%D7%92%D7%91%D7%A2%D7%AA%D7%99%D7%99%D7%9D-%D7%99%D7%A9%D7%A8%D7%90%D7%9C?dealType=secondHand"

api_requests = []

def on_request(req):
    if "madlan.co.il" in req.url:
        try:
            body = req.post_data
            api_requests.append({"url": req.url, "method": req.method, "body": body[:500] if body else None})
        except Exception:
            api_requests.append({"url": req.url, "method": req.method, "body": None})

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
    page.on("request", on_request)

    page.goto(LIST_URL, wait_until="domcontentloaded", timeout=40000)
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        pass
    time.sleep(2)
    context.close()

print(f"נלכדו {len(api_requests)} API requests\n")
for r in api_requests:
    print(f"URL: {r['url']}")
    if r['body']:
        try:
            b = json.loads(r['body'])
            op = b.get('operationName', '')
            print(f"  operation: {op}")
            # print variable keys only
            vars_ = b.get('variables', {})
            print(f"  variables: {list(vars_.keys()) if isinstance(vars_, dict) else vars_}")
        except Exception:
            print(f"  body: {r['body'][:200]}")
    print()
