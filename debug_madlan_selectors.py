import sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page(
        viewport={"width": 1280, "height": 900},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    Stealth().apply_stealth_sync(page)

    url = "https://www.madlan.co.il/for-sale/apartment/%D7%92%D7%91%D7%A2%D7%AA%D7%99%D7%99%D7%9D"
    print(f"טוען: {url}")
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    time.sleep(8)
    for _ in range(4):
        page.keyboard.press("End")
        time.sleep(2)

    html_size = len(page.content())
    print(f"HTML: {html_size} תווים")

    # כל הסלקטורים האפשריים
    selectors = [
        "[class*='listing-card']",
        "[class*='ListingCard']",
        "[class*='listing_card']",
        "[class*='PropertyCard']",
        "[class*='property-card']",
        "[class*='asset-item']",
        "[class*='AssetItem']",
        "[class*='feed-item']",
        "[class*='FeedItem']",
        "article",
        "li[class]",
        "[data-item-id]",
        "[data-listing-id]",
        "[data-testid*='listing']",
        "[data-testid*='item']",
        "[data-testid*='card']",
        "[class*='result']",
        "[class*='Result']",
        "a[href*='/item/']",
        "a[href*='/nadlan/']",
    ]

    print("\nסלקטורים שמצאו משהו:")
    for sel in selectors:
        try:
            count = len(page.query_selector_all(sel))
            if count > 0:
                print(f"  '{sel}' → {count}")
        except Exception as e:
            print(f"  '{sel}' → ERROR: {e}")

    # מצא אלמנטים שמכילים ₪
    print("\nאלמנטים שמכילים ₪:")
    try:
        els_with_price = page.evaluate("""() => {
            const results = [];
            document.querySelectorAll('*').forEach(el => {
                if (el.children.length < 10 && el.innerText && el.innerText.includes('₪')) {
                    const cls = el.className || '';
                    const tag = el.tagName;
                    const text = el.innerText.trim().slice(0, 100);
                    if (text.length < 300) {
                        results.push({ tag, cls: cls.slice(0, 80), text });
                    }
                }
            });
            return results.slice(0, 20);
        }""")
        for item in els_with_price:
            print(f"  <{item['tag']} class='{item['cls']}'> {item['text'][:80]}")
    except Exception as e:
        print(f"שגיאה: {e}")

    browser.close()
    print("\nסיום")
