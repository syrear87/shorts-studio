#!/usr/bin/env python3
"""블로그 소재 판정 — 테크만 통과시킨다 (2026-08-27 디렉터 지시로 신설).

디렉터 지시: "테크 소재만 전부다 하고 그외 소재는 하지말고. 블로그는 테크위주로 간다"

왜 테크만인가:
  - 블로그의 목적은 **구매 의도가 있는 검색 유입**이다. '폰 쿨러 효과'를 검색하는
    사람은 살까 말까 고민 중이지만, '네팔 홍수'를 검색하는 사람은 아무것도 사지 않는다.
  - 확보한 쿠팡 링크 15개가 전부 테크 기기다. 재난·시사 소재에는 걸 상품이 아예 없다.
  - 재난·인명·판결 소재는 팩트 리스크가 가장 큰 축인데, 블로그 글은 검색에 영구히 남아
    SNS 글보다 회수가 어렵다. 애초에 대상에서 뺀다.
  - 주제가 한 갈래로 모여야 검색엔진이 이 블로그를 테크 주제로 인식한다.

fail-CLOSED: 애매하면 **제외**한다. 디렉터가 "그외 소재는 하지말고"라고 못박았고,
  잘못 올리는 손해가 못 올리는 손해보다 크다 (culture_gate.py와 같은 원칙).
"""
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 카드 topic의 분류 태그 — 카드 라인은 애초에 '테크 카드'라 대부분 통과한다
CARD_TECH_TAGS = {"구매가능", "신제품", "루머", "펀딩", "AI놀이", "공유형",
                  "타이밍경고형", "한계붕괴형"}

# 제품·부품·소프트웨어. 하나라도 없으면 테크로 보지 않는다
TECH_WORDS = [
    # 기기·브랜드
    "아이폰", "갤럭시", "애플", "삼성전자", "맥북", "맥미니", "맥 미니", "아이패드",
    "에어팟", "갤럭시워치", "픽셀", "스위치2", "닌텐도", "플레이스테이션", "엑스박스",
    "노트북", "태블릿", "스마트폰", "스마트워치", "이어폰", "헤드폰", "스피커",
    "모니터", "키보드", "마우스", "공유기", "로봇청소기", "드론", "카메라", "렌즈",
    # 부품·규격
    "USB", "HDMI", "SD카드", "microSD", "DRAM", "SSD", "HDD", "메모리", "배터리",
    "충전기", "충전", "케이블", "무선충전", "Qi2", "칩셋", "프로세서", "GPU", "CPU",
    "디스플레이", "OLED", "해상도", "주사율", "방수", "쿨러", "발열", "펠티어",
    # 소프트웨어·AI
    "챗GPT", "ChatGPT", "OpenAI", "GPT", "AI", "인공지능", "안드로이드", "iOS",
    "macOS", "윈도우", "앱", "업데이트", "운영체제", "클라우드", "구글",
]

# 이 축의 소재는 테크 낱말이 섞여 있어도 블로그에 올리지 않는다
BLOCK_WORDS = [
    # 재난·기상
    "폭염", "태풍", "홍수", "지진", "산사태", "한파", "호우", "가뭄", "기후변화",
    "이중열돔", "열돔", "처서", "빙하호", "실종", "사망", "부상", "대피", "이재민",
    # 사건·사회·정치
    "판결", "무죄", "유죄", "기소", "구속", "수사", "경찰", "검찰", "재판",
    "청탁금지법", "수능", "입시", "사교육", "국회", "대통령", "선거", "시위",
    # 경제·금융 (제품 구매와 무관)
    "기준금리", "금통위", "한국은행", "대출이자", "물가", "환율", "주가", "증시",
    "주주환원", "부동산", "전세",
    # 역사·전통·정체성
    "독립", "광복", "일제", "조선", "신라", "백제", "고구려", "명절", "추석",
    "설날", "전통", "유래", "행정명령",
]


def _text_of(meta):
    """판정에 쓸 텍스트 — 제목·본문·태그를 한 덩어리로."""
    if not isinstance(meta, dict):
        return ""
    parts = [str(meta.get(k) or "") for k in
             ("topic", "title", "caption", "description", "threads_text")]
    tags = meta.get("tags")
    if isinstance(tags, (list, tuple)):
        parts.extend(str(t) for t in tags)
    return "\n".join(parts)


def card_tags(meta):
    """카드 topic의 대괄호 태그들."""
    raw = str((meta or {}).get("topic") or "")
    out = set()
    for chunk in re.findall(r"\[([^\]]+)\]", raw):
        for t in re.split(r"[·,/]", chunk):
            t = t.strip()
            if t:
                out.add(t)
    return out


def judge(meta, is_card=None):
    """(통과여부, 사유). 통과한 것만 블로그 글로 만든다."""
    text = _text_of(meta)
    if not text.strip():
        return False, "판정할 텍스트가 없다"

    blocked = [w for w in BLOCK_WORDS if w in text]
    if blocked:
        return False, "제외 축 소재: %s" % ", ".join(blocked[:4])

    if is_card is None:
        is_card = bool((meta or {}).get("cards"))

    hits = [w for w in TECH_WORDS if w in text]
    if is_card:
        tags = card_tags(meta)
        if tags & CARD_TECH_TAGS:
            return True, "카드 %s" % "·".join(sorted(tags & CARD_TECH_TAGS))
        if hits:
            return True, "테크 낱말 %s" % ", ".join(hits[:4])
        return False, "카드지만 테크 신호가 없다"

    # 영상은 계열이 섞여 있다 — 테크 낱말 2개 이상을 요구한다
    if len(hits) >= 2:
        return True, "테크 낱말 %s" % ", ".join(hits[:4])
    return False, "테크 신호 부족(%d개)" % len(hits)
