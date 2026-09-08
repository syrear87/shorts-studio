#!/usr/bin/env python3
"""카드 이미지 다운로드 헬퍼 — URL 목록을 받아 assets/cards/에 저장한다."""
import json, os, sys, requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST = os.path.join(ROOT, "assets", "cards")

def main():
    if len(sys.argv) < 2:
        print("usage: dl_card_img.py '{\"name.jpg\": \"url\", ...}'")
        sys.exit(1)
    urls = json.loads(sys.argv[1])
    os.makedirs(DEST, exist_ok=True)
    for name, url in urls.items():
        path = os.path.join(DEST, name)
        try:
            r = requests.get(url, timeout=30, headers={"User-Agent": "shorts-studio/1.0"})
            r.raise_for_status()
            with open(path, "wb") as f:
                f.write(r.content)
            print(f"OK  {name}: {len(r.content):,} bytes")
        except Exception as e:
            print(f"ERR {name}: {e}")

if __name__ == "__main__":
    main()
