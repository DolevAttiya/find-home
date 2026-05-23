import sys, io, time, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import yaml
from playwright.sync_api import sync_playwright

MADLAN_PROFILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "madlan_profile")

with open("config.yaml", encoding="utf-8") as f:
    config = yaml.safe_load(f)

location = config.get("חיפוש", {}).get("מיקום", "גבעתיים")
url = f"https://www.madlan.co.il/for-sale/apartment/{location}"

with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(
        user_data_dir=MADLAN_PROFILE,
        headless=False,
        viewport={"width": 1280, "height": 900},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        args=["--disable-blink-features=AutomationControlled"],
    )
    page = context.new_page()
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    time.sleep(5)

    page.screenshot(path="debug_profile.png")
    print(f"HTML: {len(page.content())} תווים")

    # חפש כל אלמנט שמכיל ₪ בטקסט
    results = page.evaluate("""() => {
        const seen = new Set();
        const out = [];
        document.querySelectorAll('*').forEach(el => {
            const t = (el.innerText || '').trim();
            const cls = (el.className && typeof el.className === 'string') ? el.className : '';
            if (t.includes('₪') && t.length < 500 && el.children.length < 15) {
                const key = cls.slice(0,60);
                if (!seen.has(key)) {
                    seen.add(key);
                    out.push({ tag: el.tagName, cls: cls.slice(0,80), txt: t.slice(0,120) });
                }
            }
        });
        return out.slice(0, 20);
    }""")

    print(f"\nאלמנטים עם ₪ ({len(results)}):")
    for r in results:
        print(f"  <{r['tag']} class='{r['cls']}'>\n    {r['txt']}\n")

    context.close()
