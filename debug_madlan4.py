import sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import yaml
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

with open("config.yaml", encoding="utf-8") as f:
    config = yaml.safe_load(f)

url = config["חיפוש"]["madlan_url"]
print(f"URL: {url}\n")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page(
        viewport={"width": 1280, "height": 900},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    Stealth().apply_stealth_sync(page)

    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    time.sleep(6)

    # גלול
    for _ in range(4):
        page.keyboard.press("End")
        time.sleep(2)

    page.screenshot(path="debug_madlan_stealth.png")

    cards = page.query_selector_all("[class*='listing-card']")
    print(f"כרטיסיות: {len(cards)}")

    for i, card in enumerate(cards[:3]):
        print(f"\n=== כרטיסייה {i+1} ===")
        text = card.inner_text()
        print(text[:300])

        link = card.query_selector("a[href]")
        if link:
            print(f"href: {link.get_attribute('href')}")

        # בדוק sub-elements
        for sub_sel in ["[class*='price']", "[class*='Price']", "[class*='room']", "[class*='Room']",
                        "[class*='address']", "[class*='Address']", "[class*='area']", "[class*='size']"]:
            el = card.query_selector(sub_sel)
            if el:
                print(f"  {sub_sel}: {el.inner_text()[:50]}")

    html_len = len(page.content())
    print(f"\nHTML size: {html_len} תווים")
    if html_len < 20000:
        print("WARNING: HTML קטן מדי - ייתכן שיש חסימת בוט")

    browser.close()
    print("סיום")
