import sys, io, time, json, re, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from playwright.sync_api import sync_playwright

MADLAN_PROFILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "madlan_profile")
URL = "https://www.madlan.co.il/for-sale/%D7%92%D7%91%D7%A2%D7%AA%D7%99%D7%99%D7%9D-%D7%99%D7%A9%D7%A8%D7%90%D7%9C"

best = {"size": 0, "body": None, "url": ""}

def on_response(resp):
    if "madlan" not in resp.url: return
    ct = resp.headers.get("content-type", "")
    if "json" not in ct: return
    try:
        body = resp.json()
        s = json.dumps(body, ensure_ascii=False)
        if len(s) > best["size"] and re.search(r'"price"\s*:\s*\d{6}', s):
            best["size"] = len(s)
            best["body"] = body
            best["url"] = resp.url
            print(f"[BEST] {resp.url[:80]} size={len(s)}", flush=True)
    except: pass

with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(
        user_data_dir=MADLAN_PROFILE, headless=False,
        viewport={"width": 1280, "height": 900},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
        args=["--disable-blink-features=AutomationControlled"],
    )
    page = context.new_page()
    page.on("response", on_response)
    page.goto(URL, wait_until="domcontentloaded", timeout=30000)
    time.sleep(7)

    html_size = len(page.content())
    print(f"HTML: {html_size} | {page.url[:80]}")

    if html_size < 50000:
        print("BOT BLOCKED — profile needs refresh. Run save_madlan_session.py")
        context.close()
        exit()

    # scroll to trigger lazy load
    for _ in range(5):
        page.keyboard.press("End")
        time.sleep(1.5)

    time.sleep(3)

    # find all unique css classes on elements containing shekel or address
    classes_with_price = page.evaluate("""() => {
        const classes = new Set();
        document.querySelectorAll('*').forEach(el => {
            const t = el.innerText || '';
            if ((t.includes('₪') || t.includes('חד')) && t.length < 400 && t.length > 15) {
                const c = el.className;
                if (typeof c === 'string') c.split(' ').forEach(cn => cn && classes.add(cn));
            }
        });
        return [...classes].slice(0, 50);
    }""")
    print(f"\nCSS classes on price/room elements: {classes_with_price}")

    # find elements with ₪ and their structure
    results = page.evaluate("""() => {
        const out = [];
        document.querySelectorAll('*').forEach(el => {
            const t = (el.innerText || '');
            if (t.includes('₪') && t.length < 400 && t.length > 20) {
                const c = (el.className || '').toString();
                // only leaf-ish elements
                if (el.children.length < 8) {
                    out.push({ tag: el.tagName, cls: c.slice(0,80), txt: t.slice(0,120) });
                }
            }
        });
        return out.slice(0, 8);
    }""")
    print(f"\nElements with ₪ ({len(results)}):")
    for r in results:
        print(f"  <{r['tag']} class='{r['cls']}'>\n    {repr(r['txt'])}")

    context.close()

# parse best API response
if best["body"]:
    print(f"\n=== BEST API RESPONSE ({best['size']} chars from {best['url']}) ===")
    s = json.dumps(best["body"], ensure_ascii=False)
    # find listing objects
    items = re.findall(r'\{"id":"[^"]+","price":\d+[^}]{0,400}\}', s)
    print(f"Listing-like objects: {len(items)}")
    for it in items[:3]:
        print(f"  {it[:200]}")
