#!/usr/bin/env python3
# 소재 스카우트 (2026-08-17 신설 — 디렉터: "제미나이가 서칭은 잘한다니깐 그걸 좀 써도 되니깐,
#   니가 잘하는거 넷파워를 쓰라고").
#
# Gemini + Google Search grounding으로 **지금 이 시각 한국에서 벌어지는 것**을 훑고,
# '별똥별 공식'을 만족하는 소재만 후보로 올린다.
#
# 왜 필요한가 (실측): 시한성 있는 편 304,847 / 160,398 / 75,151 회 vs
#   없는 편 203 / 164 / 152 회 — **약 1,500배 차이.** 소재가 전부다.
#
# ⚠️ Gemini 응답은 **출발점일 뿐**이다. 사실·수치·날짜는 반드시 원출처로 다시 잡아라
#   (2026-08-16 밥그릇 편 삭제 사고: 블로그성 매체를 근거로 썼다가 게시 후 삭제).
#
# 사용: .venv/bin/python3 pipeline/scout.py [추가지시]
import json
import os
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL = "gemini-2.5-flash"
URL = "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent?key=%s"


def _key():
    for line in open(os.path.join(ROOT, "keys.env"), encoding="utf-8"):
        line = line.strip()
        if line.startswith("GEMINI_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"')
    raise RuntimeError("keys.env에 GEMINI_API_KEY가 없다")


PROMPT = """## ⏱ 지금은 %s (한국시간)입니다. 이 시각이 절대 기준입니다.

당신은 한국의 지식 숏폼 채널 '1일 1지식'의 소재 스카우트입니다.
구글 검색으로 **지금 이 시각 사람들이 실제로 반응하고 있는 것**을 찾아주세요.

## 🎯 찾을 것 — 뉴스가 아니라 '현상'입니다 (2026-08-18 디렉터 지시)
우리 채널에서 실제로 터진 것들이 기준입니다: **유성우(오늘 밤 나가보세요), 거제 폭우(지금 겪는 중),
태극기(광복절), 산사태 경고(비 그친 뒤 위험)**. 전부 ①지금 벌어지고 있고 ②전 국민이 함께 겪거나 볼 수 있고
③감정(설렘·자부심·걱정)이 붙는 **현상**이었습니다. 기자가 쓴 '뉴스'가 아니라요.

1. **하늘·우주·자연현상** — 유성우, 개기일식·월식, 슈퍼문, 행성 접근, 오로라, 노을 특이현상,
   태풍·폭우·폭염·첫추위 같은 체감 기상. 오늘 밤~이번 주에 볼 수 있는 것 최우선.
2. **지금 도는 밈·챌린지·유행** — SNS에서 다들 따라 하는 것, 갑자기 역주행하는 노래·영상,
   다들 쓰기 시작한 말. (단, 출처가 커뮤니티 한 곳뿐인 가십은 제외)
3. **전 국민 공통 체험** — 개학, 연휴, 명절 준비, 계절 전환(첫 열대야 해제, 모기 소멸),
   대형 개봉작·공개작으로 다들 보고 있는 것.
4. **기념일·계기** — 오늘·이번 주가 무슨 날인지 (역사 기념일, 절기, N주년).

## 🚫 찾지 말 것
- **사건·사고 뉴스** (살인·사기·학대·재판·수사) — 우리는 뉴스 채널이 아닙니다
- 정치 (정치인 이름·정당이 나오는 것 전부)
- 커뮤니티 한 곳에서만 도는 이야기
- 특정 연령·성별만 아는 것

## 🚨 시점 규칙 — 어기면 결과물 전체가 무효입니다
- **당신의 학습 데이터에 있는 과거 정보를 절대 쓰지 마세요.** 반드시 지금 구글 검색을 실행해서 나온 것만 쓰세요.
- 각 후보에 **정보 시각**(발생·관측 가능 시각)을 반드시 적으세요. 모르면 그 후보는 버리세요.
- 하늘 현상은 **오늘 밤 한국에서 실제로 보이는지**(날씨·달빛·방향)까지 검색으로 확인하세요.
- 계절·날씨 정보는 오늘 자 실측으로 확인하세요.

## 🚫 과장 금지
- "쏟아진다·역대급" 같은 강도 표현 대신 실제 수치를 찾아 쓰세요 (예: 유성우 ZHR 시간당 몇 개).
- 수치를 못 찾으면 '검증 필요'에 "규모 수치 미확인"이라고 명시하세요.

## 💓 감정 한 줄 (필수)
각 후보에 "이걸 본 사람이 느끼는 감정: ___" — 설렘·자부심·걱정·공감·그리움 중 하나가 또렷해야 합니다.
"흥미"는 감정이 아닙니다.

## 좋은 소재의 조건 (실측 검증 공식 — 5개 중 3개 이상)
1. 오늘/오늘 밤이어야 하는가  2. 누구나 할 수 있는가  3. 같이 할 사람이 떠오르는가
4. 놓치면 아쉬운가  5. 연령을 가리지 않는가
(실측: 충족한 편 30만·16만·7.5만 / 못 채운 편 200회)

## 출력 형식 (다른 말 없이 이것만)
서로 다른 분야에서 후보 5개:

### 후보 N
- 소재:
- 감정: (한 단어 + 이유 반 줄)
- 정보 시각: (예: 오늘 밤 22시~ 관측 가능 / 모르면 제외)
- 훅 첫 줄: (완결 문장 — 조건절·명사구로 끝내지 말 것)
- 왜 오늘인가:
- 공식 충족: (1~5 중 몇 개)
- 근거 출처: (기관·매체명과 URL. 블로그 금지)
- 현재 조건 확인: (오늘 날씨·요일과 대조한 결과)
- 검증 필요: (반드시 채울 것 — '없음' 금지)
%s"""


def scout(extra=""):
    key = _key()
    now = time.strftime("%Y년 %m월 %d일 %H시 %M분")
    body = {
        "contents": [{"parts": [{"text": PROMPT % (now, ("\n## 추가 지시\n" + extra) if extra else "")}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {"temperature": 0.9},
    }
    req = urllib.request.Request(URL % (MODEL, key),
                                 data=json.dumps(body).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=180) as r:
        d = json.load(r)
    parts = d["candidates"][0]["content"]["parts"]
    return "".join(p.get("text", "") for p in parts)


if __name__ == "__main__":
    print(scout(" ".join(sys.argv[1:])))
