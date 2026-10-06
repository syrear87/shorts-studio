#!/usr/bin/env python3
# 실제 장면 사진 소스 (2026-10-07 디렉터: "손흥민 골장면 스틸샷이나 경기 장면을 넣어야지…
#   의미없는 배경화면 뭔데… 실제 장면을 사용해달라고 몇 번을 얘기해야 함?")
#
# 무엇: 뉴스 기사의 대표 사진(og:image)을 받아 배경으로 쓴다. 커먼즈에는 '그 선수'는 있어도
#   '어제 그 골'은 없다. 어제 그 골 사진은 뉴스에 있다. 검색 → 구글 뉴스 RSS → 기사별 og:image.
# 왜 사진인가: 중계 **영상** 클립은 Content ID가 자동 대조한다. **정지 사진** 한 장은 자동 대조
#   대상이 아니고, 남는 위험은 사진 통신사(연합·게티·AP)의 수동 신고뿐이다. 이 위험은 디렉터가
#   감수하기로 했다(2026-09-28 "실제 장면 캡쳐해서 움직이게 하던지", 2026-10-07 재지시).
#   그래도 ①한 편에 같은 매체 사진 2장 이내 ②설명란에 "사진: <매체>" 표기 ③영상 클립은 여전히 금지.
#
# 사용:
#   조사:  .venv/bin/python3 pipeline/fetch_scene.py "손흥민 프리킥 골 LAFC"   → 후보 + 썸네일
#   대본:  scene["bg"] = "scene:<이미지 URL>"  (make_short.py가 받아서 전체 보기(fit)로 띄운다)
#          또는 "scene:<기사 URL>" — og:image를 자동으로 뽑는다.
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "assets", "bg_cache")
CREDITS = os.path.join(CACHE, "scene_credits.json")
PREVIEW = os.path.join(ROOT, "out", "bg_candidates")
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}
IMG_EXT = (".jpg", ".jpeg", ".png", ".webp")
# 기사 대표 사진이 아니라 매체 로고·기본 썸네일인 경우 — 걸러낸다
BAD_IMG = re.compile(r"logo|default|placeholder|og_default|favicon|sprite|banner_|_thumb_default", re.I)


def _get(url, timeout=30):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout)


def news_search(query, n=12):
    """다음 뉴스 검색(최신순) → [(제목, 기사URL, 매체)]. 구글 뉴스 RSS는 링크가 암호화돼
    기사로 못 들어간다(2026-10-07 실측) — 다음은 v.daum.net 직링크를 준다."""
    url = "https://search.daum.net/search?w=news&q=%s&sort=recency" % urllib.parse.quote(query)
    with _get(url) as r:
        html = r.read().decode("utf-8", "ignore")
    out, seen = [], set()
    for m in re.finditer(r'<a[^>]+href="(https?://v\.daum\.net/v/\d+)"[^>]*>(.*?)</a>', html, re.S):
        link = m.group(1)
        if link in seen:
            continue
        title = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        if len(title) < 8:
            continue
        seen.add(link)
        out.append((title, link, ""))
        if len(out) >= n:
            break
    return out


def naver_images(query, n=12):
    """네이버 이미지 검색 → 뉴스 원본 이미지 URL 목록 (최신 날짜 경로 우선).
    검색 페이지의 썸네일은 search.pstatic.net/common/?src=<원본> 꼴이라 src를 풀면 원본이 나온다."""
    url = "https://search.naver.com/search.naver?where=image&query=%s" % urllib.parse.quote(query)
    with _get(url) as r:
        html = r.read().decode("utf-8", "ignore")
    found = []
    for m in re.finditer(r'search\.pstatic\.net/common/\?src=([^"&\']+)', html):
        src = urllib.parse.unquote(m.group(1))
        if not re.search(r"imgnews\.(naver|pstatic)\.(net|com)/image/", src) or "office_logo" in src:
            continue
        src = re.split(r"\?|\\u0026|&", src)[0]       # 썸네일 크기 파라미터(\u0026type=…) 제거 → 원본
        d = re.search(r"/(\d{4})/(\d{2})/(\d{2})/", src)
        found.append(((d.group(1) + d.group(2) + d.group(3)) if d else "0", src))
    found = sorted(dict.fromkeys(found), key=lambda x: x[0], reverse=True)
    return [u for _, u in found[:n]]


def og_image(article_url):
    """기사 → (대표 이미지 URL, 최종 기사 URL). 구글 뉴스 리디렉션도 따라간다."""
    try:
        with _get(article_url, timeout=30) as r:
            final = r.geturl()
            html = r.read(600000).decode("utf-8", "ignore")
    except Exception:
        return None, article_url
    # 구글 뉴스 중간 페이지는 JS 리디렉션 — 본문에 실제 URL이 박혀 있다
    if "news.google.com" in final:
        m = re.search(r'data-n-au="([^"]+)"|href="(https?://(?!news\.google)[^"]+)"', html)
        real = (m.group(1) or m.group(2)) if m else None
        if real:
            return og_image(real)
        return None, final
    for pat in (r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)',
                r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
                r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)'):
        m = re.search(pat, html, re.I)
        if m and not BAD_IMG.search(m.group(1)):
            return urllib.parse.urljoin(final, m.group(1)), final
    return None, final


def _save_credit(img_url, article_url, source):
    try:
        cr = json.load(open(CREDITS, encoding="utf-8"))
    except Exception:
        cr = {}
    cr[img_url] = {"article": article_url, "source": source}
    os.makedirs(CACHE, exist_ok=True)
    json.dump(cr, open(CREDITS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def credit_line(img_url):
    try:
        c = json.load(open(CREDITS, encoding="utf-8")).get(img_url)
    except Exception:
        c = None
    if not c:
        return None
    src = c.get("source") or urllib.parse.urlparse(c.get("article") or "").netloc
    return "사진: %s" % src if src else None


def fetch(ref):
    """'scene:' 뒤의 값(이미지 URL 또는 기사 URL) → 로컬 경로. 실패 시 None."""
    os.makedirs(CACHE, exist_ok=True)
    url = ref.strip()
    source = ""
    if not url.lower().split("?")[0].endswith(IMG_EXT):
        img, art = og_image(url)
        if not img:
            print("장면 사진 없음(og:image 없음): %s" % url[:80], flush=True)
            return None
        source = urllib.parse.urlparse(art).netloc
        url, article = img, art
    else:
        article = ""
    safe = re.sub(r"[^0-9A-Za-z_.-]", "_", url.split("/")[-1].split("?")[0])[:60] or "img"
    import hashlib
    path = os.path.join(CACHE, "scene_%s_%s" % (hashlib.md5(url.encode()).hexdigest()[:8], safe))
    if not path.lower().endswith(IMG_EXT):
        path += ".jpg"
    if not (os.path.exists(path) and os.path.getsize(path) > 20000):
        try:
            with _get(url, timeout=60) as r, open(path + ".part", "wb") as f:
                f.write(r.read())
            os.replace(path + ".part", path)
        except Exception as e:
            print("장면 사진 다운로드 실패: %s" % str(e)[:100], flush=True)
            return None
    try:
        from PIL import Image
        with Image.open(path) as im:
            w, h = im.size
        if min(w, h) < 500:
            print("장면 사진 해상도 부족(%dx%d): %s" % (w, h, url[:60]), flush=True)
            return None
    except Exception:
        pass
    _save_credit(ref.strip(), article, source)
    print("장면 사진 받음: %s (%s)" % (source or url[:50], os.path.basename(path)), flush=True)
    return path


def main():
    if len(sys.argv) < 2:
        sys.exit('사용: fetch_scene.py "검색어" [검색어2 ...]   (뉴스 기사 대표 사진 후보)')
    os.makedirs(PREVIEW, exist_ok=True)
    for qi, query in enumerate(sys.argv[1:]):
        print("\n== %s ==" % query)
        seen, k = set(), 0
        try:
            arts = news_search(query, n=12)
        except Exception as e:
            arts = []
            print("  (다음 뉴스 검색 실패: %s)" % str(e)[:60])
        for title, link, _src in arts:
            img, art = og_image(link)
            if not img or img in seen:
                continue
            seen.add(img)
            name = "s%d_%d.jpg" % (qi, k)
            try:
                with _get(img, timeout=30) as r, open(os.path.join(PREVIEW, name), "wb") as f:
                    f.write(r.read())
            except Exception:
                continue
            k += 1
            print("%-10s | %-16s | %s" % (name, urllib.parse.urlparse(art).netloc[:16], title[:46]))
            print('   bg 값: "scene:%s"' % art)
            if k >= 6:
                break
        if k < 3:
            try:
                for img in naver_images(query, n=8):
                    if img in seen:
                        continue
                    seen.add(img)
                    name = "s%d_%d.jpg" % (qi, k)
                    try:
                        with _get(img, timeout=30) as r, open(os.path.join(PREVIEW, name), "wb") as f:
                            f.write(r.read())
                    except Exception:
                        continue
                    k += 1
                    print("%-10s | %-16s | (네이버 이미지 검색, 날짜 %s)" % (name, "뉴스사진", (re.search(r"/(\d{4}/\d{2}/\d{2})/", img) or [None, "?"])[1]))
                    print('   bg 값: "scene:%s"' % img)
                    if k >= 8:
                        break
            except Exception as e:
                print("  (네이버 이미지 검색 실패: %s)" % str(e)[:60])
        if not k:
            print("  (후보 없음 — 검색어를 바꿔라: 선수명+골, 경기명+결과, 영문명)")
    print("\n미리보기: %s" % PREVIEW)
    print("⚠️ 눈으로 확인하라 — 그 경기·그 장면인가? 기자회견·자료사진이면 쓰지 마라. 채택 시 설명란에 '사진: 매체' 자동 표기.")


if __name__ == "__main__":
    main()
