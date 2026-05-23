import sys, io, time, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import yaml
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

with open("config.yaml", encoding="utf-8") as f:
    config = yaml.safe_load(f)

url = config["חיפוש"]["madlan_url"]

api_calls = []

def handle_response(response):
    try:
        if any(kw in response.url for kw in ["api", "search", "listing", "feed", "asset", "properties", "nadlan", "graphql"]):
            if "madlan" in response.url:
                content_type = response.headers.get("content-type", "")
                if "json" in content_type:
                    try:
                        body = response.json()
                        api_calls.append({
                            "url": response.url[:200],
                            "status": response.status,
                            "data_preview": str(body)[:500]
                        })
                    except Exception:
                        pass
    except Exception:
        pass

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page(
        viewport={"width": 1280, "height": 900},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    Stealth().apply_stealth_sync(page)
    page.on("response", handle_response)

    print(f"טוען: {url}")
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    time.sleep(8)
    for _ in range(3):
        page.keyboard.press("End")
        time.sleep(2)

    html_size = len(page.content())
    print(f"HTML: {html_size} תווים")

    print(f"\n{len(api_calls)} קריאות API נמצאו:")
    for call in api_calls:
        print(f"\n  URL: {call['url']}")
        print(f"  Status: {call['status']}")
        print(f"  Data: {call['data_preview'][:300]}")

    # גם נסה לחלץ מה-window object
    try:
        state = page.evaluate("() => { try { return JSON.stringify(window.__NEXT_DATA__ || window.__PRELOADED_STATE__ || {}) } catch(e) { return '{}' } }")
        if len(state) > 10:
            print(f"\nwindow state: {state[:500]}")
            with open("window_state.json", "w", encoding="utf-8") as f:
                f.write(state)
    except Exception as e:
        print(f"window state error: {e}")

    browser.close()
    print("\nסיום")
