#!/usr/bin/env python3
"""공개 블로그 글 중 이미지 없는 글에 현행 게이트로 사진을 소급한다.

2026-09-15: 공개 125편 중 무사진 12편(대부분 8/26~9/3 이미지 게이트 도입 전 글).
기본은 예행연습 — 실제 갱신은 --apply. 판정·삽입 로직은 publish_blog_daily._ensure_images와
동일(원고 되찾기 → pick_images → decorate), 다른 점은 대상이 DRAFT가 아니라 LIVE라는 것뿐.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))


def main():
    apply = "--apply" in sys.argv
    if not apply:
        os.environ.setdefault("DRY_RUN", "1")
    import upload_blogger as ub
    from publish_blog_daily import _ensure_images
    svc = ub._service()
    bid = ub.resolve_blog_id()
    posts, tok = [], None
    while True:
        r = svc.posts().list(blogId=bid, maxResults=100, status="LIVE", fetchBodies=True,
                             pageToken=tok).execute()
        posts += r.get("items", [])
        tok = r.get("nextPageToken")
        if not tok:
            break
    targets = [p for p in posts if not re.search(r"<img\b", p.get("content") or "")]
    print("공개 %d편 · 무사진 %d편 · %s" % (len(posts), len(targets), "APPLY" if apply else "예행연습"))
    ok = 0
    for p in targets:
        print("==", p["published"][:10], (p.get("title") or "")[:50])
        if _ensure_images(svc, bid, p, dry=not apply):
            ok += 1
    print("\n%d/%d 처리" % (ok, len(targets)))


if __name__ == "__main__":
    main()
