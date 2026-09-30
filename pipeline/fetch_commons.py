#!/usr/bin/env python3
# 위키미디어 커먼즈 실사 배경 소스 (2026-09-28 디렉터: "내용이랑 영상이랑 상관이 없는데 주목이 되겠나…
#   관계도 없는 미국 농구, 아무 절 같은 곳 영상… 스팸이지 저게")
#
# 왜: Pexels는 '비슷한 분위기'만 준다. 한국 대표팀 농구에 NBA 마이애미 경기장이, 절 벽에서 나온
#   태극기에 이름 모를 절 대문이 깔렸다. 소재의 **실물**이 화면에 있어야 멈춘다.
#   방송 중계 캡처는 쓸 수 없다 — 방송사·대회 주관사 저작물이라 Content ID에 즉시 걸리고
#   경고 3회면 채널이 삭제된다. 대신 커먼즈에는 실물 사진이 자유 라이선스로 있다
#   (국가상징·문화유산·랜드마크·선수·기관 공개 사진).
#
# 라이선스: 퍼블릭 도메인·CC0·CC BY·CC BY-SA만 받는다. BY 계열은 **저작자 표기 의무**가 있어
#   받은 파일의 크레딧을 assets/bg_cache/commons_credits.json에 남기고, upload_youtube가
#   설명란 끝에 "사진: <저작자> / Wikimedia Commons (<라이선스>)"를 붙인다. NC·ND·출처 불명 제외.
# 출처 검증: 업로더가 "직접 전달 받음"처럼 제3자 사진을 올린 파일은 라이선스 세탁 위험이 있어 뺀다
#   (2026-09-28 실측: '2026 아시안게임 현장사진' 8장이 전부 이 표기였다).
#
# 사용:
#   조사:  .venv/bin/python3 pipeline/fetch_commons.py "Taegukgi" "태극기 1900년대"  → 후보 + 썸네일
#   대본:  scene["bg"] = "commons:File:이름.jpg"  (make_short.py가 받아서 켄 번즈로 움직인다)
import json
import os
import re
import sys
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "assets", "bg_cache")
CREDITS = os.path.join(CACHE, "commons_credits.json")
PREVIEW = os.path.join(ROOT, "out", "bg_candidates")
API = "https://commons.wikimedia.org/w/api.php"
UA = {"User-Agent": "shorts-studio/1.0 (https://github.com/syrear87/shorts-studio)"}

OK_LICENSE = re.compile(r"^(public domain|pd|cc0|cc by(-sa)?( [0-9.]+)?|kogl type 1)", re.I)   # 공공누리 1유형 = 출처표시·상업 가능
BAD_LICENSE = re.compile(r"\bnc\b|\bnd\b|non-?commercial|no ?deriv", re.I)
BAD_SOURCE = re.compile(r"직접 전달|전달 받|received|from the internet|unknown", re.I)
MIN_SIDE = 1000     # 세로 1920 화면에 켄 번즈를 걸려면 짧은 변이 이 정도는 돼야 뭉개지지 않는다


def _get(url, timeout=60):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout)


def _strip(md, k):
    return re.sub(r"<[^>]+>", "", (md.get(k) or {}).get("value", "")).strip()


def info(title):
    """파일 1개의 URL·라이선스·저작자. 쓸 수 없으면 (None, 사유)."""
    q = urllib.parse.urlencode({"action": "query", "format": "json", "titles": title,
                                "prop": "imageinfo", "iiprop": "url|extmetadata|size",
                                "iiurlwidth": 2400})
    with _get("%s?%s" % (API, q)) as r:
        pages = json.load(r)["query"]["pages"]
    p = next(iter(pages.values()))
    if "imageinfo" not in p:
        return None, "파일 없음"
    ii = p["imageinfo"][0]
    md = ii.get("extmetadata", {})
    lic, artist, credit = _strip(md, "LicenseShortName"), _strip(md, "Artist"), _strip(md, "Credit")
    if BAD_LICENSE.search(lic) or not OK_LICENSE.search(lic):
        return None, "라이선스 불가(%s)" % lic
    if BAD_SOURCE.search(credit):
        return None, "출처 불명(%s)" % credit[:30]
    # 세로 사진은 세로 화면에 그대로 맞으니 짧은 변 기준을 낮춘다 (2026-09-30: 안세영 861x1579가
    # 1000 기준에 걸려 빠졌다 — 정작 인물 사진은 대부분 세로다)
    _w, _h = ii.get("width", 0), ii.get("height", 0)
    if (_h > _w and (_w < 700 or _h < 1200)) or (_h <= _w and min(_w, _h) < MIN_SIDE):
        return None, "해상도 부족(%sx%s)" % (ii.get("width"), ii.get("height"))
    return {"title": p["title"], "url": ii.get("thumburl") or ii["url"], "license": lic,
            "artist": artist[:60] or "미상", "page": ii.get("descriptionurl", ""),
            "date": _strip(md, "DateTimeOriginal")[:20], "w": ii.get("width"), "h": ii.get("height")}, ""


def search(query, n=8):
    q = urllib.parse.urlencode({"action": "query", "format": "json", "list": "search",
                                "srsearch": query + " filetype:bitmap", "srnamespace": 6,
                                "srlimit": n * 3})
    with _get("%s?%s" % (API, q)) as r:
        hits = json.load(r)["query"]["search"]
    out, skipped = [], []
    for h in hits:
        it, why = info(h["title"])
        if it:
            out.append(it)
        else:
            skipped.append((h["title"], why))
        if len(out) >= n:
            break
    return out, skipped


def _save_credit(it):
    try:
        cr = json.load(open(CREDITS, encoding="utf-8"))
    except Exception:
        cr = {}
    cr[it["title"]] = {"artist": it["artist"], "license": it["license"], "page": it["page"]}
    json.dump(cr, open(CREDITS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def credit_line(title):
    """설명란용 한 줄. 크레딧 기록이 없으면 None."""
    try:
        c = json.load(open(CREDITS, encoding="utf-8")).get(title)
    except Exception:
        c = None
    if not c:
        return None
    return "사진: %s / Wikimedia Commons (%s)" % (c["artist"], c["license"])


def fetch(title):
    """'File:이름.jpg' → 로컬 경로(캐시). 라이선스·출처가 안 맞거나 실패하면 None."""
    os.makedirs(CACHE, exist_ok=True)
    it, why = info(title)
    if not it:
        print("커먼즈 배경 기각(%s): %s" % (title, why), flush=True)
        return None
    ext = os.path.splitext(it["url"].split("?")[0])[1].lower() or ".jpg"
    safe = re.sub(r"[^0-9A-Za-z가-힣_.-]", "_", title.split(":", 1)[-1])[:80]
    path = os.path.join(CACHE, "commons_%s%s" % (os.path.splitext(safe)[0], ext))
    if not (os.path.exists(path) and os.path.getsize(path) > 50000):
        try:
            with _get(it["url"], timeout=180) as r, open(path + ".part", "wb") as f:
                f.write(r.read())
            os.replace(path + ".part", path)
        except Exception as e:
            print("커먼즈 다운로드 실패(%s): %s" % (title, str(e)[:100]), flush=True)
            return None
    _save_credit(it)
    print("커먼즈 배경 받음: %s (%s, %s)" % (title, it["license"], it["artist"][:24]), flush=True)
    return path


def main():
    if len(sys.argv) < 2:
        sys.exit('사용: fetch_commons.py "검색어" [검색어2 ...]')
    os.makedirs(PREVIEW, exist_ok=True)
    for qi, query in enumerate(sys.argv[1:]):
        print("\n== %s ==" % query)
        found, skipped = search(query)
        for i, it in enumerate(found):
            name = "commons%d_%d.jpg" % (qi, i)
            try:
                small = re.sub(r"/\d+px-", "/480px-", it["url"])
                with _get(small, timeout=60) as r, open(os.path.join(PREVIEW, name), "wb") as f:
                    f.write(r.read())
            except Exception:
                name = "(썸네일 실패)"
            print("%-14s | %s | %s | %sx%s | %s" % (name, it["license"], it["artist"][:18],
                                                   it["w"], it["h"], it["title"][5:60]))
            print('   bg 값: "commons:%s"' % it["title"])
        if skipped:
            print("   (제외 %d건: %s)" % (len(skipped), "; ".join("%s—%s" % (t[5:24], w) for t, w in skipped[:4])))
    print("\n미리보기: %s" % PREVIEW)
    print("⚠️ 눈으로 확인하라 — **소재의 실물**인가(같은 대상·같은 장소·같은 사람)? 비슷한 분위기면 쓰지 마라.")


if __name__ == "__main__":
    main()
