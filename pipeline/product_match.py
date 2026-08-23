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
        "단품", "패키지", "호환", "한국", "한국어", "일본어", "영어", "버전", "추천", "인기"}
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
