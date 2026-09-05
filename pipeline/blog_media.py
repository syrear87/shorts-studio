#!/usr/bin/env python3
"""블로그 이미지 호스팅 — 카드에 쓴 실사 사진을 R2에 **영구** 업로드한다 (2026-08-27 신설).

배경: 디렉터가 첫 자동 생성 글을 보고 "이미지도 없고 너무 투박한데, 글만 많아서 안 볼 것
  같다"고 지적했다. 맞는 지적이다 — 텍스트 벽은 체류시간을 떨어뜨리고, 네이버·구글 모두
  체류시간을 품질 신호로 쓴다.

왜 새로 안 만드나: assets/cards/ 에 카드 제작에 쓴 실사 사진이 178장 쌓여 있다. 이미
  소재별로 골라둔 사진이라 그대로 쓰면 된다.

왜 R2 영구 경로인가: Blogger API v3는 **이미지 업로드를 지원하지 않는다.** 본문에서
  외부 URL을 참조해야 한다. 기존 r2_put()은 reels/ 에 올린 뒤 게시가 끝나면 지우는데
  (메타가 가져가면 그만이라), 블로그 글은 이미지를 계속 불러오므로 지우면 안 된다.
  그래서 blog/ 경로를 따로 쓰고 삭제하지 않는다.

파일 내용 해시를 키에 넣는다 — 같은 사진을 두 글이 써도 한 번만 올라가고, 사진을 교체하면
  URL이 바뀌어 CDN 캐시를 피한다 (2026-08-25 카드 캐시 실사고와 같은 대비).
"""
import hashlib
import json
import re
import mimetypes
import os
import tempfile
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _kv():
    kv = {}
    with open(os.path.join(ROOT, "keys.env"), encoding="utf-8") as f:
        for line in f:
            k, _, v = line.partition("=")
            if k.strip():
                kv[k.strip()] = v.strip().strip('"')
    return kv


def _client(kv):
    import boto3
    return boto3.client(
        "s3", endpoint_url="https://%s.r2.cloudflarestorage.com" % kv["R2_ACCOUNT_ID"],
        aws_access_key_id=kv["R2_ACCESS_KEY"], aws_secret_access_key=kv["R2_SECRET_KEY"],
        region_name="auto")


def put(path, kv=None, s3=None, name=None):
    """사진 1장을 blog/ 에 올리고 공개 URL을 돌려준다. 이미 있으면 그대로 쓴다.

    name: 파일명으로 쓸 이름(확장자 제외). 임시파일 이름이 그대로 URL에 박히면
      지저분하고 검색엔진에도 아무 의미가 없어 소재 기반 이름을 넘긴다.
    """
    if not os.path.exists(path):
        return None
    kv = kv or _kv()
    s3 = s3 or _client(kv)
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    base, ext = os.path.splitext(os.path.basename(path))
    if name:
        base = re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-")[:48] or base
    key = "blog/%s-%s%s" % (base, h.hexdigest()[:10], ext.lower())
    url = kv["R2_PUBLIC_URL"].rstrip("/") + "/" + key
    try:                                   # 같은 해시가 이미 있으면 업로드를 건너뛴다
        s3.head_object(Bucket=kv["R2_BUCKET"], Key=key)
        return url
    except Exception:
        pass
    ctype = mimetypes.guess_type(path)[0] or "image/jpeg"
    s3.upload_file(path, kv["R2_BUCKET"], key, ExtraArgs={"ContentType": ctype})
    return url


def is_real_product_shot(credit):
    """이 사진이 **실제 그 제품을 찍은 것**인가 — 크레딧으로 가른다.

    2026-08-27 디렉터: "왜 포켓몬 폴라로이드... 실제를 캡쳐 안 하고 다른 사진을 들고 왔냐".
      맞는 지적이고, 그 전에 내가 판단을 잘못했다. phone-cooler 카드 하나만 보고
      "카드 사진은 전부 배경용 스톡"이라 단정해 카드 이미지를 통째로 버렸는데, 실제로는
      **제품 카드는 공식 제품 사진을 쓰고 있었다**:
        poke_pola.jpg     → '이미지: Polaroid 공식 (Engadget)'
        rayneo_wear.jpg   → '이미지: Gizmodo'
        anker_prime_300w  → '이미지: Anker 공식 (anker.com)'
      제품 소개 글에 다른 제품의 스톡 사진을 넣으면 독자는 그게 그 제품인 줄 안다. 오도다.

    규칙: 크레딧이 'Pexels'면 스톡 배경(제품과 무관), 그 외(공식·매체명)는 실물 사진.
    """
    c = str(credit or "")
    if not c.strip():
        return False
    return "pexels" not in c.lower()


def images_of(meta, real_only=False):
    """원고에 쓰인 사진들 [(로컬경로, 크레딧), ...] — 중복 제거, 순서 유지.

    real_only=True면 **실제 제품 사진만** 돌려준다.
    """
    out, seen = [], set()
    for c in (meta or {}).get("cards", []) or []:
        img = (c or {}).get("img")
        if not img or img in seen:
            continue
        seen.add(img)
        credit = (c or {}).get("credit") or ""
        if real_only and not is_real_product_shot(credit):
            continue
        p = img if os.path.isabs(img) else os.path.join(ROOT, img)
        if os.path.exists(p):
            out.append((p, credit))
    return out


def product_shots(meta):
    """원고의 **실제 제품 사진**을 R2에 올려 [(url, 크레딧), ...]."""
    pairs = images_of(meta, real_only=True)
    if not pairs:
        return []
    kv = _kv()
    s3 = _client(kv)
    got = []
    for path, credit in pairs:
        try:
            u = put(path, kv=kv, s3=s3)
            if u:
                got.append((u, credit))
        except Exception as e:
            print("[blog_media] 제품 사진 업로드 실패(%s): %s"
                  % (os.path.basename(path), str(e)[:90]), flush=True)
    return got


def upload_all(meta):
    """원고의 사진을 전부 올리고 [(url, 크레딧), ...]."""
    pairs = images_of(meta)
    if not pairs:
        return []
    kv = _kv()
    s3 = _client(kv)
    got = []
    for path, credit in pairs:
        try:
            u = put(path, kv=kv, s3=s3)
            if u:
                got.append((u, credit))
        except Exception as e:
            print("[blog_media] 업로드 실패(%s): %s" % (os.path.basename(path), str(e)[:100]),
                  flush=True)
    return got


# ── Pexels 가로 사진 (2026-08-27) ─────────────────────────────────────────
# 디렉터: "저게 무슨 이미지들이지? 너무 확대되어 있어서 뭔지 알아보지도 못하겠네"
# 원인: assets/cards/ 사진은 **카드 배경용**이다. pick_bg가 orientation=portrait로 뽑아
#   세로 클로즈업·여백 넓은 추상 이미지만 모였다(카드는 그 위에 텍스트를 얹으니 그게 맞다).
#   폰 쿨러 편 대표 이미지는 '종이로 만든 온도계', 두 번째는 '팬 날개 극단 클로즈업'이었다.
#   블로그 본문은 정반대가 필요하다 — **가로, 피사체가 통째로 보이는 사진**.
# 그래서 카드 사진 재활용을 접고 소재에 맞는 가로 사진을 따로 받는다.


def _pexels_key():
    return _kv().get("PEXELS_API_KEY")


def search_photos(query, count=2, exclude_urls=()):
    """Pexels 가로 사진 검색 → [{url, credit, alt}, ...]."""
    key = _pexels_key()
    if not key or not (query or "").strip():
        return []
    url = ("https://api.pexels.com/v1/search?" + urllib.parse.urlencode(
        {"query": query, "per_page": 15, "orientation": "landscape", "size": "medium"}))
    # User-Agent를 안 보내면 Pexels가 403으로 막는다 (2026-08-27 실측: urllib 기본 UA는 거부,
    # requests의 UA는 통과). pick_bg는 requests라 이 문제를 겪지 않았다.
    req = urllib.request.Request(url, headers={
        "Authorization": key, "User-Agent": "shorts-studio/1.0 (+blog)"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r)
    except Exception as e:
        print("[blog_media] Pexels 검색 실패(%s): %s" % (query, str(e)[:90]), flush=True)
        return []
    # 검색어의 핵심 낱말이 사진 설명에 있는지 본다 — Pexels는 느슨하게 매칭해서
    # 'phone cooling fan'에 **CPU 히트싱크**·PC 케이스팬을 섞어 돌려준다
    # (2026-08-27 실측: 폰 쿨러 글에 히트싱크 사진이 들어갔다).
    keys_ = [w for w in re.split(r"[^a-z0-9]+", (query or "").lower())
             if len(w) > 2 and w not in {"the", "and", "for", "with"}]
    strong, weak = [], []
    for p in data.get("photos", []):
        src = (p.get("src") or {}).get("large") or (p.get("src") or {}).get("original")
        if not src or src in exclude_urls:
            continue
        # 지나치게 세로에 가까운 것은 거른다 — 본문에서 화면을 잡아먹는다
        w, h = p.get("width") or 0, p.get("height") or 1
        if w / float(h) < 1.2:
            continue
        alt = (p.get("alt") or "")
        item = {"url": src, "alt": alt[:80],
                "credit": "사진: %s (Pexels)" % (p.get("photographer") or "Pexels")}
        low = alt.lower()
        hits = sum(1 for k in keys_ if k in low)
        (strong if hits >= 2 else weak).append((hits, item))
    strong.sort(key=lambda x: -x[0])
    weak.sort(key=lambda x: -x[0])
    # 설명이 2낱말 이상 맞는 것부터. 그런 게 없으면 1낱말이라도 맞는 것만 쓰고,
    # 하나도 안 맞으면 **아무것도 쓰지 않는다** — 무관한 사진은 없느니만 못하다.
    picked = [it for _, it in strong] + [it for h, it in weak if h >= 1]
    return picked[:count]


def fetch_to_r2(photo, kv=None, s3=None, name=None):
    """Pexels 사진을 받아 R2 blog/ 에 영구 저장하고 공개 URL을 돌려준다.

    핫링크 대신 우리 버킷에 두는 이유: 블로그 글은 몇 년 남는데 원본 URL이 바뀌거나
    내려가면 이미지가 통째로 깨진다. 사진 자체는 Pexels 라이선스로 상업적 사용이 되며
    크레딧은 캡션에 표기한다.
    """
    kv = kv or _kv()
    s3 = s3 or _client(kv)
    try:
        req = urllib.request.Request(photo["url"], headers={"User-Agent": "shorts-studio/1.0"})
        with urllib.request.urlopen(req, timeout=60) as r:
            blob = r.read()
    except Exception as e:
        print("[blog_media] 사진 내려받기 실패: %s" % str(e)[:90], flush=True)
        return None
    ext = ".jpg"
    fd, tmp = tempfile.mkstemp(suffix=ext)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(blob)
        return put(tmp, kv=kv, s3=s3, name=name)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def photos_for(queries, count=3):
    """검색어들로 가로 사진을 모아 R2에 올린다 → [(url, 크레딧), ...]."""
    kv = _kv()
    if not kv.get("PEXELS_API_KEY"):
        return []
    s3 = _client(kv)
    got, seen = [], set()
    for q in queries:
        if len(got) >= count:
            break
        for ph in search_photos(q, count=2, exclude_urls=seen):
            if len(got) >= count:
                break
            seen.add(ph["url"])
            u = fetch_to_r2(ph, kv=kv, s3=s3, name=q)
            if u:
                got.append((u, ph["credit"]))
    return got
