"""
מפעיל דפדפן מדלן מתמיד — פתרו CAPTCHA פעם אחת, מזערו את החלון.
הסריקה האוטומטית תתחבר לדפדפן הזה בלי להפעיל חדש.

הרצה: python start_madlan_browser.py
סגירה: Ctrl+C בחלון זה (או סגרו את חלון הדפדפן)
"""
import sys, io, time, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import socket
from playwright.sync_api import sync_playwright

MADLAN_PROFILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "madlan_profile")
GIVATAIM_URL   = "https://www.madlan.co.il/for-sale/%D7%92%D7%91%D7%A2%D7%AA%D7%99%D7%99%D7%9D-%D7%99%D7%A9%D7%A8%D7%90%D7%9C"
CDP_PORT       = 9222


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


if _port_in_use(CDP_PORT):
    print(f"⚠  פורט {CDP_PORT} כבר בשימוש — כנראה הדפדפן כבר פועל.")
    print("   אין צורך להפעיל שוב.")
    sys.exit(0)

# אם Chrome אמיתי קיים — מפעיל אותו ישירות (עוקף fingerprint detection)
from madlan_captcha_solver import PerimeterXSolver
_solver = PerimeterXSolver(profile_dir=MADLAN_PROFILE, cdp_port=CDP_PORT)
if _solver.chrome_path:
    print(f"✓  נמצא Chrome: {_solver.chrome_path}")
    print("   מפעיל Chrome אמיתי (לא Chromium)...")
    _proc = _solver.launch_chrome()
    print(f"✓  Chrome פועל על פורט {CDP_PORT}. מזערו את החלון.")
    print("   לסגירה: Ctrl+C\n")
    try:
        _proc.wait()
    except KeyboardInterrupt:
        _proc.terminate()
    sys.exit(0)
else:
    print("⚠  Chrome לא נמצא — עובר ל-Chromium")

print("=" * 55)
print("  מדלן — דפדפן מתמיד")
print("=" * 55)
print()
print("הוראות:")
print("  1. הדפדפן ייפתח אוטומטית")
print("  2. אם מופיע CAPTCHA — פתרו ידנית")
print("  3. לחצו על 2-3 מודעות כדי לאמת את הסשן")
print("  4. מזערו את חלון הדפדפן — אל תסגרו אותו!")
print("  5. ספרייה זו תתחבר אליו בכל סריקה אוטומטית")
print()
print("לסגירה מוחלטת: Ctrl+C בחלון זה")
print("=" * 55 + "\n")

with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(
        user_data_dir=MADLAN_PROFILE,
        headless=False,
        viewport={"width": 1440, "height": 900},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        args=[
            f"--remote-debugging-port={CDP_PORT}",
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
        ],
        ignore_default_args=["--enable-automation"],
    )

    page = context.new_page()
    page.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        window.chrome = { runtime: {} };
    """)

    try:
        page.goto(GIVATAIM_URL, wait_until="domcontentloaded", timeout=40000)
        html_size = len(page.content())
        if html_size < 50000:
            print(f"⚠  CAPTCHA מוצג ({html_size} תווים) — פתרו ידנית בדפדפן.")
        else:
            print(f"✓  דף נטען ({html_size:,} תווים) — הסשן תקין.")
    except Exception as e:
        print(f"שגיאת טעינה: {e}")

    print(f"\n✓  דפדפן פועל על פורט {CDP_PORT}.")
    print("   מזערו את חלון הדפדפן — הסריקה תתחבר אליו אוטומטית.\n")

    # שמור על הדפדפן פתוח עד שהמשתמש לוחץ Ctrl+C
    try:
        context.wait_for_event("close", timeout=86_400_000)  # 24 שעות
    except KeyboardInterrupt:
        pass
    except Exception:
        pass

    try:
        context.close()
    except Exception:
        pass

print("\nהדפדפן נסגר.")
