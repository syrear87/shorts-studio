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


# 검색 의도 — 블로그로 오는 사람은 **사기 전에 알아보러** 온다 (2026-09-06 신설).
# 공개 86편 중 구매 의도형이 29%뿐이었고 총조회는 53이었다. 루머·컨셉 글은
# 검색 수요 자체가 없다 — "아직 안 나온 물건"을 검색하는 사람은 거의 없다.
# ⚠️ 이 판정은 **보류**지 삭제가 아니다. 카드·영상으로는 그대로 나간다.
INTENT_BUY = ("구매가능",)
INTENT_WORDS = (
    # 비교형
    "vs", "VS", "비교", "차이", "뭐가 다른", "어떤 걸", "어느 게", "골라", "고를 때",
    "추천", "보다 나은", "장단점",
    # 가이드형
    "방법", "하는 법", "설정", "쓰는 법", "확인할 것", "주의할 점", "가이드",
    "총정리", "체크리스트", "따라하기",   # '활용'·'정리'·'대신'은 너무 넓어 뺐다(2026-09-06 감사)
    # 문제해결형
    "안 될 때", "안될 때", "오류", "해결", "고장", "느려", "발열", "배터리 광탈",
    "먹통", "복구", "왜 안", "문제 해결", "안 되는 이유",
    # 구매 타이밍형 — "지금 사도 되나"는 구매 직전 검색이다
    "타이밍", "언제 사", "지금 사", "살 때", "사기 전", "기다려", "출시일", "가격 인하",
    # 직구 판단형 (2026-09-06) — CARD_PROMPT §1-c가 붙인 '직구 총액·국내 대안·출시 전망'.
    # "○○ 직구"는 실제로 검색량이 있는 질의다. 종전에는 미출시 제품이 「신제품·루머」로
    # 분류돼 블로그에서 보류됐는데, 저 셋이 붙으면 구매 가이드다.
    "직구", "관세", "국내 출시", "국내 미출시", "국내 정식", "대체품", "국내 대안", "환산",
)
# 검색 수요가 없는 축 — 보류한다
INTENT_HOLD = ("루머", "유출", "컨셉", "시제품", "프로토타입", "특허", "떡밥", "밈")


def intent(meta):
    """(통과여부, 사유). 블로그 글로 만들 만한 **검색 의도**가 있는가."""
    text = _text_of(meta)
    tags = card_tags(meta)
    if tags & set(INTENT_BUY):
        return True, "구매 가능"
    # 해시태그·CTA 줄은 판정에서 뺀다 — "#IT꿀팁"·"매일 카드로 올라옵니다"가 의도 신호로 읽혔다
    import re as _re
    text = _re.sub(r"#\S+", " ", text)
    text = "\n".join(l for l in text.splitlines()
                     if not any(k in l for k in ("팔로우", "올라옵니다", "올립니다")))
    hold = [w for w in INTENT_HOLD if w in text]
    hit = [w for w in INTENT_WORDS if w in text]
    # hold(루머·컨셉)가 있으면 **강한 신호 2개 이상**을 요구한다 — 종전엔 hit 하나로 통과해
    # 컨셉·프로토타입 글이 블로그로 갔다(9/5 DualPlay Mini 컨셉).
    if hold:
        if len(hit) >= 2:
            return True, "보류 축이지만 강한 의도 신호 %d개(%s)" % (len(hit), ", ".join(hit[:3]))
        return False, "보류(삭제 아님) — 검색 수요가 낮은 축: %s" % ", ".join(hold[:3])
    if hit:
        return True, "비교·가이드·문제해결형(%s)" % ", ".join(hit[:3])
    # 세션이 blog_teaser를 썼으면 통과 (2026-09-13). 이 게이트는 9/6에 '검색 수요 없는 글'을
    # 거르려고 만들었는데, 지금 블로그 유입은 검색이 아니라 스레드 링크다(색인 0편, 링크로
    # 하루 50~60명). 그런데 게이트가 topic 키워드만 보고 걷어차서, 세션이 "충전식으로 바꿀 때
    # 확인할 것은 블로그에 정리해뒀습니다"라고 teaser까지 써놓은 에어더스터 편이 글도 링크도
    # 없이 나갔다 — 독자에게 없는 글을 약속한 셈이다. teaser는 세션이 '쓸 깊이가 있다'고
    # 판단한 신호다. 루머·컨셉·밈(hold)은 위에서 이미 막혔으니 여기 오는 건 hold가 아니다.
    teaser = str((meta or {}).get("blog_teaser") or "").strip()
    if len(teaser) >= 10:
        return True, "세션이 blog_teaser로 깊이를 약속함"
    return False, "보류(삭제 아님) — 구매 가능도 아니고 비교·가이드·문제해결형도 아니고 teaser도 없다"


def judge(meta, is_card=None):
    """(통과여부, 사유). 통과한 것만 블로그 글로 만든다."""
    text = _text_of(meta)
    if not text.strip():
        return False, "판정할 텍스트가 없다"

    # 제외 축은 **소재**(topic)로 판정한다 (2026-09-13). 본문 전체를 훑으면 스쳐가는 낱말에
    # 걸린다 — Sonos 카드의 "앰프 9개 독립 탑재"가 독립운동용 '독립'에, 블루투스 송신기의
    # "추석에 부모님 TV에 달아드리면"이 명절 특집용 '추석'에 걸려 블로그 글이 안 만들어졌다.
    # 소재가 재난·정치·역사면 topic에 그 낱말이 있다. 본문에만 있으면 언급이지 소재가 아니다.
    subject = str((meta or {}).get("topic") or (meta or {}).get("title") or "")
    if not subject.strip():
        subject = text            # topic이 없는 원고(영상 등)는 종전대로 전체를 본다
    elif (meta or {}).get("cards") and "—" in subject:
        # 카드 topic은 「제품 — 훅 [태그]」 꼴이라 소재는 앞머리다. 훅에 든 낱말은 맥락이지
        # 소재가 아니다 (2026-09-15 실사고: 점프 스타터 "명절 긴급출동 1위"의 '명절',
        # 전동 에어펌프 "사망률 12배"의 '사망'에 걸려 [구매가능]+teaser 카드 2장이 링크 없이
        # 나갔다 — 9/13 "topic만 본다" 수정으로도 못 막은 오탐). 영상 topic은 훅 자체가
        # 소재라 종전대로 전체를 본다.
        subject = subject.split("—", 1)[0]
    blocked = [w for w in BLOCK_WORDS if w in subject]
    if blocked:
        return False, "제외 축 소재: %s" % ", ".join(blocked[:4])

    if is_card is None:
        is_card = bool((meta or {}).get("cards"))

    hits = [w for w in TECH_WORDS if w in text]
    if is_card:
        tags = card_tags(meta)
        tech = bool(tags & CARD_TECH_TAGS) or bool(hits)
        if not tech:
            return False, "카드지만 테크 신호가 없다"
        ok, why = intent(meta)          # 2026-09-06: 검색 의도까지 본다
        if not ok:
            return False, why
        base = ("카드 %s" % "·".join(sorted(tags & CARD_TECH_TAGS))) if (tags & CARD_TECH_TAGS) \
            else ("테크 낱말 %s" % ", ".join(hits[:4]))
        return True, "%s / %s" % (base, why)

    # 영상은 계열이 섞여 있다 — 테크 낱말 2개 이상을 요구한다
    if len(hits) >= 2:
        return True, "테크 낱말 %s" % ", ".join(hits[:4])
    return False, "테크 신호 부족(%d개)" % len(hits)
