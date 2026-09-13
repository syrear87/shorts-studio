#!/usr/bin/env python3
"""링크 없이 나간 스레드 카드에 블로그 글을 만들고 답글로 링크를 단다 (2026-09-13 신설).

왜: 블로그-우선 파이프라인(blog_link)이 자리 잡기까지 여러 이유로 링크 없이 나간 카드가
  생겼다 — 500자 잘림, 게이트 오탐, 도입 전 슬롯. 스레드 글은 72시간이면 수명이 끝나므로
  그 안에 있는 것만 소급한다. 세 번째 손으로 하다가 도구로 굳혔다.

무엇을: 최근 스레드 글 중 (a) 본문에 블로그 링크가 없고 (b) 카드 JSON이 있고
  (c) 지금 게이트를 통과하는 것에 대해 — 글이 없으면 만들어 공개하고(blog_link.ensure_article),
  답글로 「blog_teaser + URL」을 단다. 이미 우리 답글이 달린 글은 건너뛴다.

기본은 예행연습. --apply 로 실제 게시. --hours N 으로 창 조절(기본 72).
"""
import glob
import json
import os
import sys
import time
import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))


def main():
    import upload_threads as t
    import blog_link
    apply = "--apply" in sys.argv
    hours = 72
    for i, a in enumerate(sys.argv):
        if a == "--hours" and i + 1 < len(sys.argv):
            hours = int(sys.argv[i + 1])
    tok = t.token()
    me = t._get("%s/me?fields=id,username&access_token=%s" % (t.API, tok))
    my_id, my_name = me["id"], me.get("username")
    posts = t._get("%s/%s/threads?fields=id,text,timestamp&limit=25&access_token=%s"
                   % (t.API, my_id, tok)).get("data", [])
    now = time.time()
    first = lambda s: (s or "").strip().split("\n")[0]
    cards = {}
    for f in glob.glob(os.path.join(ROOT, "content", "cards-*.json")):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        cards[first(d.get("threads_text") or d.get("caption"))[:24]] = (os.path.basename(f), d)

    plan = []
    for p in posts:
        txt = p.get("text") or ""
        if "daily1pick.blogspot.com" in txt:
            continue
        try:
            dt = datetime.datetime.fromisoformat(p["timestamp"].replace("Z", "+00:00"))
            if (now - dt.timestamp()) / 3600 > hours:
                continue
        except Exception:
            continue
        name, meta = cards.get(first(txt)[:24], (None, None))
        if not meta:
            continue
        # 이미 우리 답글(링크)이 달렸으면 건너뛴다
        try:
            reps = t._get("%s/%s/replies?fields=username,text&access_token=%s"
                          % (t.API, p["id"], tok)).get("data", [])
            if any(r.get("username") == my_name and "daily1pick" in (r.get("text") or "") for r in reps):
                continue
        except Exception:
            pass
        teaser = (meta.get("blog_teaser") or "").strip()
        plan.append((name, p["id"], meta, teaser, first(txt)[:40]))

    print("대상 %d건 (최근 %d시간, 링크 없음, 답글 없음)\n" % (len(plan), hours))
    done = 0
    for name, pid, meta, teaser, hook in plan:
        print("■ %s — %s" % (name[6:-5], hook))
        if not apply:
            from blog_gate import judge
            ok, why = judge(meta, is_card=True)
            print("   게이트: %s (%s)" % ("통과" if ok else "보류", why[:50]))
            print("   teaser: %s" % (teaser[:60] or "(없음 → 기본 문구)"))
            continue
        try:
            url, why = blog_link.ensure_article(meta, name)
        except Exception as e:
            print("   ❌ 글 확보 실패: %s" % str(e)[:80]); continue
        if not url:
            print("   ⏸ 글 없음 — %s" % why[:60]); continue
        text = (teaser or "자세한 정보는 블로그에 정리해뒀습니다") + "\n" + url
        try:
            rid = t.reply_text(pid, text)
            done += 1
            print("   ✅ %s\n      답글 %s" % (url, rid))
        except Exception as e:
            print("   ❌ 답글 실패: %s" % str(e)[:80])
        time.sleep(8)
    if not apply:
        print("\n(예행연습 — --apply 로 실제 게시)")
    else:
        print("\n완료 %d/%d" % (done, len(plan)))


if __name__ == "__main__":
    main()
