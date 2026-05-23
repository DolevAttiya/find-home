import sys, io, time, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from playwright.sync_api import sync_playwright
from madlan_scraper import parse_price, parse_rooms, parse_size

import yaml
with open("config.yaml", encoding="utf-8") as f:
    config = yaml.safe_load(f)

MADLAN_PROFILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "madlan_profile")
url = config["חיפוש"]["madlan_url"]

with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(
        user_data_dir=MADLAN_PROFILE, headless=False,
        viewport={"width": 1280, "height": 900},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
        args=["--disable-blink-features=AutomationControlled"],
    )
    page = context.new_page()
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    time.sleep(5)
    for _ in range(3):
        page.keyboard.press("End")
        time.sleep(2)

    cards = page.query_selector_all("[class*='universal-card-body-wrapper']")
    print(f"{len(cards)} כרטיסיות\n")
    for i, card in enumerate(cards[:10]):
        text = card.inner_text().strip()
        price = parse_price(text)
        rooms = parse_rooms(text)
        size = parse_size(text)
        print(f"כרטיסייה {i+1}: מחיר={price} | חדרים={rooms} | גודל={size}")
        print(f"  טקסט: {repr(text[:120])}\n")

    context.close()
