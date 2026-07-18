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

worker.py קורא ל-ensure_running() אוטומטית לפני כל סריקת יד2/יד2-פרויקטים אם
ה-CDP לא פעיל (למשל אחרי ש-Edge סגר את עצמו בעדכון גרסה) - אין יותר צורך
להריץ את הקובץ הזה ידנית בכל פעם, רק בפעם הראשונה אי-פעם (לעבור את הבדיקה).

הרצה ידנית (אופציונלי, בעיקר לפעם הראשונה): python setup/start_yad2_browser.py
"""
import sys, io, os, time, subprocess, socket

CDP_PORT = 9223
EDGE_PATHS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]
EDGE_USER_DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "edge_yad2_profile")
LAUNCH_LOCK = EDGE_USER_DATA + ".launch.lock"


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def _find_edge() -> str | None:
    for p in EDGE_PATHS:
        if os.path.exists(p):
            return p
    return None


def ensure_running(log=print, timeout: int = 15) -> bool:
    """מוודא שה-Edge הייעודי (CDP_PORT) פעיל, ומפעיל אותו אם לא.
    מחזיר True אם הפורט פעיל בסיום הקריאה (כבר היה פעיל, או שהופעל בהצלחה).

    יד2 ויד2-פרויקטים (worker.py) קוראים לזה כמעט בו-זמנית משני תהליכים
    נפרדים - בלי נעילה, שניהם היו מפעילים msedge.exe במקביל על אותו
    user-data-dir/פורט ומתנגשים (אומת ידנית: אחד מהם קיבל "Connection
    closed while reading from the driver" באמצע סריקה). קובץ נעילה אטומי
    (O_EXCL) מבטיח שרק אחד מהם בפועל מפעיל את הדפדפן; השני רק ממתין שהפורט יעלה."""
    if _port_in_use(CDP_PORT):
        return True

    edge_path = _find_edge()
    if not edge_path:
        log("✗  Edge לא נמצא בנתיבים הרגילים. ערכו את EDGE_PATHS ב-setup/start_yad2_browser.py.")
        return False

    # ponytail: אם תהליך נהרג בדיוק בין לקיחת הנעילה לשחרורה (finally למטה),
    # הקובץ נשאר יתום ויחסום הפעלות עתידיות - תיקון: מחיקה ידנית של הקובץ,
    # או שדרוג ל-lock עם timestamp/PID אם זה קורה בפועל.
    got_lock = False
    try:
        os.close(os.open(LAUNCH_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
        got_lock = True
    except FileExistsError:
        pass  # תהליך אחר כבר מפעיל - רק נחכה יחד איתו שהפורט יעלה

    try:
        if got_lock:
            first_run = not os.path.exists(EDGE_USER_DATA)
            log(f"מפעיל דפדפן Edge ייעודי לסריקת יד2 ({edge_path})...")
            subprocess.Popen([
                edge_path,
                f"--remote-debugging-port={CDP_PORT}",
                f"--user-data-dir={EDGE_USER_DATA}",
            ])

        deadline = time.time() + timeout
        while time.time() < deadline:
            if _port_in_use(CDP_PORT):
                if got_lock:
                    log(f"✓  Edge פועל על פורט {CDP_PORT} עם פרופיל ייעודי לסריקה.")
                    if first_run:
                        log("   זו הפעלה ראשונה - גלשו בחלון שנפתח ל-yad2.co.il ועברו את בדיקת "
                            "'Verifying your browser' פעם אחת. זה יישמר אוטומטית לריצות הבאות.")
                return True
            time.sleep(0.5)

        if got_lock:
            log(f"✗  לא הצליח לפתוח את פורט הדיבוג {CDP_PORT} — נסו שוב.")
        return False
    finally:
        if got_lock:
            try:
                os.remove(LAUNCH_LOCK)
            except OSError:
                pass


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    if ensure_running(log=print):
        print("   השאירו את החלון הזה פתוח (אפשר למזער) - הסריקה תפתח בו טאב חדש ברקע.")
    else:
        sys.exit(1)
