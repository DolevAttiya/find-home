import schedule
import time
import yaml
import threading
from scraper import run_scrape


def load_interval() -> int:
    with open("config.yaml", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return config.get("סריקה", {}).get("כל_כמה_שעות", 2)


def job():
    print("מתחיל סריקה אוטומטית...")
    results = run_scrape()
    print(f"הסתיים: {results['new_apartments']} דירות חדשות, {results['groups_scanned']} קבוצות")
    if results["errors"]:
        print("שגיאות:", results["errors"])


def run_scheduler():
    hours = load_interval()
    schedule.every(hours).hours.do(job)
    print(f"סריקה אוטומטית כל {hours} שעות. Ctrl+C לעצירה.")
    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    run_scheduler()
