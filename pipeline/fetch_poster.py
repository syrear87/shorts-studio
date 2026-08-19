#!/usr/bin/env python3
"""공식 포스터/홍보 이미지 다운로드 (file: 배경용)"""
import requests, os, sys

dest = sys.argv[1] if len(sys.argv) > 1 else "assets/bg_doom"
os.makedirs(dest, exist_ok=True)

urls = {
    "poster.jpg": "https://lumiere-a.akamaihd.net/v1/images/p_movies_avengersdoomsday_d23update_poster_v1_2b797e84.jpeg",
    "banner.jpg": "https://lumiere-a.akamaihd.net/v1/images/pp_avengersdoomsday_marvel_banner_mobile_4484fc60.jpeg",
}

for name, url in urls.items():
    path = os.path.join(dest, name)
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        with open(path, "wb") as f:
            f.write(r.content)
        print(f"OK  {name}: {len(r.content):,} bytes")
    except Exception as e:
        print(f"ERR {name}: {e}")
