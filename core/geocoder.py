import os
import sys
import io
import time
import sqlite3
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError
from core.database import DB_PATH

geolocator = Nominatim(user_agent="fb-apartments-scraper")


KNOWN_CITIES = {"גבעתיים", "רמת גן", "תל אביב", "בני ברק", "פתח תקווה", "רמת השרון", "חולון", "בת ים"}


def geocode_address(address: str, city: str = "") -> tuple[float, float] | None:
    if not address:
        return None

    # אם הכתובת כבר מכילה שם עיר — לא להוסיף עיר נוספת (תסתור)
    address_has_city = any(c in address for c in KNOWN_CITIES)
    effective_city = "" if address_has_city else city

    # ניסיון 1: כתובת מלאה
    query = f"{address}, {effective_city}, ישראל".strip(", ")
    try:
        location = geolocator.geocode(query, timeout=10)
        if location:
            return location.latitude, location.longitude
    except (GeocoderTimedOut, GeocoderServiceError):
        pass

    time.sleep(1.1)

    # ניסיון 2: אם הכתובת מתחילה ב"בשכונת/בעת/בר" — נסה רק שם השכונה + עיר
    import re
    stripped = re.sub(r"^ב(?:שכונת|רחוב|פרויקט|עת|ר)?\s*", "", address).strip()
    if stripped and stripped != address:
        query2 = f"{stripped}, {effective_city}, ישראל".strip(", ")
        try:
            location = geolocator.geocode(query2, timeout=10)
            if location:
                return location.latitude, location.longitude
        except (GeocoderTimedOut, GeocoderServiceError):
            pass

    time.sleep(1.1)

    # ניסיון 3: כתובות ממדלן בפורמט "רחוב[+מספר], שכונה, עיר" - Nominatim
    # נכשל כשיש גם שכונה באמצע (אומת ידנית: "התע"ש 9, הל"ה, גבעתיים" נכשל,
    # "התע"ש 9, גבעתיים" מצליח) - מסירים את המקטע האמצעי ומשווים רק רחוב+עיר
    parts = [p.strip() for p in address.split(",") if p.strip()]
    if len(parts) >= 3:
        query3 = f"{parts[0]}, {parts[-1]}, ישראל"
        try:
            location = geolocator.geocode(query3, timeout=10)
            if location:
                return location.latitude, location.longitude
        except (GeocoderTimedOut, GeocoderServiceError):
            pass
        # אין fallback לעיר — עדיף ללא קואורדינטות מאשר נקודת מרכז עיר שגויה
    return None


def geocode_pending(city: str = "גבעתיים"):
    """ממיר כתובות ל-lat/lon עבור דירות שעדיין אין להן קואורדינטות"""
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT id, address FROM apartments WHERE address IS NOT NULL AND address != '' AND lat IS NULL"
        ).fetchall()

    print(f"ממיר {len(rows)} כתובות...", flush=True)
    updated = 0

    for row_id, address in rows:
        result = geocode_address(address, city)
        if result:
            lat, lon = result
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute("UPDATE apartments SET lat=?, lon=? WHERE id=?", (lat, lon, row_id))
            updated += 1
        time.sleep(1.1)  # Nominatim מגביל 1 בקשה לשנייה

    print(f"עודכנו {updated} מתוך {len(rows)} כתובות", flush=True)
    return updated


if __name__ == "__main__":
    import yaml
    with open("config.yaml", encoding="utf-8") as f:
        _config = yaml.safe_load(f)
    geocode_pending(city=_config.get("חיפוש", {}).get("מיקום", "גבעתיים"))
