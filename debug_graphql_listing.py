"""
מריץ GraphQL query ישירות מתוך הדפדפן (same-origin) לקבלת פרטי מודעה בודדת.
כך אפשר לעקוף את ה-CAPTCHA שמופעל על בקשות ישירות מ-Python.
"""
import sys, io, time, json, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from playwright.sync_api import sync_playwright

MADLAN_PROFILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "madlan_profile")
LIST_URL = "https://www.madlan.co.il/for-sale/%D7%92%D7%91%D7%A2%D7%AA%D7%99%D7%99%D7%9D-%D7%99%D7%A9%D7%A8%D7%90%D7%9C?dealType=secondHand"

# ID מהמודעה שהמשתמש שלח + ID אחד שאנחנו מכירים מה-DB
BULLETIN_IDS = ["cZmUZETiIiN", "dj7qyUGkZKV"]

with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(
        user_data_dir=MADLAN_PROFILE, headless=False,
        viewport={"width": 1440, "height": 900},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        ignore_default_args=["--enable-automation"],
    )
    page = context.new_page()
    page.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});window.chrome={runtime:{}};")

    # טען את דף הרשימה כדי לקבל cookies + CSRF token
    page.goto(LIST_URL, wait_until="domcontentloaded", timeout=40000)
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        pass
    time.sleep(2)

    for bul_id in BULLETIN_IDS:
        print(f"\n{'='*60}")
        print(f"מנסה לאחזר: {bul_id}")

        # שלח GraphQL query ישירות מתוך הדפדפן
        result = page.evaluate(f"""async () => {{
            const query = `
                query getBulletin($id: ID!) {{
                    bulletin(id: $id) {{
                        id
                        address
                        beds
                        baths
                        area
                        floor
                        price
                        amenities
                        parking
                        elevator
                        balcony
                        mamad
                        airConditioner
                        solarBoiler
                        accessibility
                        storage
                        pool
                        garden
                        generalCondition
                        buildingClass
                        buildingYear
                    }}
                }}
            `;
            try {{
                const resp = await fetch('/api', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{
                        query,
                        variables: {{ id: '{bul_id}' }}
                    }})
                }});
                const data = await resp.json();
                return JSON.stringify(data);
            }} catch(e) {{
                return 'ERROR: ' + e.message;
            }}
        }}""")

        print(result[:2000] if result else "null")

    context.close()
