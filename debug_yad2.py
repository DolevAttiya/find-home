import sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

url = "https://www.yad2.co.il/realestate/forsale?city=4000&rooms=4-5&price=3000000-4000000"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page(
        viewport={"width": 1280, "height": 900},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    Stealth().apply_stealth_sync(page)
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    time.sleep(6)
    for _ in range(3):
        page.keyboard.press("End")
        time.sleep(2)

    page.screenshot(path="debug_yad2.png")
    print(f"HTML: {len(page.content())} תווים")

    # חפש אלמנטים עם ₪
    results = page.evaluate("""() => {
        const seen = new Set();
        const out = [];
        document.querySelectorAll('*').forEach(el => {
            const t = (el.innerText || '').trim();
            const cls = (el.className && typeof el.className === 'string') ? el.className : '';
            const testid = el.getAttribute('data-testid') || '';
            if (t.includes('₪') && t.length < 600 && el.children.length < 15) {
                const key = (cls + testid).slice(0, 60);
                if (!seen.has(key)) {
                    seen.add(key);
                    out.push({ tag: el.tagName, cls: cls.slice(0,80), testid, txt: t.slice(0,150) });
                }
            }
        });
        return out.slice(0, 20);
    }""")

    print(f"\nאלמנטים עם ₪ ({len(results)}):")
    for r in results:
        tid = f" data-testid='{r['testid']}'" if r['testid'] else ""
        print(f"  <{r['tag']} class='{r['cls']}'{tid}>")
        print(f"    {r['txt']}\n")

    browser.close()
