#!/usr/bin/env python3
# 상품명 ↔ 캡션 매칭 점수 — 단일 정본 (2026-08-24 실사고로 신설)
#
# 사고: 같은 채점 로직이 affiliate_bot.match_media(2026-08-23 소음 수정판)와
# upload_instagram.affiliate_for(구판 사본)에 이중으로 살았고, 사본 쪽이 영문 2글자
# 조각 소음으로 '앤커 충전기'를 관절 건강 편에 3점 매칭 → 무관한 편 스레드에 쿠팡
# 답글이 달렸다. 채점은 여기 한 곳에서만 고친다.
#
# 규칙 이력:
#  - 숫자·단위 토큰 제외 (2026-08-18: "100"이 "통상임금 100%"와 겹친 오매칭)
#  - 유통 상투어 제외 (2026-08-23: "국내·전용"이 아무 캡션과나 겹침)
#  - 영문↔한글 브랜드 별칭 (2026-08-23: "Nintendo Switch"가 "닌텐도 스위치2"와 0점)
#  - 조각(2글자) 매칭은 한글 토큰만 (2026-08-23: "nt"·"ch" 영문 조각 소음 /
#    2026-08-24: 같은 소음이 사본에서 재발 — 본 모듈로 통일)
import re

STOP = {"국내", "해외", "전용", "세트", "정품", "공식", "출시", "무료", "배송", "할인",
        "단품", "패키지", "호환", "한국", "한국어", "일본어", "영어", "버전", "추천", "인기",
        # 2026-09-03: 「구글 픽셀11 … 미국 직구 카메라 무음」이 Clicks Communicator(키보드폰)
        # 카드에 '직구'·'카메라'로 매칭됐다. 구매 방식과 부품명은 제품 정체가 아니다.
        # 2026-09-03: 「구글 픽셀11 … 미국 직구 …」가 다른 폰 카드에 '직구'로 매칭됐다.
        # 구매 방식·유통 표기는 제품 정체가 아니다. (부품명은 STOP이 아니라 토큰 경계로 막는다)
        "직구", "구매대행", "병행수입", "중고", "리퍼브", "미개봉", "당일발송", "무료배송",
        "모델", "제품", "기기", "인치"}
ALIAS = {"nintendo": "닌텐도", "switch": "스위치", "apple": "애플", "iphone": "아이폰",
         "ipad": "아이패드", "airpods": "에어팟", "galaxy": "갤럭시", "samsung": "삼성",
         "sony": "소니", "playstation": "플레이스테이션", "xbox": "엑스박스",
         "razer": "레이저", "logitech": "로지텍", "dyson": "다이슨", "marshall": "마샬",
         "bose": "보스", "gopro": "고프로", "mario": "마리오", "pokemon": "포켓몬",
         "anker": "앤커", "charger": "충전기"}


def tokens(product_name):
    toks = [t for t in re.split(r"[^0-9A-Za-z가-힣]+", product_name or "")
            if len(t) >= 2 and not re.fullmatch(r"[0-9]+[a-zA-Z]*", t)]
    toks = [t for t in toks if t not in STOP and t.lower() not in STOP]
    toks += [ALIAS[t.lower()] for t in toks if t.lower() in ALIAS]
    return toks


def grams(toks):
    out = set()
    for t in toks:
        if not re.search(r"[가-힣]", t):   # 영문 토큰은 조각 금지 — 전체 일치·별칭으로만
            continue
        for i in range(len(t) - 1):
            g = t[i:i + 2]
            if not re.search(r"[0-9]", g):
                out.add(g)
    return out


def score(product_name, caption):
    """상품명이 이 캡션의 편과 직결되는 정도. 3점 미만이면 무관으로 본다."""
    toks = tokens(product_name)
    cap = caption or ""
    return sum(2 for t in toks if t in cap) + sum(1 for g in grams(toks) if g in cap)


# ── 정체 판정 (2026-08-27 신설) ────────────────────────────────────────────
# 사고: 점수만으로는 정매칭과 오매칭이 구분되지 않았다. 링크 풀 전체를 후보로 돌린
#   실측에서 아래가 **모두 3~5점**으로 같이 통과했다:
#     '쿨러'   ← 폰 쿨러 편 × 펠티어 쿨러      (정매칭 — 겹친 말이 제품의 정체)
#     '미국'   ← 포르말린 배추 편 × 구글 픽셀11 (오매칭 — 겹친 말이 원산지)
#     '미니'   ← 맥 미니 편 × 다이슨 선풍기     (오매칭 — 겹친 말이 크기 수식어)
#     '삼성전자' ← 주주환원 편 × 갤럭시워치      (오매칭 — 겹친 말이 브랜드뿐)
#   즉 임계값을 올려도 해결되지 않는다. **겹친 낱말이 제품의 정체인가**를 따로 물어야 한다.
#
# 규칙: 상품명 낱말 중 캡션에 **통째로** 등장하면서, 브랜드도 곁가지 수식어도 아닌 것이
#   최소 하나 있어야 한다. 조각(2글자 그램) 일치만으로는 절대 통과시키지 않는다.

# 브랜드는 단독으로 제품을 특정하지 못한다 — '삼성전자'가 겹쳤다고 갤럭시워치 편이 아니다
BRANDS = {"삼성", "삼성전자", "엘지", "lg", "엘지전자", "애플", "구글", "소니", "다이슨",
          "닌텐도", "마이크로소프트", "아마존", "샤오미", "화웨이", "레노버", "델", "hp",
          "앤커", "로지텍", "레이저", "보스", "마샬", "고프로", "쿠팡", "네이버", "카카오",
          "apple", "google", "samsung", "sony", "dyson", "nintendo", "anker", "logitech",
          "razer", "bose", "marshall", "gopro", "microsoft", "amazon", "xiaomi", "lenovo",
          # 제품군 이름도 정체가 아니다 — '아이폰'이 겹쳤다고 아이폰 **쿨러** 편이 되지 않는다.
          # 2026-08-27 실측: '9월 9일 이벤트'·'아이폰이 접힌다'·'중고가 감가' 세 편에 모두
          # 펠티어 쿨러가 붙었다. 편의 주제는 아이폰이지 쿨러가 아니라 뜬금없는 광고가 된다.
          "아이폰", "아이패드", "에어팟", "갤럭시", "맥북", "맥미니", "픽셀", "워치",
          "플레이스테이션", "엑스박스", "스위치", "iphone", "ipad", "airpods", "galaxy",
          "macbook", "pixel", "switch", "playstation", "xbox"}

# 곁가지 수식어 — 원산지·크기·등급. 어느 제품에나 붙고 아무 글에나 겹친다
MODIFIERS = {"미국", "중국", "일본", "유럽", "독일", "미니", "소형", "대형", "초소형",
             "대용량", "휴대용", "접이식", "무선", "유선", "고속", "신형", "최신", "특가",
             "프로", "플러스", "울트라", "맥스", "라이트", "에어", "스탠다드", "일반형",
             "블랙", "화이트", "실버", "골드", "정품", "새제품", "리퍼", "벌크",
             # '스마트'가 스마트홈 편과 '스마트 AR 글라스'를 이었다 (2026-08-27)
             "스마트", "휴대", "충전식", "다용도", "저소음", "무소음"}


# 판매자가 검색 노출용으로 상품명 끝에 붙이는 꼬리표 — 제품의 정체가 아니다.
#   2026-09-03 실사고: 「Anker Prime Charger (100W 3 Ports GaN) [PSE PD Windows PC iP…]」가
#   조이콘 드리프트 카드에 매칭돼 스레드 답글로 나갔다(디렉터 삭제). 걸린 낱말은
#   'Windows'(본문 출처 "Windows Central")와 'PC'(호환 목록 "스위치·PC·안드로이드")로,
#   둘 다 상품명 꼬리표에서 온 것이었다.
#   닫는 괄호가 없는 경우도 있다(상품명이 길어 잘림) — 열린 괄호부터 끝까지 걷어낸다.
_TAIL = re.compile(r"[\[(][^\])]*(?:[\])]|$)\s*$")
# 플랫폼·규격·인증 낱말: 어느 테크 글에나 나오므로 정체 근거로 쓰지 않는다
#   ⚠️ 범위를 좁게 유지하라. 처음엔 usb·케이블·충전까지 넣었다가 「808 USB 3.2-C타입
#   고속충전 케이블」의 정체 낱말이 전부 지워져 **정매칭이 죽었다**(2026-09-03 회귀에서 발견).
#   제품의 '종류'를 나타내는 말(케이블·충전기·이어폰…)은 정체다 — 여기 넣지 마라.
#   여기 넣을 것은 **호환성·인증 표기**뿐이다.
PLATFORM = {
    "windows", "pc", "mac", "macos", "ios", "android", "안드로이드",
    "pse", "kc", "ce", "fcc", "ports", "port",
}


def strip_tail(product_name):
    """상품명 끝의 검색 꼬리표를 걷어낸다 — 정체 판정에서 제외하기 위해."""
    prev = None
    out = (product_name or "").strip()
    while out != prev:                     # 꼬리표가 여러 개 붙는 경우가 있다
        prev = out
        out = _TAIL.sub("", out).strip()
    return out or (product_name or "")


# 한국어 조사 — 캡션 토큰이 "케이블을"이어도 "케이블"과 같은 말로 본다
_JOSA = ("은", "는", "이", "가", "을", "를", "의", "에", "에서", "으로", "로",
         "도", "만", "과", "와", "랑", "이나", "나", "까지", "부터", "보다", "처럼", "라")


def _in_caption(token, caption):
    """상품명 낱말이 캡션에 **낱말 단위로** 등장하는가.

    2026-09-03 실사고: 단순 부분 문자열 매칭이라 「닌텐도 64 **카트**리지」가
    「마리오 **카트**」와 겹쳐 Analogue 3D 카드에 Switch 2가 매칭됐다.
    조사만 허용하고 그 밖의 접미는 다른 낱말로 취급한다.
    """
    low = token.lower()
    for ct in tokens(caption):
        c = ct.lower()
        if c == low:
            return True
        if c.startswith(low) and c[len(low):] in _JOSA:
            return True
    return False


# 제품 '종류'를 나타내는 낱말 — 짝이 맞는지 판정하는 축이다.
#   2026-09-03: 정체 낱말만 보면 **곁다리 언급**이 정체로 세어졌다 —
#     · ASUS ZenScreen(모니터) 글의 'USB·케이블' → USB 케이블 상품 매칭
#     · USB-C 충전기 글의 '고속충전·노트북'      → 파워뱅크 상품 매칭
#   둘 다 본문 뒷부분의 부속 설명에서 온 낱말이었다. 상품의 종류가 카드의 **주제**
#   (캡션 앞부분 = 훅·도입)에 등장할 때만 짝으로 인정한다.
CATEGORY = ("케이블", "충전기", "파워뱅크", "보조배터리", "마우스", "키보드", "이어폰",
            "헤드폰", "헤드셋", "모니터", "선풍기", "쿨러", "렌즈", "워치", "시계",
            "마이크", "청소기", "스피커", "글라스", "카메라", "삼각대", "거치대",
            "충전패드", "필름", "케이스", "제습제", "살충제", "앰플", "콘솔", "게임기")
def category_ok(product_name, caption):
    """상품의 제품 종류가 카드의 **주제**에 등장하는가.

    주제 = 캡션 첫 두 줄(훅 + 제품명 줄)로 본다. 앞 220자로 잡았더니
    ZenScreen(모니터) 캡션 4행의 「USB-C 케이블 하나로 둘 다 켜진다」가 걸려
    케이블 상품이 통과했다 — 그건 모니터의 장점 설명이지 주제가 아니다(2026-09-03).
    상품명에서 종류를 못 찾으면 판정하지 않는다(True) — 기존 동작 유지.
    """
    low = (product_name or "").lower()
    cats = [c for c in CATEGORY if c in low]
    if not cats:
        return True
    lines = [l for l in (caption or "").split("\n") if l.strip()][:2]
    head = " ".join(lines)
    return any(_in_caption(c, head) for c in cats)


def identity_hits(product_name, caption):
    """캡션과 통째로 겹치면서 **제품의 정체를 특정하는** 낱말들.

    브랜드(BRANDS)·곁가지(MODIFIERS)·상투어(STOP)는 정체가 아니므로 제외한다.
    2글자 미만과 순수 영문 조각도 제외 — 소음원이었다(2026-08-23·24 오매칭 이력).
    2026-09-03: 상품명 끝의 검색 꼬리표와 플랫폼·규격 낱말도 제외한다(위 _TAIL/PLATFORM 주석).
    """
    cap = caption or ""
    out = []
    for t in tokens(strip_tail(product_name)):
        if t.lower() in PLATFORM:
            continue
        low = t.lower()
        if low in BRANDS or low in MODIFIERS or t in MODIFIERS or low in STOP:
            continue
        if len(t) < 2:
            continue
        if _in_caption(t, cap):
            out.append(t)
    return out


MIN_IDENTITY = 2   # 정체 낱말 **2개 이상**


def matches(product_name, caption, min_score=3):
    """이 상품을 이 편에 붙여도 되는가 — 점수와 정체 판정을 **둘 다** 통과해야 한다.

    정체 낱말을 2개 요구하는 이유: 쿠팡 상품명은 꼬리에 판촉 키워드가 붙는다.
      '구글 픽셀11 … 미국 직구 **카메라** 무음'  → 아이폰 이벤트 편에 '카메라' 하나로 걸렸다
      'Nintendo Switch 2 … 마리오 **카트** 월드' → SD카드 편에 '카트' 하나로 걸렸다
    반면 진짜 직결된 편은 낱말이 겹겹이 맞는다:
      '… 펠티어 발열 쿨러' × 폰 쿨러 편   → ['펠티어', '쿨러']
      '808 USB … 케이블'  × USB-C 편    → ['USB', '케이블']
    한 낱말은 우연이고 두 낱말은 주제다. 못 붙이는 손해보다 잘못 붙이는 손해가 크다 —
    무관한 편에 상품을 붙이면 광고 계정이 되고, 클릭도 어차피 나오지 않는다.
    """
    if score(product_name, caption) < min_score:
        return False
    hits = identity_hits(product_name, caption)
    if len(hits) < MIN_IDENTITY:
        return False
    # 종류 판정 (2026-09-03): 정체 낱말이 본문 뒷부분의 곁다리 언급에서 왔을 수 있다.
    #   · ZenScreen(모니터) × USB 케이블 → 낱말 2개('USB','케이블')뿐이고 종류도 안 맞다 → 기각
    #   · HushJet(선풍기)  × 다이슨 선풍기 → 훅에 '선풍기'란 말은 없지만
    #     낱말이 4개('선풍기','Hushjet','Mini','Cool') 맞물린다 → 통과
    # 낱말이 딱 2개인 아슬아슬한 경우에만 종류 일치를 추가로 요구한다.
    if len(hits) >= MIN_IDENTITY + 1:
        return True
    return category_ok(product_name, caption)
