"""Download public domain images for 유관순 편 backgrounds from Wikimedia Commons."""

import urllib.request
import urllib.parse
import json
import os
import time

OUT_DIR = "assets/bg_yoo"
os.makedirs(OUT_DIR, exist_ok=True)

API = "https://commons.wikimedia.org/w/api.php"
HEADERS = {"User-Agent": "ShortsStudioBot/1.0 (shorts-studio; educational)"}

def api_get(params: dict) -> dict:
    url = f"{API}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())

def get_image_url(title: str) -> str:
    data = api_get({
        "action": "query",
        "titles": title,
        "prop": "imageinfo",
        "iiprop": "url|size",
        "format": "json",
    })
    pages = data["query"]["pages"]
    for page in pages.values():
        if "imageinfo" in page:
            return page["imageinfo"][0]["url"]
    return ""

def download_file(url: str, out_path: str):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=60) as resp:
        with open(out_path, "wb") as f:
            f.write(resp.read())
    return os.path.getsize(out_path)

# Files to download (found from search)
files = [
    ("File:Ryu Gwan-sun.jpg", "s_portrait.jpg"),
    ("File:유관순 일제감시대상인물카드.jpg", "s_mugshot.jpg"),
    ("File:Seodaemun Prison, April 2023.jpg", "s_exterior.jpg"),
    ("File:Inside View ofThe Old Seodaemun Prison, April 2023.jpg", "s_cell.jpg"),
    ("File:March 1st movement.jpg", "s_march.jpg"),
    ("File:Overview of the Old Seodaemun Prison (구서대문형무소).jpg", "s_overview.jpg"),
]

ok = 0
for title, out_name in files:
    time.sleep(2)  # rate limit
    try:
        url = get_image_url(title)
        if not url:
            print(f"NOT FOUND: {title}")
            continue
        time.sleep(1)
        out_path = os.path.join(OUT_DIR, out_name)
        size = download_file(url, out_path)
        print(f"OK: {title} → {out_path} ({size:,} bytes)")
        ok += 1
    except Exception as e:
        print(f"ERROR: {title} — {e}")

print(f"\nDone: {ok}/{len(files)}")
