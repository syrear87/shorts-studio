#!/usr/bin/env python3
"""?m=1 주소 사이트맵 — 블로거 자동 사이트맵 대신 구글에 줄 두 번째 사이트맵 (2026-10-08).

왜: 서치콘솔 '발견됨 - 색인 안 됨' 196편이 전부 데스크톱 주소다. 블로거 자동 사이트맵
  (sitemap.xml)이 데스크톱 주소만 담는데, 구글 모바일 크롤러에게 데스크톱 주소는 302로
  ?m=1에 넘어가는 '리디렉션 페이지'다. 9/10 데스크톱 주소로 요청한 5편은 전부 리디렉션
  오류, 9/28 ?m=1 주소로 요청한 1편은 1분 만에 색인됐고 구글이 고른 정본도 ?m=1이었다.
  블로거 사이트맵은 수정할 수 없으니 ?m=1 주소만 담은 사이트맵을 따로 만든다.

어디에: 블로거는 파일을 못 올린다 → 블로그 이미지에 쓰는 Cloudflare R2 공개 버킷에 둔다.
  구글은 다른 호스트의 사이트맵도 **그 블로그의 robots.txt에 Sitemap: 줄로 적혀 있으면**
  인정한다(교차 사이트 제출). 블로거 설정 → 맞춤 robots.txt에 한 줄 추가돼 있다.

갱신: 러너가 슬롯마다 돌린다(새 글이 생기면 반영). 내용이 같으면 업로드하지 않는다.
사용: .venv/bin/python3 pipeline/sitemap_m.py [--dry]
"""
import hashlib
import os
import sys
from xml.sax.saxutils import escape

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
KEY = "sitemap-m.xml"
STAMP = os.path.join(ROOT, "logs", ".sitemap_m.sha")


def build():
    from upload_blogger import _service, resolve_blog_id
    svc, bid = _service(), resolve_blog_id()
    posts, tok = [], None
    while True:
        kw = {"blogId": bid, "status": "LIVE", "fetchBodies": False, "maxResults": 100,
              "fields": "nextPageToken,items(url,updated)"}
        if tok:
            kw["pageToken"] = tok
        d = svc.posts().list(**kw).execute()
        posts += d.get("items", [])
        tok = d.get("nextPageToken")
        if not tok:
            break
    rows = []
    for p in posts:
        u = p["url"].replace("http://", "https://")
        if "?m=" not in u:
            u += "?m=1"
        rows.append("<url><loc>%s</loc><lastmod>%s</lastmod></url>" % (escape(u), p["updated"][:10]))
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n%s\n</urlset>\n'
           % "\n".join(rows))
    return xml, len(rows)


def main():
    dry = "--dry" in sys.argv or os.environ.get("DRY_RUN") in ("1", "true")
    xml, n = build()
    sha = hashlib.sha1(xml.encode()).hexdigest()
    try:
        old = open(STAMP).read().strip()
    except Exception:
        old = ""
    from blog_media import _kv, _client
    kv = _kv()
    url = kv["R2_PUBLIC_URL"].rstrip("/") + "/" + KEY
    if sha == old:
        print("[sitemap_m] 변경 없음 (%d개) — %s" % (n, url))
        return
    if dry:
        print("[sitemap_m][dry] %d개 주소, 업로드 생략 — %s" % (n, url))
        return
    tmp = os.path.join(ROOT, "logs", KEY)
    open(tmp, "w", encoding="utf-8").write(xml)
    _client(kv).upload_file(tmp, kv["R2_BUCKET"], KEY,
                            ExtraArgs={"ContentType": "application/xml", "CacheControl": "max-age=3600"})
    open(STAMP, "w").write(sha)
    print("[sitemap_m] 업로드 %d개 → %s" % (n, url))


if __name__ == "__main__":
    main()
