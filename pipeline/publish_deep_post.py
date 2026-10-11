#!/usr/bin/env python3
"""깊은 블로그 글 게시 — 게이트를 통과한 글만 공개한다 (2026-10-12 신설).

왜: 애드센스 "가치가 별로 없는 콘텐츠" 반려 + 서치콘솔 "크롤링됨 - 색인 안 됨". 카드 원고를
  AI로 1,500자로 늘린 같은 골격의 글이 하루 5편씩 쌓인 결과다. 디렉터(10/12): "주 2~3편만
  쓰고 깊은 글로". 이 도구가 그 '깊이'를 기계로 지킨다 — 세션이 '충분하다'고 자기설득하는
  걸 막는 건 문구가 아니라 게이트였다(생활정보 게이트와 같은 교훈).

입력: content/blog-deep-YYYY-MM-DD-<slug>.json
  {"title", "html", "topic", "sources": [{"name","url"}...], "labels": [...] (선택)}
게이트(하나라도 걸리면 공개하지 않는다):
  ① 본문 3,000자 이상(태그 제외)  ② 비교표 <table> 1개 이상  ③ 출처 4개 이상(URL 있는 것)
  ④ 이미지 2장 이상  ⑤ <h2> 4개 이상  ⑥ 공개 글과 제목 중복 아님  ⑦ 결론·체크리스트·FAQ 중 2개 이상
  ⑧ 기계 티 문구 금지("결론부터 말씀드리면", "정리해 보겠습니다" 등)
통과하면: blog_polish(라벨·alt) → 관련 글 링크 → 공개 → logs/deep_posts.jsonl 기록 →
  ?m=1 사이트맵 갱신 → 텔레그램 알림.
사용: .venv/bin/python3 pipeline/publish_deep_post.py content/blog-deep-….json [--check]
"""
import json
import os
import re
import subprocess
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
LOG = os.path.join(ROOT, "logs", "deep_posts.jsonl")
MIN_CHARS = 3000
MIN_SOURCES = 4
MIN_IMAGES = 2
MIN_H2 = 4
MACHINE = ("결론부터 말씀드리면", "정리해 보겠습니다", "알아보겠습니다", "살펴보겠습니다",
           "도움이 되셨길", "도움이 되었기를", "이상으로", "오늘은 ~에 대해")


def check(d):
    html = d.get("html") or ""
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()
    probs = []
    if len(text) < MIN_CHARS:
        probs.append("본문 %d자 < %d" % (len(text), MIN_CHARS))
    if "<table" not in html:
        probs.append("비교표(<table>) 없음")
    srcs = [s for s in (d.get("sources") or []) if str(s.get("url", "")).startswith("http")]
    if len(srcs) < MIN_SOURCES:
        probs.append("출처 %d개 < %d" % (len(srcs), MIN_SOURCES))
    if html.count("<img") < MIN_IMAGES:
        probs.append("이미지 %d장 < %d" % (html.count("<img"), MIN_IMAGES))
    if len(re.findall(r"<h2", html)) < MIN_H2:
        probs.append("소제목(h2) %d개 < %d" % (len(re.findall(r"<h2", html)), MIN_H2))
    parts = sum(1 for k in (("결론", "한 줄 요약", "요약"), ("체크리스트", "확인할 것", "고를 때"),
                            ("FAQ", "자주 묻는", "Q."))
                if any(w in text for w in k))
    if parts < 2:
        probs.append("결론·체크리스트·FAQ 중 %d개뿐(2개 이상)" % parts)
    hits = [m for m in MACHINE if m in text]
    if hits:
        probs.append("기계 티 문구: %s" % ", ".join(hits))
    title = (d.get("title") or "").strip()
    if not (10 <= len(title) <= 70):
        probs.append("제목 %d자 (10~70)" % len(title))
    try:
        from blog_dedup import is_dup
        from blog_related import live_posts
        dup, hit, _w = is_dup(title, [p.get("title") or "" for p in live_posts()])
        if dup:
            probs.append("공개 글과 중복: %s" % (hit or "")[:40])
    except Exception as e:
        print("[deep] 중복 검사 건너뜀(무해): %s" % str(e)[:80], flush=True)
    return probs, len(text), len(srcs)


def main():
    if len(sys.argv) < 2:
        sys.exit("사용: publish_deep_post.py content/blog-deep-….json [--check]")
    path = sys.argv[1]
    d = json.load(open(path, encoding="utf-8"))
    probs, n, ns = check(d)
    if probs:
        print("기각: " + " / ".join(probs))
        sys.exit(1)
    print("게이트 통과: %d자, 출처 %d개" % (n, ns), flush=True)
    if "--check" in sys.argv:
        return
    from blog_polish import polish
    from blog_related import append as related
    html, labels = polish(d["html"], d["title"], tags=d.get("labels") or ())
    src_html = "<h2>출처</h2><ul>%s</ul>" % "".join(
        '<li><a href="%s" rel="nofollow noopener" target="_blank">%s</a></li>'
        % (s["url"], re.sub(r"[<>]", "", s.get("name") or s["url"])) for s in d["sources"])
    if "<h2>출처" not in html:
        html += "\n" + src_html
    html = related(html, d["title"], labels)
    from upload_blogger import publish
    res = publish(d["title"], html, labels=d.get("labels") or labels, draft=False)
    url = (res or {}).get("url") or ""
    rec = {"date": datetime.now().strftime("%Y-%m-%d %H:%M"), "title": d["title"], "url": url,
           "topic": d.get("topic"), "chars": n, "sources": ns, "file": os.path.basename(path)}
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print("공개: %s\n      %s" % (d["title"], url), flush=True)
    if os.environ.get("DRY_RUN") not in ("1", "true"):
        subprocess.run([sys.executable, os.path.join(ROOT, "pipeline", "sitemap_m.py")], timeout=120)
        try:
            subprocess.run(["bash", os.path.join(ROOT, "bin", "tg-send.sh"),
                            "📝 블로그 깊은 글 공개 (%d자·출처 %d)\n%s\n%s" % (n, ns, d["title"], url)],
                           timeout=30)
        except Exception:
            pass


if __name__ == "__main__":
    main()
