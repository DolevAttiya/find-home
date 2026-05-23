import sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import yaml
from playwright.sync_api import sync_playwright

with open("config.yaml", encoding="utf-8") as f:
    config = yaml.safe_load(f)

url = config["חיפוש"]["madlan_url"]

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page(viewport={"width": 1280, "height": 800})
    page.goto(url, wait_until="networkidle", timeout=30000)
    time.sleep(8)

    # גלול
    for _ in range(5):
        page.keyboard.press("End")
        time.sleep(2)
    page.keyboard.press("Home")
    time.sleep(2)

    # שמור HTML
    html = page.content()
    with open("debug_madlan.html", "w", encoding="utf-8") as f:
        f.write(html)
    print(f"HTML נשמר ({len(html)} תווים)")

    page.screenshot(path="debug_madlan2.png")

    # נסה סלקטורים
    selectors = [
        "[class*='listing-card']",
        "[class*='ListingCard']",
        "[class*='listing_card']",
        "[class*='asset-item']",
        "[class*='AssetItem']",
        "[class*='feed-item']",
        "[class*='FeedItem']",
        "[class*='property']",
        "[class*='nadlan']",
        "article",
        "li[class*='item']",
        "div[class*='item']",
        "[data-item-id]",
        "[data-listing-id]",
        "[data-asset-id]",
    ]
    print("\nסלקטורים:")
    for sel in selectors:
        try:
            count = len(page.query_selector_all(sel))
            if count > 0:
                print(f"  '{sel}' → {count}")
        except Exception as e:
            print(f"  '{sel}' → ERROR: {e}")

    browser.close()
    print("סיום")
