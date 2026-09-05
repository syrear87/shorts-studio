#!/usr/bin/env python3
"""테크 원고 → 블로그 글 생성 (2026-08-27 신설).

왜 원고를 그대로 못 쓰나: 우리 원고는 45초 영상·카드용이라 300~500자다. 그대로 올리면
  검색엔진이 '짧고 상업성 짙은 글'로 본다. 네이버는 2025-12부터 발행 즉시 노출이 아니라
  체류시간·이탈률을 보는 검증 루프를 돌리고, 구글도 얇은 콘텐츠를 걸러낸다.
  그래서 **검색 의도에 맞춰 다시 쓴다** — 복사가 아니다.

왜 팩트 게이트가 안에 있나: 블로그 글은 검색에 영구히 남아 SNS 글보다 회수가 어렵다.
  거제 만조·수능 4억·네팔 편은 전부 공개된 뒤에야 잡혔다. 생성 모델이 그럴듯한 수치를
  지어내면 그게 그대로 박힌다. 그래서 **원고에 없는 숫자를 전부 찾아내** 초안에 첨부한다.
  차단이 아니라 표시인 이유: 유용한 보충 설명에도 숫자는 들어가고(예: 습도 70~80%),
  그건 사람이 출처를 확인할 문제지 기계가 일괄로 지울 문제가 아니다.

쿠팡 링크는 affiliate_pool 단일 정본으로 매칭한다 — 스레드·카드와 같은 판정을 쓴다.
"""
import json
import os
import re
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))

MODEL = "gemini-2.5-flash"
MIN_CHARS = 1500          # 이보다 짧으면 얇은 글로 본다


def _key():
    for line in open(os.path.join(ROOT, "keys.env"), encoding="utf-8"):
        line = line.strip()
        if line.startswith("GEMINI_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"')
    return None


PROMPT = """당신은 한국어 테크 블로그 글을 쓴다. 아래 원고를 검색으로 들어온 독자에게
유용한 블로그 글로 다시 쓴다. 복사가 아니라 재구성이다.

# 절대 규칙
1. **원고에 없는 수치를 새로 만들지 마라.** 온도·가격·날짜·퍼센트·용량은 원고에 있는
   값만 쓴다. 모르면 숫자 없이 서술하라.
2. **직접 써본 것처럼 쓰지 마라.** "제가 써보니", "직접 테스트했더니" 금지.
   공개된 자료를 정리하는 입장으로 쓴다.
3. 원고에 출처가 있으면 글 끝에 그대로 밝힌다. 없는 출처를 지어내지 마라.
4. 광고 문구를 쓰지 마라. 판단은 독자가 한다.

# 글 구조
- 도입 2~3문장: 독자가 겪는 상황을 짚는다. 과장 금지.
- `<h2>결론부터</h2>`: 핵심 답을 먼저 준다. 목록으로.
- `<h2>`로 나눈 본문 3~4개: 왜 그런지 원리와 근거.
- 비교할 값이 둘 이상이면 `<table>`로 정리한다.
- `<h2>고를 때 확인할 것</h2>` 또는 그에 준하는 실용 체크리스트.
- `<h2>정리</h2>`: 2~3문장.

# 형식
- HTML 조각만 출력한다. `<html>`, `<head>`, `<body>` 태그 금지.
- 쓸 태그: p, h2, h3, ul, ol, li, table, thead, tbody, tr, th, td, strong, hr
- table에는 style="border-collapse:collapse;width:100%"를, td/th에는
  style="border:1px solid #ddd;padding:8px" 를 넣는다.
- 1500자 이상. 설명충 금지 — 길이를 위해 같은 말을 반복하지 마라.
- 존댓말(합니다체).
- **한 문단은 2~3문장을 넘기지 마라.** 긴 문단은 화면에서 벽처럼 보여 읽히지 않는다.
- 핵심 문장은 <strong>으로 짚어준다. 다만 한 섹션에 2개를 넘기지 마라.
- 표로 정리할 수 있는 건 문장으로 늘어놓지 말고 표로 만든다.

# 읽히게 만들기
- **이모지를 쓰지 마라.** 제목에도, 목록에도, 본문에도 하나도 넣지 마라.
  `🔍 결론부터`, `✅ 고를 때`, `⚡ 원리` 같은 것은 AI가 쓴 티가 나는 대표적인 패턴이라
  읽는 사람이 바로 알아본다 (2026-08-27 디렉터 지적).
- 글 전체에서 **가장 중요한 문장 2~3개**를 `<mark>` 로 감싼다. 남발하면 효과가 없다.
- 제목은 그 절의 내용을 그대로 말하는 평범한 문장으로 쓴다. 꾸미지 마라.

# 사람이 쓴 것처럼
- "~에 집중합니다", "~를 알아보겠습니다", "결론부터 말씀드리면" 같은 상투구를 피한다.
- 모든 절을 같은 길이·같은 구조로 만들지 마라. 짧게 끝낼 절은 짧게 끝낸다.
- 굵은 글씨를 절마다 기계적으로 넣지 마라. 정말 중요한 곳에만 쓴다.
- 마지막을 "~하시기 바랍니다" 같은 공지문으로 닫지 마라.

# 사진 검색어
본문 다음 줄에 `PHOTOS: ` 로 시작하는 줄을 쓴다. 이 글에 어울리는 **사진 검색어 2개**를
영어로, ` | ` 로 구분해 쓴다. 실물이 통째로 보이는 사진이 나올 만한 구체적인 말로.
예: `PHOTOS: smartphone cooling fan gaming | phone overheating hand`

# 제목
첫 줄에 `TITLE: ` 로 시작하는 제목 한 줄을 쓴다. 검색어가 들어가되 낚시는 금지.

**⚠️ 제목 맨 앞에 영문 브랜드·모델명을 넣어라 (2026-08-31 실측 개선)**: Blogger는 제목으로 URL을
자동 생성하는데 **한글은 슬러그로 변환되지 않는다.** 그래서 한글로 시작하는 제목은
`/2026/08/3.html`·`/2026/08/blog-post_30.html`처럼 의미 없는 URL이 된다(실측: 공개 57편 중 26편).
반면 영문 모델명으로 시작한 글은 `/anbernic-rg-55g1.html`·`/asus-zenscreen-duo-oled.html`처럼
검색어가 그대로 URL에 박힌다. Blogger API는 커스텀 URL 지정을 지원하지 않으므로 **제목이 유일한 수단**이다.

- 제품 글: `Anbernic RG 55G1: 스위치 라이트 닮은 휴대용 레트로 게임기` — **영문 모델명이 맨 앞**
- 제품명이 한글뿐이면 영문 표기를 병기: `가민 인스팅트 3 솔라` → `Garmin Instinct 3 Solar: 햇빛으로...`
- 제품이 없는 주제 글도 **핵심 영문 키워드를 앞이나 중간에** 넣어라:
  `노트북 성능 저하` → `노트북 발열 스로틀링(Thermal Throttling), 성능이 떨어지는 진짜 이유`
- 영문을 억지로 만들지는 마라 — 실제로 쓰이는 브랜드·규격·기술명만(USB-C, ANC, microSD, OLED 등).
그 다음 줄부터 HTML 본문.

# 원고
{{ORIGIN}}
"""


def _gemini(prompt, timeout=180):
    key = _key()
    if not key:
        raise RuntimeError("GEMINI_API_KEY 없음")
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 8192},
    }).encode()
    req = urllib.request.Request(
        "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent?key=%s"
        % (MODEL, key), data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        resp = json.load(r)
    cands = resp.get("candidates") or []
    parts = (cands[0].get("content", {}).get("parts") or []) if cands else []
    if not parts:
        raise RuntimeError("모델 응답 없음(%s)" % str(
            cands[0].get("finishReason") if cands else resp.get("promptFeedback"))[:80])
    return parts[0].get("text") or ""


def source_text(meta):
    """원고에서 판정·생성에 쓸 텍스트를 모은다."""
    parts = []
    for k in ("topic", "title", "caption", "threads_text", "description"):
        v = (meta or {}).get(k)
        if v:
            parts.append(str(v))
    for c in (meta or {}).get("cards", []) or []:
        for k in ("title", "body", "sub", "credit"):
            v = (c or {}).get(k)
            if v:
                parts.append(str(v))
    for s in (meta or {}).get("scenes", []) or []:
        for k in ("text", "narration", "sub"):
            v = (s or {}).get(k)
            if v:
                parts.append(str(v))
    if (meta or {}).get("narrator"):
        parts.append(str(meta["narrator"]))
    return "\n".join(parts)


_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _numbers(text):
    """의미 있는 숫자만 — 한 자리 수와 순서 번호는 소음이라 뺀다."""
    out = set()
    for m in _NUM.finditer(text or ""):
        raw = m.group(0).replace(",", "")
        if len(raw.replace(".", "")) < 2:
            continue
        out.add(raw)
    return out


def fact_check(article, origin):
    """원고에 없는 숫자 목록. 사람이 확인할 지점을 알려주는 용도다."""
    src = _numbers(origin)
    new = []
    for n in sorted(_numbers(article), key=lambda x: (-len(x), x)):
        if n in src:
            continue
        # 콤마 표기 차이 흡수 — 원고가 "35,000"이고 글이 "35000"인 경우
        if any(n == s.replace(",", "") for s in src):
            continue
        new.append(n)
    return new


SUMMARY_BOX = ('<div style="background:#f4f8ff;border:1px solid #d6e4ff;'
               'border-left:5px solid #1a73e8;padding:18px 22px;margin:26px 0;'
               'border-radius:10px;line-height:1.75;">')


def _figure(url, credit, first=False):
    cap = ('<figcaption style="text-align:center;color:#999;font-size:0.85em;'
           'margin-top:8px;">%s</figcaption>' % credit) if credit else ""
    return ('<figure style="margin:%s 0 28px;">'
            '<img src="%s" alt="" style="width:100%%;height:auto;border-radius:8px;'
            'display:block;">%s</figure>' % ("0" if first else "32px", url, cap))


MARK_STYLE = ('background:linear-gradient(transparent 55%,#fff3a3 55%);'
              'padding:0 2px;font-weight:600;')
STRONG_STYLE = "color:#1a4fa0;"


def style_marks(html):
    """<mark>는 형광펜처럼, <strong>은 색으로 — 볼드만으로는 눈에 안 들어온다.

    디렉터(2026-08-27): "이모티콘이나 텍스트 컬러도 주요 글 강조 볼드 말고 좀 센스있고
      가독성있게". Blogger 본문은 외부 CSS를 못 쓰므로 인라인 스타일로 넣는다.
    """
    html = re.sub(r"<mark>", '<span style="%s">' % MARK_STYLE, html)
    html = html.replace("</mark>", "</span>")
    html = re.sub(r"<strong>", '<strong style="%s">' % STRONG_STYLE, html)
    return html


def decorate(html, images):
    """이미지를 섹션 사이에 끼우고, 첫 요약 섹션을 상자로 감싼다.

    디렉터 지적(2026-08-27): "이미지도 없고 너무 투박한데, 글만 많아서 안 볼 것 같다".
      본문이 <p>와 <h2>만 늘어선 텍스트 벽이면 체류시간이 떨어지고, 체류시간은
      네이버·구글 모두 품질 신호로 쓴다. 이미지는 새로 만들지 않고 카드에 쓴 실사를 재사용한다.
    """
    if not images:
        return html
    # 첫 장은 글 맨 위 대표 이미지
    out = _figure(images[0][0], images[0][1], first=True) + "\n" + html
    rest = images[1:]
    if not rest:
        return out
    # 나머지는 h2 앞에 하나씩 — 맨 앞 h2(결론부터)는 건너뛰어 도입부가 이미지에 끊기지 않게
    parts = re.split(r"(<h2[^>]*>)", out)
    heads = [i for i, x in enumerate(parts) if x.startswith("<h2")]
    for n, idx in enumerate(heads[1:]):
        if n >= len(rest):
            break
        parts[idx] = _figure(rest[n][0], rest[n][1]) + "\n" + parts[idx]
    return "".join(parts)


def boxed_summary(html):
    """'결론부터' 섹션의 목록을 눈에 띄는 상자로 — 스캔하는 독자가 답을 먼저 본다."""
    m = re.search(r"(<h2[^>]*>\s*결론부터\s*</h2>)(.*?)(?=<h2|$)", html, re.S)
    if not m:
        return html
    inner = m.group(2).strip()
    if not inner:
        return html
    return html[:m.start()] + SUMMARY_BOX + m.group(1) + inner + "</div>" + html[m.end():]


# 이 태그가 붙은 카드는 **특정 제품을 소개하는 글**이다. 여기에 다른 제품의 스톡 사진을
# 넣으면 독자는 그게 그 제품인 줄 안다 — 실물이 없으면 차라리 이미지를 넣지 않는다.
PRODUCT_TAGS = {"구매가능", "신제품", "루머", "펀딩"}


def pick_images(meta, queries):
    """이 글에 넣을 사진 [(url, 크레딧), ...].

    ① 원고에 **실제 제품 사진**이 있으면 그것을 쓴다 (카드가 이미 공식 이미지를 확보해 둔다).
    ② 없고 제품 소개 글이면 → **넣지 않는다.** 스톡으로 대체하면 오도다.
    ③ 없고 일반 정보 글이면 → Pexels 가로 사진으로 분위기를 채운다.
    """
    from blog_media import product_shots, photos_for
    from blog_gate import card_tags
    real = product_shots(meta)
    if real:
        return real
    if card_tags(meta) & PRODUCT_TAGS:
        print("[make_blog] 제품 글인데 실물 사진이 없다 — 이미지 없이 간다", flush=True)
        return []
    return photos_for(queries or [str((meta or {}).get("topic") or "")[:60]], count=3)


def build(meta, blog_link=True):
    """원고 dict → {title, html, new_numbers, product}."""
    origin = source_text(meta)
    if not origin.strip():
        raise ValueError("원고에서 텍스트를 못 찾았다")
    raw = _gemini(PROMPT.replace("{{ORIGIN}}", origin))

    title, html = "", raw
    m = re.search(r"^\s*TITLE:\s*(.+)$", raw, re.M)
    if m:
        title = m.group(1).strip()
        html = raw[m.end():].strip()
    html = re.sub(r"^```(?:html)?\s*|\s*```$", "", html.strip())
    if not title:
        title = str((meta or {}).get("title") or (meta or {}).get("topic") or "").split("—")[0].strip()

    queries = []
    pm = re.search(r"^\s*PHOTOS:\s*(.+)$", html, re.M)
    if pm:
        queries = [q.strip() for q in pm.group(1).split("|") if q.strip()]
        html = (html[:pm.start()] + html[pm.end():]).strip()

    # 제목 URL 검사 (2026-08-31): Blogger는 제목으로 URL을 만드는데 한글은 슬러그로
    # 변환되지 않는다. 영문 토막이 없으면 /2026/08/3.html·blog-post_30.html 같은 무의미한
    # URL이 된다(실측: 공개 57편 중 26편). API는 커스텀 URL을 지원하지 않아 제목이 유일한 수단.
    # 원고 원문에서 영문 키워드를 찾아 제목 앞에 얹는다.
    if not re.search(r"[A-Za-z]{3,}", title):
        cand = re.findall(r"\b[A-Za-z][A-Za-z0-9]{2,}(?:[ -][A-Za-z0-9]+){0,2}\b", origin)
        SKIP = {"the", "and", "for", "with", "you", "your", "this", "that", "from", "has",
                "www", "http", "https", "com", "kr", "net", "org", "출처", "TITLE", "PHOTOS"}
        pick = next((c for c in cand if c.split()[0].lower() not in SKIP and len(c) >= 3), None)
        if pick:
            title = "%s: %s" % (pick, title)
            print("[make_blog] 제목에 영문 키워드 삽입 — URL 슬러그 확보: %s" % pick, flush=True)
        else:
            print("[make_blog] ⚠️ 제목·원고에 영문 키워드가 없다 — URL이 무의미해진다: %s"
                  % title[:40], flush=True)

    text_only = re.sub(r"<[^>]+>", "", html)
    if len(text_only) < MIN_CHARS:
        raise RuntimeError("생성 글이 너무 짧다(%d자) — 얇은 콘텐츠로 걸린다" % len(text_only))

    # 프롬프트로 막아도 모델이 되풀이하는 표현들을 여기서 걷어낸다 (decliche.py 주석)
    from decliche import clean, clean_text
    html = clean(html)
    title = clean_text(title)

    html = style_marks(html)
    html = boxed_summary(html)
    try:
        html = decorate(html, pick_images(meta, queries))
    except Exception as e:
        print("[make_blog] 이미지 처리 건너뜀:", str(e)[:120], flush=True)

    product = None
    if blog_link:
        from affiliate_pool import best
        from disclosure import DISCLOSURE
        url, name = best(origin)
        if url:
            product = {"name": name, "url": url}
            html += (
                '\n<p><a href="%s" target="_blank" rel="nofollow noopener">%s</a></p>\n'
                '<p><span style="color:#888;font-size:0.9em;">%s</span></p>'
                % (url, name, DISCLOSURE)
            )
    return {"title": title, "html": html,
            "new_numbers": fact_check(text_only, origin), "product": product}


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        sys.exit("사용: make_blog.py <원고.json> [--publish] [--out 파일]")
    with open(args[0], encoding="utf-8") as f:
        meta = json.load(f)
    if isinstance(meta, list):
        meta = meta[0] if meta else {}

    from blog_gate import judge
    ok, why = judge(meta)
    if not ok:
        sys.exit("⛔ 블로그 대상 아님 — %s" % why)
    print("게이트 통과:", why, flush=True)

    r = build(meta)
    print("제목:", r["title"])
    print("본문:", len(re.sub(r'<[^>]+>', '', r['html'])), "자")
    if r["product"]:
        print("쿠팡:", r["product"]["name"][:40])
    if r["new_numbers"]:
        print("⚠️ 원고에 없는 숫자 %d개 — 확인 필요: %s"
              % (len(r["new_numbers"]), ", ".join(r["new_numbers"][:12])))
    else:
        print("✓ 원고에 없는 숫자 없음")

    out = None
    if "--out" in sys.argv:
        i = sys.argv.index("--out")
        if i + 1 < len(sys.argv):
            out = sys.argv[i + 1]
    if out:
        with open(out, "w", encoding="utf-8") as f:
            f.write(r["html"])
        print("저장:", out)

    if "--publish" in sys.argv or "--draft" in sys.argv:
        from upload_blogger import publish
        res = publish(r["title"], r["html"], labels=["IT·테크"],
                      draft="--publish" not in sys.argv)
        print("%s: %s" % ("공개 발행" if res["status"] == "live" else "초안 저장",
                          res["url"] or res["id"]))


if __name__ == "__main__":
    main()
