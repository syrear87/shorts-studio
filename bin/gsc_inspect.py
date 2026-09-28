#!/usr/bin/env python3
"""Search Console URL 검사 API로 블로그 색인 상태를 **페이지 단위 정본 데이터**로 확정한다 (2026-09-28 신설).

왜 필요한가:
  서치콘솔 화면(2026-09-28 캡처)은 "알려진 페이지 156 · 색인 생성됨 0 · 발견됨-색인 안 됨 151"이고,
  세션은 그 집계 숫자 위에 "구글이 호스트 단위로 크롤링 가치 없음 판정" 같은 해석을 얹었다.
  디렉터가 "잘못 알고 있는 것 아니냐"고 도전했는데, 실은 그 해석을 뒷받침할 페이지 단위 실측이
  하나도 없었다. 화면의 집계로는 다음을 구분할 수 없다:
    (a) 구글이 그 페이지를 실제로 가져가 본 적이 있는가            → lastCrawlTime
    (b) 가져갔다면 무슨 상태로 봤는가                                → pageFetchState · robotsTxtState · indexingState
    (c) 구글이 고른 표준 URL이 우리가 선언한 것과 같은가            → googleCanonical vs userCanonical
    (d) 데스크톱/모바일 중 무엇으로 크롤링했는가 (?m=1 302 문제)     → crawledAs
    (e) 검색 결과에 단 한 번이라도 노출된 적이 있는가                → searchanalytics impressions
  "발견됨 - 현재 색인이 생성되지 않음"은 *크롤링조차 안 한 상태*와 *크롤링 후 버린 상태*를
  한 통에 담는 라벨이다. URL 검사 API는 그것을 URL마다 갈라 준다.

무엇을 하나 (전부 읽기 전용 — 이 도구는 어떤 API에도 쓰지 않는다):
  ① sites.list        속성 자동 탐지 (URL-prefix 'https://daily1pick.blogspot.com/' 우선 → sc-domain 차선)
  ② sitemaps.list     구글이 사이트맵을 언제 받아갔고, 몇 개를 '제출/색인'으로 보고하는지
  ③ searchanalytics   최근 28일 노출·클릭 합계 + 상위 페이지 10 (노출 0 = 검색에 한 번도 안 나옴)
  ④ urlInspection     홈 + Blogger API(LIVE, 읽기)에서 뽑은 최신 글 N개 (기본 25, --all 전체, --limit 상한)
  ⑤ 집계              coverageState별 개수 · lastCrawlTime 있는 URL 수(= 실제 크롤링된 적 있는 페이지 수) 등
  ⑥ --json            logs/gsc_inspect-YYYYMMDD.json 저장 (원본 응답 포함 — 나중 대조용)

쿼터: URL 검사는 속성당 하루 2,000건 · 분당 600건. 178편 전수(--all)도 하루 한 번은 여유가 있다.
DRY_RUN=1: 이 도구는 쓰기가 없어 원칙적으로 무관하지만, 저장소 규약(검증 실행은 항상 DRY_RUN=1)에 맞춰
  **쿼터를 소모하는 URL 검사와 파일 저장만 건너뛴다.** 인증·속성 탐지·사이트맵·검색 성과는 그대로 돈다.
  실측은 DRY_RUN 없이 돌려라.

스코프: https://www.googleapis.com/auth/webmasters.readonly — URL 검사도 readonly로 된다(discovery 문서 확인).
  token.json에 없으면 재인증 안내만 찍고 exit 2. 재인증은 브라우저 동의가 필요해 디렉터가 직접 한다.

사용:
  .venv/bin/python3 bin/gsc_inspect.py                     # 홈 + 최신 25편
  .venv/bin/python3 bin/gsc_inspect.py --all --json        # 전수 + logs/gsc_inspect-YYYYMMDD.json
  .venv/bin/python3 bin/gsc_inspect.py --limit 5 --url 'https://daily1pick.blogspot.com/?m=1'
                                                           # 임의 URL 추가 검사 (리디렉션 오류 4건 추적용)
"""
import argparse
import datetime
import json
import os
import sys
import time
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))

HOST = "daily1pick.blogspot.com"
HOME = "https://%s/" % HOST
SCOPE_RO = "https://www.googleapis.com/auth/webmasters.readonly"
SCOPE_RW = "https://www.googleapis.com/auth/webmasters"   # 상위 스코프 — 있으면 그것으로도 된다
TOKEN = os.path.join(ROOT, "token.json")
CRED = os.path.join(ROOT, "credentials.json")
EXIT_NO_SCOPE = 2
EXIT_NO_SITE = 3


def _dry():
    return os.environ.get("DRY_RUN") in ("1", "true", "True")


# ── 인증 ─────────────────────────────────────────────────────────────────────

def _token_scopes():
    """token.json의 scopes 목록만 읽는다 — 토큰 값은 절대 읽지도 찍지도 않는다.
    None = 파일 없음, [] = 읽기 실패/스코프 없음."""
    try:
        with open(TOKEN, encoding="utf-8") as f:
            return list(json.load(f).get("scopes") or [])
    except FileNotFoundError:
        return None
    except Exception:
        return []


def _project_id():
    """credentials.json의 project_id (비밀 아님). Search Console API 활성화 링크를 정확히 찍기 위해."""
    try:
        with open(CRED, encoding="utf-8") as f:
            d = json.load(f)
        return (d.get("installed") or d.get("web") or {}).get("project_id")
    except Exception:
        return None


def _scope_guide(scopes):
    """스코프가 없을 때의 안내. 재인증은 브라우저 동의라 여기서 자동으로 하지 않는다."""
    print("⛔ token.json에 Search Console 스코프가 없다 (webmasters.readonly / webmasters 둘 다 없음).")
    print("   현재 스코프:")
    for s in scopes:
        print("     -", s)
    print()
    print("재인증 절차 (디렉터가 맥미니 터미널에서 직접 — 브라우저 동의 1회):")
    print("  0. (한 번만) Google Cloud 콘솔에서 'Google Search Console API'를 켠다 — 안 켜면 403 accessNotConfigured")
    pid = _project_id()
    if pid:
        print("     https://console.cloud.google.com/apis/library/searchconsole.googleapis.com?project=%s" % pid)
    else:
        print("     https://console.cloud.google.com/apis/library/searchconsole.googleapis.com  (credentials.json과 같은 프로젝트)")
    print("  1. pipeline/setup_auth.py 의 SCOPES 목록 끝에 한 줄 추가:")
    print('       "%s",' % SCOPE_RO)
    print("  2. cd %s && .venv/bin/python3 pipeline/setup_auth.py" % ROOT)
    print("     → 브라우저에서 syrear87@gmail.com 선택 → '확인되지 않은 앱' 화면이면 고급 → 이동")
    print("     → 동의 항목 **전부** 체크 (YouTube 4개 + Blogger + Search Console). 하나라도 빠지면 기존 토큰 유지됨.")
    print("     (기존 token.json은 token.json.bak-<시각>으로 자동 백업된다)")
    print("  3. 다시: .venv/bin/python3 bin/gsc_inspect.py --json")
    sys.exit(EXIT_NO_SCOPE)


def _creds():
    scopes = _token_scopes()
    if scopes is None:
        sys.exit("token.json 없음 — pipeline/setup_auth.py를 먼저 실행하세요")
    have = SCOPE_RW if SCOPE_RW in scopes else (SCOPE_RO if SCOPE_RO in scopes else None)
    if not have:
        _scope_guide(scopes)
    from google_creds import load_creds
    return load_creds(require_scope=have)


def _gsc(creds):
    from googleapiclient.discovery import build
    # 'webmasters' v3가 아니라 'searchconsole' v1 — urlInspection은 v1에만 있다
    return build("searchconsole", "v1", credentials=creds, cache_discovery=False)


def _http_reason(e):
    """HttpError에서 사람이 읽을 사유만 뽑는다."""
    r = getattr(e, "reason", None) or ""
    try:
        det = e.error_details
        if det:
            r = "%s %s" % (r, det)
    except Exception:
        pass
    return (r or str(e)).strip()


def _die_if_api_off(e):
    """Search Console API가 프로젝트에서 꺼져 있으면 403 accessNotConfigured — 정확한 링크로 안내."""
    txt = str(e)
    if "accessNotConfigured" in txt or "has not been used in project" in txt or "is disabled" in txt:
        pid = _project_id()
        print("⛔ Search Console API가 이 OAuth 클라이언트의 프로젝트에서 꺼져 있다.")
        print("   켜는 곳: https://console.cloud.google.com/apis/library/searchconsole.googleapis.com%s"
              % ("?project=%s" % pid if pid else ""))
        print("   켠 뒤 재인증은 필요 없다 — 몇 분 기다렸다가 다시 실행하라.")
        sys.exit(EXIT_NO_SITE)


# ── ① 속성 탐지 ──────────────────────────────────────────────────────────────

def find_site(svc, want=None):
    """서치콘솔 속성을 정한다. 인자 --site > URL-prefix https > sc-domain > 첫 후보.
    URL-prefix를 우선하는 이유: 디렉터 캡처(색인 0/156)가 그 속성일 가능성이 높고,
    같은 속성으로 봐야 화면 숫자와 API 숫자를 1:1로 대조할 수 있다."""
    from googleapiclient.errors import HttpError
    try:
        entries = svc.sites().list().execute().get("siteEntry", [])
    except HttpError as e:
        _die_if_api_off(e)
        sys.exit("sites.list 실패: %s" % _http_reason(e))
    if want:
        for e in entries:
            if e.get("siteUrl") == want:
                return e
        sys.exit("--site %r 속성이 이 계정에 없다. 있는 속성:\n%s" % (
            want, "\n".join("  %s  (%s)" % (e.get("siteUrl"), e.get("permissionLevel")) for e in entries)))
    cands = [e for e in entries if HOST in (e.get("siteUrl") or "")]
    print("[속성] 이 계정의 서치콘솔 속성 %d개 중 %s 포함 %d개:" % (len(entries), HOST, len(cands)))
    for e in cands:
        print("   %-45s %s" % (e.get("siteUrl"), e.get("permissionLevel")))
    if not cands:
        print("⛔ %s 속성이 없다. 계정 전체 속성:" % HOST)
        for e in entries:
            print("   %-45s %s" % (e.get("siteUrl"), e.get("permissionLevel")))
        print("   → 서치콘솔에 로그인한 계정이 syrear87@gmail.com 이 맞는지, 속성이 다른 계정에 있지 않은지 확인.")
        sys.exit(EXIT_NO_SITE)
    pick = None
    for e in cands:
        if e.get("siteUrl") == HOME:
            pick = e
            break
    if pick is None:
        for e in cands:
            if (e.get("siteUrl") or "").startswith("sc-domain:"):
                pick = e
                break
    pick = pick or cands[0]
    if pick.get("permissionLevel") == "siteUnverifiedUser":
        print("⚠ 이 속성은 '미확인 사용자' 권한이다 — URL 검사·검색 성과가 거부될 수 있다.")
    return pick


# ── ② 사이트맵 ────────────────────────────────────────────────────────────────

def sitemaps(svc, site):
    """구글이 사이트맵을 어떻게 보고 있는지. lastDownloaded 가 없으면 아직 한 번도 안 받아간 것이고,
    contents[].indexed 는 구글이 '색인했다'고 스스로 보고하는 수(화면의 0과 대조)."""
    from googleapiclient.errors import HttpError
    try:
        items = svc.sitemaps().list(siteUrl=site).execute().get("sitemap", [])
    except HttpError as e:
        _die_if_api_off(e)
        print("[사이트맵] 조회 실패: %s" % _http_reason(e))
        return []
    print("\n[사이트맵] 제출된 사이트맵 %d개" % len(items))
    if not items:
        print("   (없음 — 서치콘솔에 사이트맵이 제출된 적이 없거나, 이 속성에는 안 보인다)")
    for s in items:
        cont = s.get("contents") or []
        sub = sum(int(c.get("submitted", 0)) for c in cont)
        idx = sum(int(c.get("indexed", 0)) for c in cont)
        print("   %s" % s.get("path"))
        print("      제출 %s · 마지막 다운로드 %s · 대기중 %s · 오류 %s · 경고 %s · 제출URL %d · 색인보고 %d" % (
            _dt(s.get("lastSubmitted")), _dt(s.get("lastDownloaded")), s.get("isPending"),
            s.get("errors", 0), s.get("warnings", 0), sub, idx))
    return items


# ── ③ 검색 성과 ──────────────────────────────────────────────────────────────

def analytics(svc, site, days):
    """최근 N일 노출/클릭. dataState=ALL 이라 아직 확정 안 된 최근 2~3일도 포함한다.
    노출이 0이면 '색인은 됐는데 순위가 낮다'가 아니라 '검색 결과에 한 번도 안 나왔다'는 뜻."""
    from googleapiclient.errors import HttpError
    end = datetime.date.today()
    start = end - datetime.timedelta(days=days)
    base = {"startDate": start.isoformat(), "endDate": end.isoformat(), "dataState": "ALL"}
    out = {"startDate": base["startDate"], "endDate": base["endDate"]}
    try:
        tot = svc.searchanalytics().query(siteUrl=site, body=dict(base)).execute()
        rows = tot.get("rows") or []
        t = rows[0] if rows else {}
        out["total"] = {"clicks": t.get("clicks", 0), "impressions": t.get("impressions", 0),
                        "ctr": t.get("ctr", 0), "position": t.get("position", 0)}
        pages = svc.searchanalytics().query(
            siteUrl=site, body=dict(base, dimensions=["page"], rowLimit=10)).execute()
        out["top_pages"] = [{"page": r["keys"][0], "clicks": r.get("clicks", 0),
                             "impressions": r.get("impressions", 0), "position": r.get("position", 0)}
                            for r in (pages.get("rows") or [])]
        # 노출이 있었다면 어떤 검색어였는지도 — 브랜드 검색(블로그 이름)인지 일반 검색인지 갈린다
        qs = svc.searchanalytics().query(
            siteUrl=site, body=dict(base, dimensions=["query"], rowLimit=10)).execute()
        out["top_queries"] = [{"query": r["keys"][0], "clicks": r.get("clicks", 0),
                               "impressions": r.get("impressions", 0)}
                              for r in (qs.get("rows") or [])]
    except HttpError as e:
        _die_if_api_off(e)
        out["error"] = _http_reason(e)
        print("\n[검색 성과] 조회 실패: %s" % out["error"])
        return out
    t = out["total"]
    print("\n[검색 성과] %s ~ %s (%d일, dataState=ALL)" % (out["startDate"], out["endDate"], days))
    print("   노출 %s · 클릭 %s · CTR %.2f%% · 평균 순위 %.1f" % (
        t["impressions"], t["clicks"], t["ctr"] * 100, t["position"]))
    if out["top_pages"]:
        print("   상위 페이지:")
        for r in out["top_pages"]:
            print("      노출 %4d 클릭 %3d 순위 %5.1f  %s" % (r["impressions"], r["clicks"], r["position"], _short(r["page"])))
    else:
        print("   상위 페이지: (없음 — 이 기간 검색 결과에 노출된 URL이 하나도 없다)")
    if out["top_queries"]:
        print("   상위 검색어:")
        for r in out["top_queries"]:
            print("      노출 %4d 클릭 %3d  %s" % (r["impressions"], r["clicks"], r["query"]))
    return out


# ── ④ 검사 대상 URL ──────────────────────────────────────────────────────────

def blog_urls(limit=25, everything=False):
    """Blogger API(읽기)에서 공개(LIVE) 글 URL을 최신순으로 뽑는다.
    사이트맵 대신 Blogger를 쓰는 이유: 사이트맵은 구글이 보는 목록이고, 이건 우리가 실제로
    공개한 목록이다 — 둘이 다르면 그것도 신호다(--json에 남는다)."""
    from upload_blogger import _service, resolve_blog_id
    svc = _service()
    bid = resolve_blog_id()
    urls, tok = [], None
    while True:
        r = svc.posts().list(blogId=bid, maxResults=100 if everything else min(limit, 100),
                             pageToken=tok, fetchBodies=False, fetchImages=False).execute()
        for p in r.get("items", []):
            if p.get("status") and p["status"] != "LIVE":   # status는 관리자 응답에만 있다
                continue
            if p.get("url"):
                urls.append(p["url"])
        tok = r.get("nextPageToken")
        if not tok or (not everything and len(urls) >= limit):
            break
    return urls if everything else urls[:limit]


# ── ⑤ URL 검사 ───────────────────────────────────────────────────────────────

def inspect(svc, site, url):
    """URL 하나 검사. 429/5xx는 지수 백오프 3회. 그 외 오류는 행에 남기고 계속 간다
    (URL-prefix 속성에 http:// 나 다른 호스트를 넣으면 400 — 그 사실 자체가 정보다)."""
    from googleapiclient.errors import HttpError
    body = {"inspectionUrl": url, "siteUrl": site, "languageCode": "ko"}
    for attempt in range(4):
        try:
            return svc.urlInspection().index().inspect(body=body).execute()
        except HttpError as e:
            _die_if_api_off(e)
            if e.resp.status in (429, 500, 503) and attempt < 3:
                time.sleep(2 ** attempt)
                continue
            return {"error": "%s %s" % (e.resp.status, _http_reason(e))}
    return {"error": "재시도 소진"}


def _row(url, res):
    ir = res.get("inspectionResult") or {}
    idx = ir.get("indexStatusResult") or {}
    gc, uc = idx.get("googleCanonical"), idx.get("userCanonical")
    if gc and uc:
        canon = "=" if gc == uc else "≠"
    elif uc:
        canon = "-"       # 구글이 고른 표준 URL이 없음 = 색인 안 됨(또는 크롤링 전)
    else:
        canon = "?"
    return {
        "url": url,
        "error": res.get("error"),
        "verdict": idx.get("verdict"),
        "coverageState": idx.get("coverageState"),
        "lastCrawlTime": idx.get("lastCrawlTime"),
        "crawledAs": idx.get("crawledAs"),
        "pageFetchState": idx.get("pageFetchState"),
        "robotsTxtState": idx.get("robotsTxtState"),
        "indexingState": idx.get("indexingState"),
        "googleCanonical": gc,
        "userCanonical": uc,
        "canonMatch": canon,
        "referringUrls": idx.get("referringUrls") or [],
        "sitemap": idx.get("sitemap") or [],
        "inspectionResultLink": ir.get("inspectionResultLink"),
        "raw": ir,
    }


# ── 출력 ─────────────────────────────────────────────────────────────────────

_ENUM_SHORT = {
    "PAGE_FETCH_STATE_UNSPECIFIED": "-", "SUCCESSFUL": "OK",
    "INDEXING_STATE_UNSPECIFIED": "-", "INDEXING_ALLOWED": "ALLOWED",
    "ROBOTS_TXT_STATE_UNSPECIFIED": "-",
    "CRAWLING_USER_AGENT_UNSPECIFIED": "-", "DESKTOP": "desk", "MOBILE": "mobile",
    "VERDICT_UNSPECIFIED": "-",
}


def _s(v):
    return _ENUM_SHORT.get(v, v) if v else "-"


def _dt(v):
    """RFC3339 → 'YYYY-MM-DD HH:MM' (UTC 그대로. 화면과 대조할 때 KST +9 주의)."""
    if not v:
        return "-"
    return v.replace("T", " ")[:16]


def _short(url):
    for pre in ("https://%s" % HOST, "http://%s" % HOST):
        if url.startswith(pre):
            return url[len(pre):] or "/"
    return url


def print_table(rows):
    hdr = "%-3s %-46s %-38s %-16s %-6s %-15s %-8s %-16s %-2s %-7s" % (
        "#", "URL(경로)", "coverageState", "lastCrawl(UTC)", "as", "fetch", "robots", "indexing", "c", "verdict")
    print("\n[URL 검사] %d개" % len(rows))
    print(hdr)
    print("-" * len(hdr))
    for i, r in enumerate(rows, 1):
        if r["error"]:
            print("%-3d %-46s ⛔ %s" % (i, r["url"][:46], r["error"][:110]))   # 오류 행은 전체 URL(http:// 구분)
            continue
        print("%-3d %-46s %-38s %-16s %-6s %-15s %-8s %-16s %-2s %-7s" % (
            i, _short(r["url"])[:46], (r["coverageState"] or "-")[:38], _dt(r["lastCrawlTime"]),
            _s(r["crawledAs"]), _s(r["pageFetchState"]), _s(r["robotsTxtState"]),
            _s(r["indexingState"]), r["canonMatch"], _s(r["verdict"])))
    print("  c: googleCanonical vs userCanonical  '=' 일치 · '≠' 불일치 · '-' 구글 표준 없음(색인 안 됨) · '?' 둘 다 없음")


def summarize(rows):
    ok = [r for r in rows if not r["error"]]
    err = [r for r in rows if r["error"]]
    crawled = [r for r in ok if r["lastCrawlTime"]]
    summ = {
        "inspected": len(rows), "errors": len(err),
        "coverageState": dict(Counter(r["coverageState"] or "(없음)" for r in ok)),
        "verdict": dict(Counter(r["verdict"] or "(없음)" for r in ok)),
        "crawled_ever": len(crawled),
        "never_crawled": len(ok) - len(crawled),
        "crawledAs": dict(Counter(r["crawledAs"] or "(없음)" for r in crawled)),
        "pageFetchState": dict(Counter(r["pageFetchState"] or "(없음)" for r in crawled)),
        "robots_not_allowed": sum(1 for r in crawled if r["robotsTxtState"] not in (None, "ALLOWED")),
        "indexing_blocked": sum(1 for r in crawled if r["indexingState"] not in (None, "INDEXING_ALLOWED")),
        "canonical_mismatch": sum(1 for r in ok if r["canonMatch"] == "≠"),
        "google_canonical_present": sum(1 for r in ok if r["googleCanonical"]),
        "in_sitemap": sum(1 for r in ok if r["sitemap"]),
        "has_referrers": sum(1 for r in ok if r["referringUrls"]),
        "first_crawl": min((r["lastCrawlTime"] for r in crawled), default=None),
        "last_crawl": max((r["lastCrawlTime"] for r in crawled), default=None),
    }
    print("\n[집계] 검사 %d · 오류 %d" % (summ["inspected"], summ["errors"]))
    print("   coverageState:")
    for k, v in sorted(summ["coverageState"].items(), key=lambda kv: -kv[1]):
        print("      %3d  %s" % (v, k))
    print("   verdict: %s" % ", ".join("%s %d" % kv for kv in summ["verdict"].items()))
    print("   실제 크롤링된 적 있는 URL(lastCrawlTime 있음): %d / %d   ← 0이면 '크롤링 거부', >0이면 '크롤링 후 미색인'"
          % (summ["crawled_ever"], len(ok)))
    if crawled:
        print("      크롤링 시각 범위: %s ~ %s (UTC)" % (_dt(summ["first_crawl"]), _dt(summ["last_crawl"])))
        print("      crawledAs: %s" % ", ".join("%s %d" % kv for kv in summ["crawledAs"].items()))
        print("      pageFetchState: %s" % ", ".join("%s %d" % kv for kv in summ["pageFetchState"].items()))
        print("      robots 차단 %d · noindex/헤더 차단 %d" % (summ["robots_not_allowed"], summ["indexing_blocked"]))
    print("   구글 표준 URL 있음(=색인 흔적) %d · 표준 불일치 %d · 사이트맵에서 발견 %d · 참조 링크 있음 %d" % (
        summ["google_canonical_present"], summ["canonical_mismatch"], summ["in_sitemap"], summ["has_referrers"]))
    return summ


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Search Console URL 검사 — 블로그 색인 상태 실측 (읽기 전용)")
    ap.add_argument("--all", action="store_true", help="공개 글 전부 검사 (기본은 최신 25편)")
    ap.add_argument("--limit", type=int, default=25, help="검사할 글 수 상한 (기본 25, --all이면 상한으로만 작용, 0=무제한)")
    ap.add_argument("--url", action="append", default=[], help="추가로 검사할 임의 URL (반복 가능)")
    ap.add_argument("--no-home", action="store_true", help="홈 URL은 검사하지 않는다")
    ap.add_argument("--site", default=None, help="속성 URL 직접 지정 (예: sc-domain:daily1pick.blogspot.com)")
    ap.add_argument("--days", type=int, default=28, help="검색 성과 기간 (기본 28일)")
    ap.add_argument("--json", nargs="?", const="", default=None, metavar="경로",
                    help="결과 저장. 경로 생략 시 logs/gsc_inspect-YYYYMMDD.json")
    a = ap.parse_args()

    if _dry():
        print("[DRY_RUN] URL 검사(쿼터 소모)와 파일 저장은 건너뛴다. 인증·속성·사이트맵·검색 성과만 확인한다.")

    creds = _creds()                      # 스코프 없으면 여기서 안내 후 exit 2
    svc = _gsc(creds)
    site_entry = find_site(svc, a.site)
    site = site_entry["siteUrl"]
    print("[속성] 사용: %s (%s)" % (site, site_entry.get("permissionLevel")))

    sm = sitemaps(svc, site)
    an = analytics(svc, site, a.days)

    # 검사 대상: 홈 + 최신 글 + 임의 URL. 중복 제거하되 순서 유지.
    targets = [] if a.no_home else [HOME]
    try:
        posts = blog_urls(limit=(a.limit or 10 ** 6), everything=a.all)
        if a.all and a.limit:
            posts = posts[:a.limit]
    except SystemExit:
        raise
    except Exception as e:   # Blogger 쪽이 죽어도 홈·--url 검사는 하게 둔다
        print("⚠ Blogger 글 목록 실패(%s) — 홈·--url만 검사한다" % e)
        posts = []
    targets += posts + a.url
    seen, uniq = set(), []
    for u in targets:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    targets = uniq
    print("\n[대상] 홈 %s + 글 %d + 추가 %d = %d URL" % ("포함" if not a.no_home else "제외", len(posts), len(a.url), len(targets)))

    if _dry():
        for u in targets:
            print("   (dry) %s" % u)
        print("\n[DRY_RUN] 여기까지. 실측은 DRY_RUN 없이 다시 실행.")
        return

    rows = []
    for i, u in enumerate(targets, 1):
        res = inspect(svc, site, u)
        rows.append(_row(u, res))
        if i % 25 == 0:
            print("   … %d/%d" % (i, len(targets)), flush=True)
        time.sleep(0.15)    # 분당 600 한도에 한참 못 미치지만, 공손하게
    print_table(rows)
    summ = summarize(rows)

    if a.json is not None:
        path = a.json or os.path.join(ROOT, "logs", "gsc_inspect-%s.json" % datetime.date.today().strftime("%Y%m%d"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        doc = {
            "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "site": site_entry, "sitemaps": sm, "analytics": an,
            "summary": summ, "rows": rows,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
        print("\n저장: %s" % path)


if __name__ == "__main__":
    main()
