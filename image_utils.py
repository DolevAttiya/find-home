"""
Utility for downloading apartment images to local disk.
"""
import os
import re
import requests
from pathlib import Path

IMG_DIR = Path("apartment_images")
IMG_DIR.mkdir(exist_ok=True)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def download_images(post_id: str, urls: list, referer: str = "") -> list:
    """
    Downloads up to 15 images for a listing.
    Returns list of local relative paths.
    Skips files that already exist.
    """
    if not urls:
        return []

    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", str(post_id))[:40]
    folder = IMG_DIR / safe_id
    folder.mkdir(exist_ok=True)

    headers = {"User-Agent": UA}
    if referer:
        headers["Referer"] = referer

    local_paths = []
    for i, url in enumerate(urls[:15]):
        try:
            clean_url = url.split("?")[0]
            ext = clean_url.rsplit(".", 1)[-1].lower()
            if ext not in ("jpg", "jpeg", "png", "webp", "gif"):
                ext = "jpg"
            path = folder / f"{i:02d}.{ext}"

            if not path.exists():
                r = requests.get(url, headers=headers, timeout=15)
                if r.status_code == 200:
                    path.write_bytes(r.content)

            if path.exists():
                local_paths.append(str(path))
        except Exception:
            pass

    return local_paths
