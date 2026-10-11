#!/usr/bin/env python3
"""카드의 블로그 글을 **게시 전에** 확보한다 (2026-09-11 디렉터 지시).

왜 순서를 바꿨나:
  스레드 카드는 하루 약 2,000명에게 닿는데(도달 중앙값 371 × 5~6장) 그중 누구도
  블로그가 있다는 걸 몰랐다 — 블로그 조회는 하루 2명이었다. 검색 색인은 0편이라
  유입 경로가 통째로 없었다.
  디렉터: "앞으로 작성할것들은 블로그 먼저 작성하고 그 링크를 스레드 본문 맨 마지막에"

  종전 순서는 [카드 게시] → (나중 슬롯) [블로그 초안] → (하루 3편) [블로그 공개]라
  카드가 나갈 때 링크가 존재하지 않았다. 이제 카드 게시 직전에 글을 공개해 URL을 쥔다.

무엇을 하지 않나:
  - 블로그 게이트를 통과 못 한 소재는 글을 만들지 않는다(링크 없이 게시된다).
  - 같은 소재 글이 이미 있으면 새로 만들지 않고 **그 글을 가리킨다.**
  - 여기서 공개한 편수는 logs/.blog_card_pub_<날짜>에 적어 publish_blog_daily가
    그만큼 하루 쿼터에서 뺀다 — 두 경로가 따로 세면 발행량이 두 배가 된다.
"""
import datetime
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))


def _counter_path(day=None):
    day = day or datetime.date.today().isoformat()
    return os.path.join(ROOT, "logs", ".blog_card_pub_%s" % day)


def published_today():
    """오늘 카드 경로로 공개한 블로그 편수 (publish_blog_daily가 쿼터에서 뺀다)."""
    try:
        return int(open(_counter_path(), encoding="utf-8").read().strip() or 0)
    except Exception:
        return 0


def _bump():
    p = _counter_path()
    n = published_today() + 1
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(str(n))
    except Exception:
        pass
    return n


MAP_F = os.path.join(ROOT, "logs", "blog_map.jsonl")   # {card, url, title} — 카드→글 정본


def _mapped_url(card_name):
    """이 카드로 이미 만든 글의 URL. 제목 대조(dedup)보다 앞선다 (2026-09-13).
    자석 그립톡 카드가 글을 두 번 만들었다 — topic은 한국어, 옛 글 제목은 영어
    (Magnetic Detachable Grip Tok)라 겹치는 낱말이 0개였다. 카드 이름은 언어와 무관하다."""
    try:
        with open(MAP_F, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if r.get("card") == card_name and r.get("url"):
                    return r["url"]
    except Exception:
        pass
    return None


def _remember(card_name, url, title):
    try:
        os.makedirs(os.path.dirname(MAP_F), exist_ok=True)
        with open(MAP_F, "a", encoding="utf-8") as f:
            f.write(json.dumps({"card": card_name, "url": url, "title": title,
                                "at": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")},
                               ensure_ascii=False) + "\n")
    except Exception:
        pass


def _live_posts():
    from upload_blogger import _service, resolve_blog_id
    svc = _service()
    bid = resolve_blog_id()
    out, tok = [], None
    while True:
        kw = {"blogId": bid, "status": "LIVE", "fetchBodies": False, "maxResults": 100}
        if tok:
            kw["pageToken"] = tok
        d = svc.posts().list(**kw).execute()
        out += [((p.get("title") or "").strip(), p.get("url")) for p in d.get("items", [])]
        tok = d.get("nextPageToken")
        if not tok:
            break
    return out


# 카드마다 새 블로그 글을 만들지 않는다 (2026-10-12 디렉터: "주 2~3편만 깊은 글로").
# 애드센스가 "가치가 별로 없는 콘텐츠"로 반려했고, 서치콘솔도 ?m=1로 요청한 글을 크롤한 뒤
# "크롤링됨 - 색인 안 됨"으로 거절했다 — 카드 원고를 1,500자로 늘린 같은 골격의 글이 하루
# 5편씩 쌓인 게 원인이다. 이제 카드는 **이미 있는 글**(같은 소재, 깊은 글 포함)만 가리킨다.
# 새 글은 pipeline/publish_deep_post.py(BLOG_PROMPT 세션)로만 나간다. 기존 글은 그대로 둔다.
NEW_POST_PER_CARD = False


def ensure_article(meta, card_name):
    """(url, 사유). url이 None이면 링크 없이 카드를 게시한다 — 슬롯을 죽이지 않는다."""
    mapped = _mapped_url(card_name)
    if mapped:
        return mapped, "이 카드로 이미 만든 글(blog_map)"
    from blog_gate import judge
    ok, why = judge(meta, is_card=True)
    if not ok:
        return None, "블로그 게이트 보류: %s" % why

    from blog_dedup import is_dup
    live = _live_posts()
    titles = [t for t, _u in live]
    probe = " ".join(str(meta.get(k) or "") for k in ("topic", "caption"))[:300]
    dup, hit, words = is_dup(probe, titles)
    if dup:
        url = next((u for t, u in live if t == hit), None)
        if url:
            return url, "이미 있는 글을 가리킨다 (%s)" % ", ".join(words[:3])
        return None, "중복 판정이나 해당 글 주소를 못 찾음"

    if not NEW_POST_PER_CARD:
        return None, "같은 소재의 기존 글 없음 — 카드별 새 글은 만들지 않는다(2026-10-12)"

    from make_blog import build
    from upload_blogger import publish
    r = build(meta)
    # 발행은 일시 장애(네트워크·Blogger 5xx)로 흔들린다. 두 번 더 친다 — 여기서 자가치유하면
    # 슬롯을 중단하지 않아도 된다 (2026-09-12: 도어락 편이 한 번 실패해 링크 없이 나갔다).
    import time as _t
    res, last = None, None
    for _i in range(3):
        try:
            res = publish(r["title"], r["html"], labels=r.get("labels") or ["IT·테크"], draft=False)
            break
        except Exception as _e:
            last = _e
            if _i < 2:
                _t.sleep(3)
    if res is None:
        raise last            # 세 번 다 실패 — 호출부(make_cards)가 스레드 게시를 막는다
    url = res.get("url")
    if not url:
        raise RuntimeError("공개는 됐으나 주소를 못 받음")   # 정상 ‘링크 없음’이 아니라 오류다
    try:                       # autogen이 같은 카드로 또 만들지 않게
        with open(os.path.join(ROOT, "logs", "blog_generated.txt"), "a", encoding="utf-8") as f:
            f.write(card_name + "\n")
    except Exception:
        pass
    _bump()
    _remember(card_name, url, r["title"])
    return url, "새 글 공개: %s" % r["title"][:40]


MAX_TEXT = 500          # 스레드 본문 상한 (upload_threads.MAX_TEXT와 같다)
BODY_BUDGET = 400       # 세션이 지켜야 할 본문 상한 — 100자를 소개 한 줄 + URL 몫으로 남긴다


def append_link(threads_text, url, teaser=""):
    """링크는 **첫 답글**로 단다 → (본문, 답글 텍스트) (2026-10-12 개정).

    왜: 9/13부터 블로그 링크를 본문 끝에 붙였는데(거의 100%), 9/21 주부터 스레드 24시간
    조회 중앙값이 300 → 100~170으로 떨어졌다. 9/21 이후 본문에 링크 있는 글 중앙 130(n=88),
    링크 없는 글 중앙 703(n=6). 메타는 외부 링크가 든 글을 덜 퍼뜨린다. 본문엔 짧은 안내만
    남기고 링크는 답글로 보낸다 — 본문 도달을 살리고, 관심 있는 사람만 답글에서 누른다.
    소개 문구(blog_teaser)는 답글 첫 줄이 된다. 소재마다 달라야 한다는 규칙은 그대로다.
    """
    body = (threads_text or "").rstrip()
    t = (teaser or "").strip() or "자세한 정보는 블로그에 정리해뒀습니다"
    pointer = "\n\n👇 자세한 정리는 댓글에"
    if len(body + pointer) <= MAX_TEXT:
        body = body + pointer
    return body, t + "\n" + url


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("사용: blog_link.py <cards.json>   (확인용 — 실제 공개까지 한다)")
    p = sys.argv[1]
    m = json.load(open(p, encoding="utf-8"))
    u, why = ensure_article(m, os.path.basename(p))
    print("url :", u or "(없음)")
    print("사유 :", why)
