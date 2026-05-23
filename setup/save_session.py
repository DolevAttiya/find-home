"""
הרץ סקריפט זה פעם אחת כדי להתחבר לפייסבוק ידנית ולשמור את ה-session.
אחרי זה הסקרייפר ישתמש ב-session השמור אוטומטית.
"""
from playwright.sync_api import sync_playwright
import time

SESSION_PATH = "fb_session"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    context = browser.new_context(viewport={"width": 1280, "height": 800})
    page = context.new_page()

    page.goto("https://www.facebook.com/", wait_until="domcontentloaded")

    print("התחבר לפייסבוק בדפדפן שנפתח (כולל אימות דו-שלבי אם נדרש).")
    print("אחרי שנכנסת ורואה את הפיד - חזור לכאן ולחץ Enter.")
    input(">> לחץ Enter אחרי ההתחברות: ")

    # שמור session
    context.storage_state(path=f"{SESSION_PATH}.json")
    print(f"Session נשמר ב-{SESSION_PATH}.json - לא תצטרך להתחבר שוב!")
    browser.close()
