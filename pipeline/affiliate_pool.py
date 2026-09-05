#!/usr/bin/env python3
"""쿠팡 링크 풀 — 확보해 둔 제휴 링크 **전체**에서 이 편에 맞는 상품을 고른다.
(2026-08-27 실사고로 신설)

사고: affiliate_for()가 state의 `last_product`(가장 최근 회신 1건)만 후보로 삼았다.
  `hub_items`에 15개가 쌓여 있는데 그중 1개만 쓰이니, 오늘 소재가 '폰 쿨러'여도
  last_product가 '제습제'면 매칭이 실패해 링크가 통째로 빠졌다.
  실측(2026-08-27): 최근 스레드 15개 글 중 **본문에 링크가 있는 글 0개** / 11일 클릭 12회.

왜 재사용이 유일한 수단인가: 쿠팡 파트너스 Open API는 **누적 판매 15만원 이상의
  '최종승인' 파트너**에게만 발급된다(우리 실적 0건). 파트너스 웹·쿠팡 도메인은
  브라우저 도구가 차단한다. 즉 **새 링크는 디렉터만 만들 수 있다.** 자동화가 할 수 있는
  전부는 이미 확보한 링크를 소재에 맞게 재사용하는 것이다.

채점은 product_match 단일 정본만 쓴다 — 자체 채점 사본이 오매칭을 낸 전례가 있다
  (2026-08-24 '앤커 충전기'가 관절 건강 편에 3점 매칭).

stdlib + product_match 전용 — 순환 import 방지 (disclosure.py 선례).
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_F = os.path.join(ROOT, "logs", "affiliate_state.json")

MIN_SCORE = 3          # 3점 미만은 무관 — 무관한 편에 상품을 붙이면 광고 계정이 된다
MAX_AGE_DAYS = 120     # 너무 오래된 링크는 품절 위험이 있어 후보에서 뺀다


def _state():
    try:
        with open(STATE_F, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def pool(state=None):
    """후보 상품 목록 [{name, url, ep, date}, ...] — 최신이 앞. url 기준 중복 제거."""
    st = state if state is not None else _state()
    items, seen = [], set()
    raw = list(st.get("hub_items") or [])
    # hub_items는 최신이 앞(no 내림차순)이지만 보장되지 않으니 no로 정렬한다
    raw.sort(key=lambda it: (it or {}).get("no") or 0, reverse=True)
    last = st.get("last_product") or {}
    if last.get("name") and last.get("url"):
        raw.insert(0, last)
    for it in raw:
        name, url = (it or {}).get("name"), (it or {}).get("url")
        if not (name and url) or url in seen:
            continue
        seen.add(url)
        items.append({"name": name, "url": url,
                      "ep": (it or {}).get("ep"), "date": (it or {}).get("date")})
    return items


def best(caption, min_score=MIN_SCORE, state=None):
    """이 캡션과 가장 잘 맞는 상품 (url, name). 없으면 (None, None).

    동점이면 **최신 상품**이 이긴다 — pool()이 최신순이라 첫 최고점을 잡으면 된다.
    """
    from product_match import score, matches
    cap = caption or ""
    if not cap.strip():
        return None, None
    top, top_s = None, 0
    for it in pool(state):
        # 정체 판정을 먼저 통과해야 후보다 — 점수만 보면 '미국'·'미니'·브랜드 단독
        # 일치가 정매칭과 같은 3~5점으로 뚫린다 (2026-08-27 실측, product_match.matches 주석)
        if not matches(it["name"], cap, min_score):
            continue
        s = score(it["name"], cap)
        if s > top_s:
            top, top_s = it, s
    if top:
        return top["url"], top["name"]
    return None, None


def link_block(name, url, disclosure=None):
    """본문 말미·답글 공용 링크 블록. 고지 문구는 링크와 **같은 글**에 있어야 한다(법정 의무)."""
    if disclosure is None:
        from disclosure import DISCLOSURE as disclosure
    return "%s\n%s\n\n%s" % (name, url, disclosure)


def attach(text, name, url, limit=500):
    """본문 말미에 링크 블록을 붙인다. 상한을 넘으면 None을 돌려준다(→ 호출부가 답글로 폴백).

    본문을 잘라서까지 넣지는 않는다 — 내용이 상하면 링크를 넣은 의미가 없다.
    """
    block = link_block(name, url)
    joined = "%s\n\n%s" % ((text or "").rstrip(), block)
    return joined if len(joined) <= limit else None
