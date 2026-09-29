#!/usr/bin/env python3
"""새 글 끝에 「함께 보면 좋은 글」 3개를 붙인다 — 글끼리 잇는 크롤 가능한 링크.

왜 (2026-09-28 서치콘솔 판정): 색인 0의 원인은 기술 문제가 아니라 크롤 우선순위였다.
실제 URL 테스트는 통과("등록할 수 있음")했는데 151편이 '발견됨-미색인'으로 남아 있다.
글끼리 연결하는 링크가 0이었다 — 라벨·페이지네이션 링크는 /search 경로라 robots에 막히고,
홈에서 글로 가는 링크는 7개뿐이라 나머지는 사이트맵으로만 발견되는 고아 페이지였다.
본문 안의 직접 링크는 robots와 무관하게 따라간다.

기존 글은 소급하지 않는다 — 라이브 글 일괄 수정은 lastmod를 한꺼번에 흔든다(9/5에 75편).
새 글이 옛 글을 가리키는 방향만으로도 옛 글에 들어가는 링크가 쌓인다.
"""
import re

HEADING = "함께 보면 좋은 글"
# 제목에 흔한 서술 낱말 — 소재와 무관하게 겹쳐 엉뚱한 글을 잇는다(시험에서 '없이'가 최다 매칭)
_WEAK = {"없이", "방법", "확인", "이제", "이유", "하는", "되는", "가능", "새로운", "등장", "정리",
         "분석", "특징", "기능", "비교", "차이", "사용", "활용", "선택", "구매", "필요", "위한",
         "걱정", "간편하게", "쉽게", "바로", "직접", "해결", "만에", "동안", "까지", "부터"}


def _head(t):
    """제목의 제품명 부분(콜론 앞) — 같은 제품의 다른 글을 '관련 글'로 걸지 않기 위해."""
    return t.split(":")[0].strip().lower() if ":" in t else ""
_cache = None


def live_posts():
    """공개 글 [{title, url, labels}] — 한 프로세스에서 한 번만 조회한다."""
    global _cache
    if _cache is None:
        from upload_blogger import _service, resolve_blog_id
        svc, bid = _service(), resolve_blog_id()
        out, tok = [], None
        while True:
            kw = {"blogId": bid, "status": "LIVE", "fetchBodies": False, "maxResults": 100,
                  "fields": "nextPageToken,items(title,url,labels,published)"}
            if tok:
                kw["pageToken"] = tok
            d = svc.posts().list(**kw).execute()
            out += d.get("items", [])
            tok = d.get("nextPageToken")
            if not tok:
                break
        _cache = out
    return _cache


def pick(title, labels, n=3, posts=None):
    """관련 글 n개 [(title, url)]. 점수 = 공통 라벨×2 + 제목 공통 낱말.
    같은 소재(중복 판정)는 빼고, 점수 0은 넣지 않는다 — 억지 링크는 독자에게도 소음이다."""
    from blog_dedup import _keys, is_dup
    from blog_polish import BASE_LABEL
    posts = live_posts() if posts is None else posts
    mine_l = set(labels or ()) - {BASE_LABEL}
    mine_k = _keys(title) - _WEAK
    mine_h = _head(title)
    scored = []
    for p in posts:
        t = (p.get("title") or "").strip()
        if not t or t == title.strip():
            continue
        if is_dup(title, [t])[0] or (mine_h and _head(t) == mine_h):
            continue
        s = 2 * len(mine_l & (set(p.get("labels") or ()) - {BASE_LABEL})) + len(mine_k & (_keys(t) - _WEAK))
        if s > 0:
            scored.append((s, p.get("published") or "", t, p["url"]))
    scored.sort(reverse=True)
    return [(t, u) for _s, _d, t, u in scored[:n]]


def _crawl_url(u):
    """링크는 ?m=1 주소로 건다 (2026-09-29 서치콘솔 실측). 구글은 모바일 크롤러만 쓰는데
    데스크톱 주소는 302로 ?m=1에 넘어가고, 9/10 데스크톱 주소 요청 5편은 전부 '리디렉션
    오류'였다. 9/28 ?m=1 주소 요청 1편은 1분 만에 크롤·색인됐고 구글이 정본으로 고른 것도
    ?m=1 주소였다. 크롤러가 따라갈 링크는 리디렉션 없이 바로 200이 나는 쪽이어야 한다."""
    return u if "?m=" in u else u + "?m=1"


def section(items):
    if not items:
        return ""
    li = "".join('<li><a href="%s">%s</a></li>' % (_crawl_url(u), re.sub(r"[<>]", "", t))
                 for t, u in items)
    return '\n<h3>%s</h3>\n<ul>%s</ul>\n' % (HEADING, li)


def append(html, title, labels):
    """html 끝에 관련 글 섹션을 붙인다. 조회 실패는 무해 — 글 발행을 막지 않는다."""
    try:
        items = pick(title, labels)
    except Exception as e:
        print("[blog_related] 건너뜀(무해): %s" % str(e)[:100], flush=True)
        return html
    if items:
        print("[blog_related] 관련 글 %d개: %s" % (len(items), " / ".join(t[:18] for t, _ in items)),
              flush=True)
    return html + section(items)
