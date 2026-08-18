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
    # 2026-08-17: UA 없이 요청하면 디시가 공지만 내려준다(실글 차단). 브라우저 UA를 붙인다.
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
        "Accept-Language": "ko-KR,ko;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


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
    """디시 실시간 베스트 — 제목만.
    2026-08-17 수정: 제목 <a> 안에 아이콘 <em>과 개행이 섞여 있어 기존 정규식이 1건만 잡았다
    (디렉터: "이건 왜 1개만 있지?"). gall_tit 셀 전체를 잡아 태그를 걷어내는 방식으로 바꿨다."""
    html = _decode(_get("https://gall.dcinside.com/board/lists/?id=dcbest"))
    seen, out = set(), []
    for m in re.finditer(r'gall_tit[^>]*>(.*?)</td>', html, re.S):
        t = re.sub(r"<[^>]+>", " ", m.group(1))
        t = re.sub(r"\s+", " ", t).strip()
        t = re.sub(r"\s*\[\d+\]$", "", t)      # 끝의 댓글수 [12] 제거
        if len(t) >= 6 and t not in seen:
            seen.add(t)
            out.append(t)
        if len(out) >= 14:
            break
    return out


def todayhumor_best():
    """웃긴대학... 이 아니라 오늘의유머 베오베 — 제목만. (웃대는 구조 변경 잦아 차기 버전)"""
    return _titles("http://www.todayhumor.co.kr/board/list.php?table=bestofbest",
                   r'class="subject"[^>]*>\s*<a[^>]*>(.*?)</a>')


def naver_ranking_news():
    """네이버 랭킹뉴스(많이 본 뉴스) — 제목만. EUC-KR 주의."""
    return _titles("https://news.naver.com/main/ranking/popularDay.naver",
                   r'class="list_title[^"]*"[^>]*>(.*?)</a>', limit=15)


# ── 필터 (2026-08-17 디렉터 지시) ─────────────────────────────
# "정치 제외 == 특정 정치인 언급 또는 정당 이름 나오는 뉴스/영상 등"
# 중립 원칙(최상위 규약)의 집행 장치다. 걸러진 항목은 아예 눈에 띄지 않게 한다 —
# 목록에 남으면 슬롯 세션이 무심코 집어 든다.
_PARTY = ("민주당", "국민의힘", "국힘", "조국혁신당", "개혁신당", "진보당", "정의당",
          "기본소득당", "사회민주당", "자유통일당", "새미래", "무소속", "여의도")
_POLI = ("대통령", "의원", "장관", "총리", "청와대", "대통령실", "국회", "여당", "야당",
         "최고위원", "당대표", "당 대표", "경선", "총선", "대선", "지방선거", "공천",
         "탄핵", "특검", "국정감사", "대변인", "원내대표", "시장 후보", "도지사", "정치인",
         # 2026-08-17 보강: 첫 적용에서 '국힘·전당대회·지지 이탈'이 그대로 통과했다
         "전당대회", "당권", "지지율", "지지 이탈", "정치권", "여권", "야권", "개헌",
         "정계", "후보 등록", "선거", "국정", "정부 비판", "정권")


def is_political(text):
    t = text or ""
    return any(k in t for k in _PARTY) or any(k in t for k in _POLI)


def has_korean(text):
    """한글이 한 글자라도 있는가 — 외국어 검색어·해외 영상 제목을 걸러낸다."""
    return bool(re.search(r"[가-힣]", text or ""))


def clean(rows, key=lambda x: x, korean_only=False):
    """정치 제외(+선택적으로 한글만) 필터. 원본 자료형(튜플/문자열)을 유지한다."""
    out = []
    for r in rows:
        t = key(r)
        if is_political(t):
            continue
        if korean_only and not has_korean(t):
            continue
        out.append(r)
    return out


def main():
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = ["# 실시간 트렌드 다이제스트 — %s" % now,
             "> 소재 스카우팅 전용. 채택 전 3중 게이트(원출처·시점·제작 후) 필수. 커뮤니티발은 사실 검증 없이는 '감정의 온도' 참고로만.", ""]
    sources = [
        # 전 소스에 정치 필터. 구글·유튜브는 한글만(외국어 검색어·해외 영상 제외) — 2026-08-17 디렉터
        ("구글 트렌드 급상승(KR)", lambda: clean(google_trends(), key=lambda x: x[0], korean_only=True),
         lambda r: ["- %s (%s)" % (t, tr or "?") for t, tr in r]),
        ("유튜브 인기 급상승(KR)", lambda: clean(youtube_trending(), key=lambda x: "%s %s" % (x[0], x[1]), korean_only=True),
         lambda r: ["- %s — %s (%s회)" % (t, ch, format(vc, ",")) for t, ch, vc in r]),
        ("네이버 랭킹뉴스(많이 본)", lambda: clean(naver_ranking_news()), lambda r: ["- %s" % t for t in r]),
        ("디시 실시간 베스트", lambda: clean(dcinside_best()), lambda r: ["- %s" % t for t in r]),
        ("오늘의유머 베오베", lambda: clean(todayhumor_best()), lambda r: ["- %s" % t for t in r]),
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
