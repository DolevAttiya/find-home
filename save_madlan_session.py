"""
פותח דפדפן עם פרופיל קבוע למדלן.
פתור את האתגר ידנית, גלוש קצת באתר, ואז סגור את הדפדפן.
הפרופיל נשמר אוטומטית לתיקייה madlan_profile/.
"""
import sys, io, time, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from playwright.sync_api import sync_playwright

MADLAN_PROFILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "madlan_profile")
GIVATAIM_URL = "https://www.madlan.co.il/for-sale/%D7%92%D7%91%D7%A2%D7%AA%D7%99%D7%99%D7%9D-%D7%99%D7%A9%D7%A8%D7%90%D7%9C"

print("=" * 55)
print("  מדלן — שמירת פרופיל")
print("=" * 55)
print(f"URL: {GIVATAIM_URL}")
print()
print("הוראות:")
print("  1. המתן לטעינת הדף")
print("  2. אם מופיע אתגר אבטחה (PerimeterX/CAPTCHA) — פתור ידנית")
print("  3. גלוש קצת: פתח 2-3 מודעות, גלול למטה")
print("  4. חזור לדף הרשימה הראשי")
print("  5. סגור את הדפדפן — הפרופיל נשמר אוטומטית")
print("=" * 55 + "\n")

with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(
        user_data_dir=MADLAN_PROFILE,
        headless=False,
        viewport={"width": 1440, "height": 900},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
        ],
        ignore_default_args=["--enable-automation"],
    )

    page = context.new_page()

    # הסתר סימני אוטומציה
    page.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        window.chrome = { runtime: {} };
    """)

    try:
        page.goto(GIVATAIM_URL, wait_until="domcontentloaded", timeout=40000)
    except Exception as e:
        print(f"שגיאת טעינה (אפשר להמשיך): {e}")

    print("הדפדפן פתוח — פעל לפי ההוראות למעלה, ואז סגור את הדפדפן.")
    print("(ממתין לסגירה — עד 10 דקות)\n")

    # ממתין עד שהמשתמש סוגר את הדפדפן (עד 10 דקות)
    try:
        context.wait_for_event("close", timeout=600_000)
    except Exception:
        pass

    try:
        context.close()
    except Exception:
        pass

print(f"\n✓ פרופיל נשמר ב: {MADLAN_PROFILE}")
print("כעת הרץ: python worker.py madlan")
