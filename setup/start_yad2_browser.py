"""
מפעיל את ה-Edge האמיתי שלך (הפרופיל הרגיל - עם כל ה-cookies וההיסטוריה שלך)
במצב remote-debugging, כדי שהסריקה האוטומטית תתחבר אליו ותיראה בדיוק כמוך.
זה הסיכוי הכי טוב לעבור את חסימת Radware ביד2 (הרבה יותר טוב מפרופיל נקי).

חשוב: אי אפשר לצרף דיבוג מרוחק ל-Edge שכבר פתוח - צריך לפתוח אותו מחדש
עם הדגל הזה. אם Edge פתוח, הסקריפט יבקש מכם לסגור אותו ידנית (לא סוגר
בשבילכם - כדי לא לאבד לכם טאבים/עבודה בלי אזהרה).

הרצה: python setup/start_yad2_browser.py
"""
import sys, io, os, time, subprocess
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import socket

CDP_PORT = 9223
EDGE_PATHS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]
EDGE_USER_DATA = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Edge", "User Data")


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def _edge_running() -> bool:
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq msedge.exe"],
            capture_output=True, text=True,
        )
        return "msedge.exe" in out.stdout
    except Exception:
        return False


def _find_edge() -> str | None:
    for p in EDGE_PATHS:
        if os.path.exists(p):
            return p
    return None


if _port_in_use(CDP_PORT):
    print(f"⚠  פורט {CDP_PORT} כבר בשימוש — כנראה כבר פועל.")
    sys.exit(0)

edge_path = _find_edge()
if not edge_path:
    print("✗  Edge לא נמצא בנתיבים הרגילים. ערכו את EDGE_PATHS בקובץ הזה.")
    sys.exit(1)

if _edge_running():
    print("⚠  Edge פתוח כרגע.")
    print("   כדי להתחבר לפרופיל האמיתי שלכם (עם ה-cookies וההיסטוריה), Edge")
    print("   צריך להיפתח מחדש עם דיבוג מרוחק - אי אפשר לצרף את זה לחלון פתוח.")
    print()
    print("   1. סגרו את כל חלונות Edge (כולל מה-taskbar)")
    print("   2. הריצו את הסקריפט הזה שוב")
    print("\n   (הטאבים שלכם אמורים לחזור אוטומטית אם 'שחזור טאבים' מופעל ב-Edge)")
    sys.exit(1)

print(f"✓  Edge נמצא: {edge_path}")
print("   מפעיל עם הפרופיל האמיתי שלכם + דיבוג מרוחק...")

subprocess.Popen([
    edge_path,
    f"--remote-debugging-port={CDP_PORT}",
    f"--user-data-dir={EDGE_USER_DATA}",
    "--profile-directory=Default",
])

time.sleep(4)
if _port_in_use(CDP_PORT):
    print(f"✓  Edge פועל על פורט {CDP_PORT} עם הפרופיל האמיתי שלכם.")
    print("   אפשר להמשיך להשתמש בו כרגיל - הסריקה תפתח טאב חדש ברקע כשתריצו סריקה.")
    print("   השאירו את Edge פתוח (אפשר למזער).")
else:
    print("✗  לא הצליח לפתוח את פורט הדיבוג — נסו שוב.")
