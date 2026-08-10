#!/usr/bin/env python3
# NASA 공개 아카이브 배경 소스 (2026-08-11 디렉터 승인 — "우주·천문 소재는 스톡으로 안 되니 공공 자료를 붙이자")
#
# 라이선스: NASA 콘텐츠는 미 저작권법 17 U.S.C. §105에 따라 퍼블릭 도메인(CC0)이며 상업적 사용도 가능하다.
#   다만 아래 세 가지는 반드시 지킨다 —
#   ① NASA 인시그니아·로고타입·식별표지는 퍼블릭 도메인이 아니다 → 로고가 보이는 클립 사용 금지
#   ② 식별 가능한 인물(우주비행사 등)이 나오면 상업적 사용에 별도 동의가 필요하다 → 인물 등장 클립 사용 금지
#   ③ NASA를 후원사처럼 보이게 하면 안 되고, 출처는 표기한다 → 설명란에 "영상: NASA" 표기
#   → ①②는 기계로 판별할 수 없으므로 **반드시 미리보기를 눈으로 확인하고 고른다**(pick 모드).
#
# 사용:
#   조사:  .venv/bin/python3 pipeline/fetch_nasa.py "meteor shower night sky"   → 후보 목록 + 썸네일 저장
#   대본:  content json의 scene["bg"] 를 "nasa:<nasa_id>" 로 지정 (make_short.py가 자동 다운로드)
import json
import os
import re
import sys
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "assets", "bg_cache")
PREVIEW = os.path.join(ROOT, "out", "bg_candidates")
API = "https://images-api.nasa.gov"
UA = {"User-Agent": "Mozilla/5.0 (shorts-studio)"}

# 배경으로 쓰기 부적합한 유형 — 제목/설명에 걸리면 후보에서 제외 (①② 리스크 1차 차단)
BAD = re.compile(r"astronaut|crew|interview|briefing|press|conference|administrator|"
                 r"portrait|award|ceremony|logo|insignia|meatball|patch|"
                 # 제작 시리즈물 — 화면에 NASA 로고·자막이 박혀 있어 배경으로 쓸 수 없다 (2026-08-11 실측)
                 r"what's up|whats up|skywatching tips|nasa explorers|this week at nasa|"
                 r"science casts|사이언스캐스트|"
                 r"우주비행사|기자회견", re.I)


def _get(url, timeout=60):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout)


def search(query, n=8):
    """NASA 영상 검색 → [{nasa_id, title, date, thumb, desc}]"""
    q = urllib.parse.urlencode({"q": query, "media_type": "video", "page_size": n * 2})
    d = json.load(_get("%s/search?%s" % (API, q)))
    out = []
    for it in d.get("collection", {}).get("items", []):
        dat = it["data"][0]
        title, desc = dat.get("title", ""), (dat.get("description") or "")[:200]
        if BAD.search(title) or BAD.search(desc):
            continue          # 인물·로고 위험 후보 제외
        thumb = next((l["href"] for l in it.get("links", []) if l.get("render") == "image"), None)
        out.append({"nasa_id": dat["nasa_id"], "title": title,
                    "date": (dat.get("date_created") or "")[:10],
                    "center": dat.get("center", ""), "thumb": thumb, "desc": desc})
        if len(out) >= n:
            break
    return out


def asset_mp4(nasa_id, prefer=("~medium", "~mobile", "~large")):
    """nasa_id → 적당한 해상도의 mp4 URL (orig은 수백 MB라 피한다)"""
    a = json.load(_get("%s/asset/%s" % (API, urllib.parse.quote(nasa_id))))
    hrefs = [x["href"] for x in a["collection"]["items"] if x["href"].lower().endswith(".mp4")]
    for tag in prefer:
        for h in hrefs:
            if tag in h:
                return h
    return hrefs[0] if hrefs else None


def fetch(nasa_id):
    """nasa_id → 로컬 mp4 경로 (캐시). 실패 시 None."""
    os.makedirs(CACHE, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", nasa_id)[:80]
    path = os.path.join(CACHE, "nasa_%s.mp4" % safe)
    if os.path.exists(path) and os.path.getsize(path) > 200000:
        return path
    url = asset_mp4(nasa_id)
    if not url:
        print("NASA asset 없음: %s" % nasa_id, flush=True)
        return None
    try:
        tmp = path + ".part"
        with _get(url, timeout=300) as r, open(tmp, "wb") as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
        os.replace(tmp, path)
        print("NASA 배경 받음: %s (%.1fMB)" % (nasa_id, os.path.getsize(path) / 1048576), flush=True)
        return path
    except Exception as e:
        print("NASA 다운로드 실패(%s): %s" % (nasa_id, str(e)[:100]), flush=True)
        return None


def main():
    if len(sys.argv) < 2:
        sys.exit('사용: fetch_nasa.py "검색어" [검색어2 ...]')
    os.makedirs(PREVIEW, exist_ok=True)
    for qi, query in enumerate(sys.argv[1:]):
        print("\n== %s ==" % query)
        for it in search(query):
            name = "nasa%d_%s.jpg" % (qi, re.sub(r"[^A-Za-z0-9]", "_", it["nasa_id"])[:40])
            if it["thumb"]:
                try:
                    with _get(it["thumb"], timeout=60) as r, open(os.path.join(PREVIEW, name), "wb") as f:
                        f.write(r.read())
                except Exception:
                    name = "(썸네일 실패)"
            print("%-46s | %s | %s" % (name, it["date"], it["title"][:52]))
            print("   bg 값: \"nasa:%s\"" % it["nasa_id"])
    print("\n미리보기: %s" % PREVIEW)
    print("⚠️ 반드시 눈으로 확인하라 — NASA 로고가 찍힌 클립과 인물이 나오는 클립은 쓸 수 없다(라이선스 제약).")
    print("   채택 시 meta description 끝에 '영상: NASA' 출처를 넣을 것.")


if __name__ == "__main__":
    main()
