#!/usr/bin/env python3
"""이미 발행된 블로그 글을 후처리한다 — 기본은 dry-run이다.

왜 필요한가 (2026-09-06 공개 86편 전수):
  발행 코드를 고쳐도 **이미 나간 글은 그대로 남는다.** 검색엔진이 보는 건 지금
  올라가 있는 HTML이다. 마크다운 7편·alt 공백 75편·라벨 없음 54편을 그냥 두면
  초기 글 전체가 기계 티를 달고 색인 신호를 버린 채로 남는다.

기본은 dry-run이다. `--apply` 없이는 아무것도 고치지 않는다 —
이건 공개된 글을 실제로 수정하는 일이라 눈으로 먼저 본다.
"""
import argparse
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))


def fetch_all(svc, bid):
    posts, tok = [], None
    while True:
        r = svc.posts().list(blogId=bid, maxResults=100, pageToken=tok,
                             fetchBodies=True).execute()
        posts += r.get("items", [])
        tok = r.get("nextPageToken")
        if not tok:
            return posts


def plan(p):
    """이 글에 무엇을 바꿀 것인가. (새 html, 새 labels, 변경 목록)"""
    from blog_polish import demote_markdown, fill_alt, pick_labels
    html = p.get("content", "") or ""
    title = p.get("title", "") or ""
    changes = []

    h = demote_markdown(html)
    if h != html:
        n = len(re.findall(r"\*\*[^*\n]{1,120}\*\*", html))
        changes.append("마크다운 %d곳 → <strong>" % n)

    h2 = fill_alt(h, title)
    if h2 != h:
        changes.append("빈 alt %d곳 채움" % html.count('alt=""'))

    cur = list(p.get("labels") or [])
    txt = re.sub(r"<[^>]+>", " ", html)[:1200]
    new_labels = pick_labels(title, txt)
    if sorted(cur) != sorted(new_labels):
        changes.append("라벨 %s → %s" % (cur or ["(없음)"], new_labels))
    else:
        new_labels = None

    return (h2 if h2 != html else None), new_labels, changes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="실제로 수정한다 (없으면 dry-run)")
    ap.add_argument("--limit", type=int, default=0, help="이만큼만 처리")
    ap.add_argument("--only", default="", help="제목에 이 문자열이 든 글만")
    a = ap.parse_args()

    from upload_blogger import _service, resolve_blog_id, update
    svc = _service()
    bid = resolve_blog_id()
    posts = fetch_all(svc, bid)
    if a.only:
        posts = [p for p in posts if a.only in p.get("title", "")]

    todo = []
    for p in posts:
        html, labels, changes = plan(p)
        if changes:
            todo.append((p, html, labels, changes))
    if a.limit:
        todo = todo[:a.limit]

    print("공개 %d편 중 손볼 글 %d편%s"
          % (len(posts), len(todo), "" if a.apply else "  [dry-run — 아무것도 안 고친다]"))
    print()
    for p, html, labels, changes in todo:
        print("■ %s" % p["title"][:66])
        for c in changes:
            print("   · " + c)
    if not a.apply:
        print()
        print("실제로 고치려면 --apply 를 붙여라. 공개된 글을 수정하는 일이다.")
        return 0

    done = fail = 0
    for p, html, labels, changes in todo:
        try:
            update(p["id"], html=html, labels=labels, blog_id=bid)
            done += 1
            print("✓ %s" % p["title"][:60], flush=True)
            time.sleep(0.4)          # API 예의
        except Exception as e:
            fail += 1
            print("✗ %s — %s" % (p["title"][:44], str(e)[:90]), flush=True)
    print()
    print("수정 %d편 · 실패 %d편" % (done, fail))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
