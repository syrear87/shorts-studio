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


def ensure_article(meta, card_name):
    """(url, 사유). url이 None이면 링크 없이 카드를 게시한다 — 슬롯을 죽이지 않는다."""
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
    return url, "새 글 공개: %s" % r["title"][:40]


def append_link(threads_text, url, teaser=""):
    """스레드 본문 **맨 마지막**에 한 줄 소개 + 링크를 붙인다.

    소개 문구는 카드 JSON의 blog_teaser를 쓴다 — 소재마다 달라야 한다
    (디렉터 2026-09-11: "각각 다르게 알맞게"). 같은 문구가 반복되면 링크 스팸으로 읽힌다.
    """
    t = (teaser or "").strip() or "자세한 정보는 블로그에 정리해뒀습니다"
    return (threads_text or "").rstrip() + "\n\n" + t + "\n" + url


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("사용: blog_link.py <cards.json>   (확인용 — 실제 공개까지 한다)")
    p = sys.argv[1]
    m = json.load(open(p, encoding="utf-8"))
    u, why = ensure_article(m, os.path.basename(p))
    print("url :", u or "(없음)")
    print("사유 :", why)
