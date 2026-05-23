import sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import yaml
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

with open("config.yaml", encoding="utf-8") as f:
    config = yaml.safe_load(f)

url = config["חיפוש"]["madlan_url"]

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page(
        viewport={"width": 1280, "height": 900},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    Stealth().apply_stealth_sync(page)

    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    time.sleep(6)
    for _ in range(4):
        page.keyboard.press("End")
        time.sleep(2)

    # שמור HTML
    html = page.content()
    with open("debug_madlan_full.html", "w", encoding="utf-8") as f:
        f.write(html)
    print(f"HTML: {len(html)} תווים")

    # מצא כל div/li/article עם class שמכיל מחיר בטקסט
    els = page.query_selector_all("div[class], li[class], article[class], a[class]")
    print(f"\nכל האלמנטים עם class: {len(els)}")

    candidates = []
    for el in els:
        try:
            text = el.inner_text()
            cls = el.get_attribute("class") or ""
            # מחפש אלמנטים שמכילים ₪ או "חדרים"
            if ("₪" in text or "חדרים" in text or "ש״ח" in text) and len(text) < 800:
                candidates.append((cls[:80], text[:200]))
        except Exception:
            pass

    print(f"\nמועמדים עם מחיר/חדרים: {len(candidates)}")
    for cls, text in candidates[:10]:
        print(f"\nclass: {cls}")
        print(f"text: {text[:150]}")

    browser.close()
    print("\nסיום")
