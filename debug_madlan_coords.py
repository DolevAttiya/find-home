"""
בדיקת חילוץ קואורדינטות ישירות מדפי Madlan.
מריץ על כמה URLs מה-DB ומדפיס מה שמוצא.
"""
import re, json, sys, io, time, socket
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

URLS = [
    "https://www.madlan.co.il/listings/gx9PnwOOeuD",   # בוטינסקי 71
    "https://www.madlan.co.il/listings/CSCNJizoEYb",   # בוטינסקי 71
    "https://www.madlan.co.il/listings/IOXCYmMgflU",   # ברדיצ'בסקי
    "https://www.madlan.co.il/listings/eDpfEzQ9Mwh",   # ברת חשמל
]

CDP_PORT = 9222

def cdp_alive():
    try:
        with socket.socket() as s:
            return s.connect_ex(("127.0.0.1", CDP_PORT)) == 0
    except: return False

if not cdp_alive():
    print("CDP לא פעיל — הפעל את הדפדפן קודם (start_madlan_browser.py)")
    sys.exit(1)

from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp(f"http://localhost:{CDP_PORT}")
    ctx = browser.contexts[0]
    page = ctx.new_page()

    for url in URLS:
        print(f"\n{'='*60}")
        print(f"URL: {url}")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=25000)
            time.sleep(2)
            html = page.content()

            # 1. חפש lat/lon בכל ה-JSON שמוטמע בדף
            lat, lon = None, None

            # __NEXT_DATA__ או window.__data__ או כל JSON עם lat/lng
            for pattern in [
                r'"lat"\s*:\s*([\d.]+)',
                r'"latitude"\s*:\s*([\d.]+)',
                r'"lat"\s*:\s*"([\d.]+)"',
            ]:
                m = re.search(pattern, html)
                if m:
                    lat = float(m.group(1))
                    print(f"lat נמצא: {lat}  (pattern: {pattern})")
                    break

            for pattern in [
                r'"lng"\s*:\s*([\d.]+)',
                r'"lon"\s*:\s*([\d.]+)',
                r'"longitude"\s*:\s*([\d.]+)',
                r'"lng"\s*:\s*"([\d.]+)"',
            ]:
                m = re.search(pattern, html)
                if m:
                    lon = float(m.group(1))
                    print(f"lon נמצא: {lon}  (pattern: {pattern})")
                    break

            # 2. חפש כתובת אמיתית
            body = page.inner_text("body")
            # Madlan formats: "רחוב X Y, עיר"
            addr_patterns = [
                r'([^\n]{3,40}\s+\d{1,3})\s*,\s*(גבעתיים|רמת גן|תל אביב)',  # רחוב מספר
                r'([א-ת]{2,}\s+\d{1,3})\s*,\s*(גבעתיים|רמת גן|תל אביב)',
            ]
            print("כתובות שנמצאו בטקסט:")
            for pat in addr_patterns:
                matches = re.findall(pat, body)
                for m in matches[:5]:
                    print(f"  >> {m[0]}, {m[1]}")

            # 3. מה h1 מציג?
            try:
                h1 = page.inner_text("h1")
                print(f"h1: {h1[:100]}")
            except: pass

            # 4. חפש JSON embedded עם address
            next_data = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
            if next_data:
                try:
                    data = json.loads(next_data.group(1))
                    # הדפס מפתחות רלוונטיים
                    txt = json.dumps(data, ensure_ascii=False)
                    for kw in ["address", "street", "city", "lat", "lng", "coordinate"]:
                        idx = txt.lower().find(f'"{kw}"')
                        if idx != -1:
                            snippet = txt[max(0,idx-5):idx+80]
                            print(f"  NEXT_DATA [{kw}]: ...{snippet}...")
                except: pass

        except Exception as e:
            print(f"שגיאה: {e}")

        time.sleep(2)

    page.close()
print("\nסיום.")
