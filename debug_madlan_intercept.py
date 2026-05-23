import sys, io, time, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

# כל ה-API calls
api_calls = []

def handle_response(response):
    try:
        content_type = response.headers.get("content-type", "")
        url = response.url
        if "json" in content_type and response.status == 200:
            if any(kw in url for kw in ["search", "listing", "feed", "asset", "properties", "nadlan", "graphql", "api", "nadlanApi"]):
                try:
                    body = response.body()
                    text = body.decode("utf-8", errors="replace")
                    api_calls.append({"url": url, "text": text[:2000]})
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

    # URL פשוט - הצליח בפעם הראשונה
    url = "https://www.madlan.co.il/for-sale/apartment/%D7%92%D7%91%D7%A2%D7%AA%D7%99%D7%99%D7%9D"
    print(f"טוען: {url}")
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    time.sleep(8)
    for _ in range(3):
        page.keyboard.press("End")
        time.sleep(2)

    html_size = len(page.content())
    print(f"HTML: {html_size} תווים")

    # בדוק כרטיסיות
    for sel in ["[class*='listing-card']", "[class*='ListingCard']", "article", "li[class*='item']"]:
        count = len(page.query_selector_all(sel))
        if count:
            print(f"  {sel} → {count}")

    print(f"\n{len(api_calls)} קריאות API:")
    for call in api_calls[:10]:
        print(f"\n  URL: {call['url'][:150]}")
        print(f"  Data: {call['text'][:400]}")
        with open(f"api_{len(api_calls)}.json", "w", encoding="utf-8") as f:
            f.write(call['text'])

    browser.close()
    print("סיום")
