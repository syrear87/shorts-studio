#!/usr/bin/env python3
# 실시간 트렌드 스캔 — 유튜브 인기 급상승 단일 소스 (2026-08-18 디렉터 확정:
#   "그냥 유튜브 인기만 남기고 다 제거". 구글 트렌드·네이버 랭킹뉴스·디시·오유·네이트판 순차 제거)
# 이유: 나머지 소스가 소재 선택을 오염시켰다(가족사진 사기 실사고 등). 유튜브 인기가
#   조회수라는 **정직한 파도 신호**를 준다. 인스타는 공식 API에 트렌딩 피드가 없다.
# 사용: .venv/bin/python3 pipeline/scan_trends.py [--save]
import os
import re
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── 필터 (2026-08-17 디렉터: "정치 제외 == 특정 정치인 언급 또는 정당 이름") ──
_PARTY = ("민주당", "국민의힘", "국힘", "조국혁신당", "개혁신당", "진보당", "정의당",
          "기본소득당", "사회민주당", "자유통일당", "새미래", "무소속", "여의도")
_POLI = ("대통령", "의원", "장관", "총리", "청와대", "대통령실", "국회", "여당", "야당",
         "최고위원", "당대표", "당 대표", "경선", "총선", "대선", "지방선거", "공천",
         "탄핵", "특검", "국정감사", "대변인", "원내대표", "시장 후보", "도지사", "정치인",
         "전당대회", "당권", "지지율", "지지 이탈", "정치권", "여권", "야권", "개헌",
         "정계", "후보 등록", "선거", "국정", "정부 비판", "정권")


def is_political(text):
    t = text or ""
    return any(k in t for k in _PARTY) or any(k in t for k in _POLI)


def has_korean(text):
    return bool(re.search(r"[가-힣]", text or ""))


def youtube_trending(limit=20):
    """유튜브 인기 급상승 (KR) — 정치 제외, 한글 포함만. (제목, 채널, 조회수) 리스트."""
    sys.path.insert(0, os.path.join(ROOT, "pipeline"))
    from google_creds import load_creds
    from googleapiclient.discovery import build
    yt = build("youtube", "v3", credentials=load_creds())
    r = yt.videos().list(part="snippet,statistics", chart="mostPopular",
                         regionCode="KR", maxResults=limit).execute()
    out = []
    for v in r.get("items", []):
        sn, st = v["snippet"], v.get("statistics", {})
        title, ch = sn["title"], sn.get("channelTitle", "")
        if is_political("%s %s" % (title, ch)) or not has_korean("%s %s" % (title, ch)):
            continue
        out.append((title, ch, int(st.get("viewCount", 0))))
    return out


def main():
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = ["# 유튜브 인기 급상승(KR) — %s" % now,
             "> 파도 신호 전용. 채택 전 3중 게이트(원출처·시점·제작 후) 필수. "
             "같은 소재가 아침·지금 모두 상위면 진짜 파도다.", ""]
    try:
        for t, ch, vc in youtube_trending():
            lines.append("- %s — %s (%s회)" % (t, ch, format(vc, ",")))
    except Exception as e:
        lines.append("(조회 실패: %s)" % str(e)[:120])
    text = "\n".join(lines)
    print(text)
    if "--save" in sys.argv:
        path = os.path.join(ROOT, "logs", "trend_scan_latest.md")
        open(path, "w", encoding="utf-8").write(text + "\n")
        print("\n저장: %s" % path)


if __name__ == "__main__":
    main()
