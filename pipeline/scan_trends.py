#!/usr/bin/env python3
# 실시간 트렌드 스캐너 (2026-08-12 밤 디렉터 지시 — "너가 나보다 서칭을 더 잘할 건데, 먼저 물어와줘")
# 사람들이 "지금" 관심 있는 것을 여러 소스에서 모아 한 장의 다이제스트로 만든다.
#   ① 구글 트렌드 실시간 급상승 (KR, 공식 RSS)
#   ② 유튜브 인기 급상승 (Data API mostPopular — 채널 OAuth 재사용)
#   ③ 커뮤니티 베스트글 제목 (디시 실베 · 웃대 베오베 — 제목만, 저부하 1회 요청)
# 소스별 실패는 무시하고 되는 것만 출력한다 (아침 브리핑·슬롯 세션이 Read해서 소재 후보로 사용).
# ⚠️ 용도는 '소재 스카우팅'뿐이다 — 본문 인용·재게시 금지, 요청은 소스당 1회.
# 사용: .venv/bin/python3 pipeline/scan_trends.py [--save]   (--save: content/trends_latest.md 갱신)
import json
import os
import re
import sys
import urllib.request
from datetime import datetime
from xml.etree import ElementTree

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}


def _get(url, timeout=20):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()


def google_trends():
    """구글 트렌드 실시간 급상승 (KR) — 공식 RSS."""
    xml = _get("https://trends.google.co.kr/trending/rss?geo=KR")
    root = ElementTree.fromstring(xml)
    out = []
    for item in root.iter("item"):
        title = item.findtext("title") or ""
        traffic = item.findtext("{https://trends.google.co.kr/trending/rss}approx_traffic") or ""
        if title:
            out.append((title.strip(), traffic.strip()))
    return out[:15]


def youtube_trending():
    """유튜브 인기 급상승 (KR) — 업로더와 동일한 OAuth 크리덴셜 재사용."""
    sys.path.insert(0, os.path.join(ROOT, "pipeline"))
    from google_creds import load_creds  # 업로더와 동일 인증 헬퍼
    from googleapiclient.discovery import build
    yt = build("youtube", "v3", credentials=load_creds())
    r = yt.videos().list(part="snippet,statistics", chart="mostPopular",
                         regionCode="KR", maxResults=15).execute()
    out = []
    for v in r.get("items", []):
        sn, st = v["snippet"], v.get("statistics", {})
        out.append((sn["title"], sn.get("channelTitle", ""), int(st.get("viewCount", 0))))
    return out


def _decode(raw):
    for enc in ("utf-8", "cp949"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def _titles(url, pattern, limit=12):
    html = _decode(_get(url))
    seen, out = set(), []
    for m in re.finditer(pattern, html):
        t = re.sub(r"<[^>]+>", "", m.group(1)).strip()
        t = re.sub(r"\s+", " ", t)
        if len(t) >= 6 and t not in seen:
            seen.add(t)
            out.append(t)
        if len(out) >= limit:
            break
    return out


def dcinside_best():
    """디시 실시간 베스트 — 제목만."""
    return _titles("https://gall.dcinside.com/board/lists/?id=dcbest",
                   r'class="gall_tit[^"]*"[^>]*>\s*<a[^>]*>(.*?)</a>')


def todayhumor_best():
    """웃긴대학... 이 아니라 오늘의유머 베오베 — 제목만. (웃대는 구조 변경 잦아 차기 버전)"""
    return _titles("http://www.todayhumor.co.kr/board/list.php?table=bestofbest",
                   r'class="subject"[^>]*>\s*<a[^>]*>(.*?)</a>')


def nate_pann():
    """네이트판 실시간 인기 톡 — 제목만 (2026-08-12 밤 디렉터 요청 '네이트판 실시간 순위')."""
    return _titles("https://pann.nate.com/", r'<a[^>]*href="/talk/\d+"[^>]*>(.*?)</a>')


def naver_ranking_news():
    """네이버 랭킹뉴스(많이 본 뉴스) — 제목만. EUC-KR 주의."""
    return _titles("https://news.naver.com/main/ranking/popularDay.naver",
                   r'class="list_title[^"]*"[^>]*>(.*?)</a>', limit=15)


def main():
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = ["# 실시간 트렌드 다이제스트 — %s" % now,
             "> 소재 스카우팅 전용. 채택 전 3중 게이트(원출처·시점·제작 후) 필수. 커뮤니티발은 사실 검증 없이는 '감정의 온도' 참고로만.", ""]
    sources = [
        ("구글 트렌드 급상승(KR)", google_trends, lambda r: ["- %s (%s)" % (t, tr or "?") for t, tr in r]),
        ("유튜브 인기 급상승(KR)", youtube_trending, lambda r: ["- %s — %s (%s회)" % (t, ch, format(vc, ",")) for t, ch, vc in r]),
        ("네이버 랭킹뉴스(많이 본)", naver_ranking_news, lambda r: ["- %s" % t for t in r]),
        ("네이트판 실시간 톡", nate_pann, lambda r: ["- %s" % t for t in r]),
        ("디시 실시간 베스트", dcinside_best, lambda r: ["- %s" % t for t in r]),
        ("오늘의유머 베오베", todayhumor_best, lambda r: ["- %s" % t for t in r]),
    ]
    for name, fn, fmt in sources:
        lines.append("## %s" % name)
        try:
            rows = fn()
            lines += fmt(rows) if rows else ["(비어 있음)"]
        except Exception as e:
            lines.append("(수집 실패: %s)" % str(e)[:80])
        lines.append("")
    text = "\n".join(lines)
    print(text)
    if "--save" in sys.argv:
        with open(os.path.join(ROOT, "content", "trends_latest.md"), "w", encoding="utf-8") as f:
            f.write(text)
        print("→ content/trends_latest.md 저장")


if __name__ == "__main__":
    main()
