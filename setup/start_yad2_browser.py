"""
מפעיל Edge עם פרופיל ייעודי ונפרד (לא הפרופיל האישי שלכם!) במצב
remote-debugging, כדי שהסריקה האוטומטית תתחבר אליו ותיראה כמו דפדפן Edge
אמיתי - זה עוזר לעבור את חסימת Radware ביד2 טוב יותר מדפדפן Playwright גנרי.

למה פרופיל נפרד ולא הפרופיל האמיתי שלכם: גרסאות עדכניות של Edge/Chrome
(נבדק על Edge 150) חוסמות לגמרי פתיחת remote-debugging כש-user-data-dir
הוא הפרופיל ברירת-המחדל האמיתי שלכם - זו הגנת אבטחה של הדפדפן עצמו, לא
משהו שאפשר לעקוף מהצד שלנו. עם user-data-dir נפרד וייעודי (בתיקייה הזו,
לא בתיקיית ה-Edge הרגילה שלכם) Edge כן מרשה remote-debugging.

המשמעות: בפעם הראשונה שמריצים, החלון שנפתח יהיה "נקי" (בלי ה-cookies שלכם).
פשוט גלשו בו ל-yad2.co.il פעם אחת ועברו את בדיקת "Verifying your browser"
(ואם יש לכם חשבון - התחברו) - זה פרופיל קבוע (persistent), אז זה יישמר
לכל הריצות הבאות של הסריקה האוטומטית, בלי לגעת בדפדפן הרגיל שלכם בכלל.

מאחר שזה פרופיל נפרד לגמרי, אין צורך לסגור את חלונות ה-Edge הרגילים שלכם -
הם יכולים להישאר פתוחים, Edge תומך בכמה user-data-dir נפרדים במקביל.

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
EDGE_USER_DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "edge_yad2_profile")


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


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

first_run = not os.path.exists(EDGE_USER_DATA)

print(f"✓  Edge נמצא: {edge_path}")
print(f"   מפעיל עם פרופיל ייעודי ({EDGE_USER_DATA}) + דיבוג מרוחק...")

subprocess.Popen([
    edge_path,
    f"--remote-debugging-port={CDP_PORT}",
    f"--user-data-dir={EDGE_USER_DATA}",
])

time.sleep(4)
if _port_in_use(CDP_PORT):
    print(f"✓  Edge פועל על פורט {CDP_PORT} עם פרופיל ייעודי לסריקה.")
    if first_run:
        print("   זו הפעלה ראשונה - גלשו בחלון שנפתח ל-yad2.co.il ועברו את בדיקת")
        print("   'Verifying your browser' פעם אחת. זה יישמר אוטומטית לריצות הבאות.")
    print("   השאירו את החלון הזה פתוח (אפשר למזער) - הסריקה תפתח בו טאב חדש ברקע.")
else:
    print("✗  לא הצליח לפתוח את פורט הדיבוג — נסו שוב.")
