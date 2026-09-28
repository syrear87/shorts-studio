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
5. **판매 유도 어법 금지** (2026-09-06 디렉터: "무조건 이거 사야해 유도하지 말고 테크 정보를
   전달하는 게 목적인 것처럼 보여야 함"): "무조건 사야" · "안 사면 손해" · "사야 합니다" ·
   "강추" · "필수템" · "품절 전에" · "꼭 사세요" 금지.
   대신 이렇게 쓴다 — "이런 게 있다" · "이럴 때 쓴다" · "고를 때 볼 것".
6. **대결 구도 금지 — 「A보다 B가 낫다」로 쓰지 마라** (2026-09-06 디렉터 지정):
   독자는 이미 A를 쓰고 있다. 그 선택을 틀렸다고 말하면 반박을 부른다.
   ✗ "클라우드 대신 SSD" → ✓ "클라우드를 쓰는데 용량이 모자라면 이런 대안도 있다".
   어느 쪽이 낫다는 **판정을 넣지 마라.** 조건("이럴 땐 이쪽")으로 쓴다.
   자가검증: 이 문장이 **누구의 선택을 틀렸다고 말하나** — 답이 나오면 그 사람이 반박 댓글이다.
7. **가격은 기준을 밝혀라.** 원고에 가격이 있으면 "○○ 기준 N원(YYYY-MM-DD 조회)"처럼
   **판매처와 조회 시점**을 함께 쓴다. 원고에 판매처·시점이 없으면 **가격을 결론이나 제목에
   쓰지 마라** — 본문에서 "원고 기준"이라고 밝히고 한 번만 언급한다.
   (2026-09-04 사고: 사양서 가격을 실거래처럼 썼다가 정정했다. 블로그 글은 검색에 오래 남아
   회수가 더 어렵다.)
8. **국내 미출시 제품이면 세 가지에 답하라**: ①직구 총액(관세·배송 포함) ②지금 국내에서 살 수
   있는 대안(없으면 "국내에 대체품 없음") ③국내 출시 전망("미정"도 답이다).
   원고에 없는 내용을 지어내지 말고, 없으면 "원고에 정보 없음"이라고 쓴다.

# 글 구조
{{STRUCTURE}}

**소제목(h2) 규칙 — 가장 중요하다.** 위의 역할 이름을 소제목으로 그대로 쓰지 마라.
소제목은 **그 절이 이 글에서 실제로 말하는 내용**을 문장으로 쓴다.
  ✗ "결론부터" · "정리" · "고를 때 확인할 것" · "장단점" · "특징"   (어느 글에나 붙는 라벨)
  ✓ "135g이라 자격증도 신고도 필요 없다" · "Qi2 인증이 없으면 15W가 안 나온다"
같은 소제목이 다른 글에도 붙을 수 있으면 잘못 쓴 것이다.
(2026-09-11 실측: 공개 94편 중 93편이 "결론부터", 91편이 "정리"로 시작해 검색엔진과
애드센스 심사에 **틀에 찍어낸 글**로 읽혔다.)
- 비교할 값이 둘 이상이면 `<table>`로 정리한다.

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


# ── 소재 유형별 글 골격 (2026-09-11) ─────────────────────────────────────
# 절의 **역할**만 정한다. 소제목 문구는 글마다 내용으로 쓴다(프롬프트의 소제목 규칙).
# 유형이 다르면 절 구성 자체가 달라야 사람이 쓴 블로그처럼 읽힌다.
STRUCTURES = {
    "compare": """- 도입 2~3문장: 독자가 고르다 막힌 지점을 짚는다.
- 첫 절: **먼저 답** — 어떤 조건이면 어느 쪽인지 한눈에. 목록 또는 표.
- 둘째 절: **갈리는 기준** — 무엇이 실제 차이를 만드는지, 표로.
- 셋째 절: **상황별 선택** — "이런 사람은 이쪽" 2~3가지.
- 넷째 절: **흔한 오해** — 사람들이 잘못 아는 것 하나.
- 끝: 2문장. 판정 대신 조건으로 닫는다.""",
    "fix": """- 도입 2~3문장: 어떤 증상이 나타나는지.
- 첫 절: **무슨 일이 벌어지는가** — 현상을 정확히.
- 둘째 절: **왜 그런가** — 원리·원인.
- 셋째 절: **해결** — 순서대로. 목록.
- 넷째 절: **그래도 안 되면** — 다음 단계 또는 한계.
- 끝: 1~2문장.""",
    "product": """- 도입 2~3문장: 이 물건이 어떤 상황에서 눈에 들어오는지.
- 첫 절: **핵심 한 가지** — 이 제품이 기존과 다른 딱 하나. 목록 3개 이내.
- 둘째 절: **어떤 사람한테 맞나** — 맞는 경우와 안 맞는 경우를 나란히.
- 셋째 절: **사기 전에 짚을 것** — 사양·호환·규정 중 실제로 걸리는 것.
- 넷째 절: **가격과 구매 경로** — 원고에 있는 값만. 미출시면 직구 총액·국내 대안·전망.
- 끝: 1~2문장.""",
    "guide": """- 도입 2~3문장: 이걸 왜 알아야 하는지.
- 첫 절: **먼저 답** — 핵심 순서 또는 기준. 목록.
- 둘째 절: **단계별로** — 따라 할 수 있게. 번호 목록.
- 셋째 절: **주의할 점** — 여기서 사람들이 막힌다.
- 끝: 1~2문장.""",
    "issue": """- 도입 2~3문장: 지금 무슨 일이 벌어졌는지.
- 첫 절: **핵심** — 무엇이 어떻게 됐나. 목록 3개 이내.
- 둘째 절: **배경** — 왜 지금 이런 게 나왔나.
- 셋째 절: **해보려면 / 나한테 어떤 의미인가** — 실제로 쓸 수 있는 정보.
- 넷째 절: **주의할 점** — 과장·한계.
- 끝: 1~2문장.""",
}
_COMPARE = ("vs", "VS", "비교", "차이", "뭐가 다른", "어떤 걸", "어느 게", "골라", "고를 때", "장단점")
_FIX = ("안 될 때", "안될 때", "오류", "해결", "고장", "느려", "발열", "먹통", "복구", "왜 안",
        "안 되는 이유", "안 되던 이유", "이유가 사라졌다")
_GUIDE = ("방법", "하는 법", "설정", "쓰는 법", "따라하기", "체크리스트", "총정리")


def article_kind(meta):
    """소재 유형 → STRUCTURES 키."""
    from blog_gate import card_tags
    text = " ".join(str((meta or {}).get(k) or "") for k in ("topic", "caption"))[:400]
    tags = card_tags(meta)
    if any(w in text for w in _COMPARE):
        return "compare"
    if any(w in text for w in _FIX):
        return "fix"
    if "구매가능" in tags or "직구" in text or "국내 미출시" in text:
        return "product"
    if any(w in text for w in _GUIDE):
        return "guide"
    return "issue"


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
    """첫 h2 절을 눈에 띄는 상자로 — 스캔하는 독자가 답을 먼저 본다.
    종전엔 '결론부터'라는 제목을 찾았는데, 소제목을 글마다 다르게 쓰면서(2026-09-11)
    제목이 아니라 **위치**로 잡는다 — 모든 유형이 첫 절에 답을 둔다."""
    m = re.search(r"(<h2[^>]*>.*?</h2>)(.*?)(?=<h2|$)", html, re.S)
    if not m:
        return html
    inner = m.group(2).strip()
    if not inner:
        return html
    return html[:m.start()] + SUMMARY_BOX + m.group(1) + inner + "</div>" + html[m.end():]


# 특정 제품 글에 다른 제품의 스톡 사진을 넣으면 독자는 그게 그 제품인 줄 안다 — 실물이 없으면
# 차라리 이미지를 넣지 않는다. 종전엔 [구매가능] 태그로 이걸 판정했는데(PRODUCT_TAGS), 그러면
# 「멀티탭 서지보호」「NFC 태그 스티커」같은 **카테고리 소재**까지 제품 글로 묶여 이미지 없이
# 나갔다 (2026-09-13 디렉터: "이미지도 없고"). 멀티탭 스톡 사진은 아무도 안 속는다.
# 이제 topic 앞머리(— 이전)에 고유명사·모델명이 있을 때만 특정 제품으로 본다.
# 캡션까지 훑지 않는 이유: 경쟁사 언급(PopSocket·Brother)·규격명(NTAG215)에 걸려 오탐한다.
PRODUCT_TAGS = {"구매가능", "신제품", "루머", "펀딩"}   # (하위 호환 — 다른 곳에서 참조)
_ACRO = {"USB", "NFC", "LED", "HDMI", "GAN", "AI", "TV", "PC", "OLED", "LCD", "UV", "CO2", "QI",
         "QI2", "SSD", "HDD", "SD", "IPX", "ANC", "BT", "IR", "GPS", "CD", "DVD", "EV", "PD",
         "IOS", "IP", "MICROSD", "USB-C", "TYPE-C", "LTE", "5G", "4K", "8K", "3D"}
_PROPER = re.compile(r"\b[A-Z][a-z]{2,}[A-Za-z]*\b")           # Niimbot, Lockin, Neo, Xteink
_MODEL = re.compile(r"\b[A-Za-z]{1,6}\d{1,4}[A-Za-z]{0,3}\b")   # D110, V7, X3, AP30, S50


def specific_product(meta):
    """topic 앞머리에 특정 제품을 가리키는 낱말이 있으면 그 낱말, 없으면 None(카테고리 소재)."""
    head = re.sub(r"\[[^\]]*\]", "", str((meta or {}).get("topic") or "").split("—")[0])
    for m in _PROPER.findall(head):
        if m.upper() not in _ACRO:
            return m
    for m in _MODEL.findall(head):
        if m.upper() not in _ACRO:
            return m
    return None


def pick_images(meta, queries):
    """이 글에 넣을 사진 [(url, 크레딧), ...].

    ① 원고에 **실제 제품 사진**이 있으면 그것을 쓴다 (카드가 이미 공식 이미지를 확보해 둔다).
    ② 없고 **특정 제품** 글이면 → 넣지 않는다. 스톡으로 대체하면 오도다.
    ③ 없고 카테고리·일반 정보 글이면 → Pexels 가로 사진. 크레딧에 「참고 이미지」를 붙여
       실물이 아님을 밝힌다.
    """
    from blog_media import product_shots, photos_for
    real = product_shots(meta)
    if real:
        return real
    sp = specific_product(meta)
    if sp:
        print("[make_blog] 특정 제품 글(%s)인데 실물 사진이 없다 — 이미지 없이 간다" % sp, flush=True)
        return []
    got = photos_for(queries or [str((meta or {}).get("topic") or "")[:60]], count=3)
    return [(u, "참고 이미지 · " + (c or "")) for u, c in got]


def build(meta, blog_link=True):
    """원고 dict → {title, html, new_numbers, product}."""
    origin = source_text(meta)
    if not origin.strip():
        raise ValueError("원고에서 텍스트를 못 찾았다")
    kind = article_kind(meta)
    print("[make_blog] 글 유형: %s" % kind, flush=True)
    raw = _gemini(PROMPT.replace("{{ORIGIN}}", origin)
                        .replace("{{STRUCTURE}}", STRUCTURES[kind]))

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
    # 후처리는 여기서 — CLI(main)뿐 아니라 blog_autogen(운영 경로)도 build()를 쓴다.
    # 2026-09-06 감사: polish가 main()에만 있어 실제 발행되는 글엔 적용되지 않고 있었다.
    from blog_polish import polish
    html, labels = polish(html, title, tags=(meta or {}).get("tags") or ())
    # 글끼리 잇는 링크 (2026-09-28) — 색인 0의 원인이 크롤 우선순위로 판정됐다(blog_related 주석)
    from blog_related import append as _related
    html = _related(html, title, labels)
    return {"title": title, "html": html, "labels": labels,
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
        # 후처리 (2026-09-06): 마크다운 잔재를 HTML로 내리고, 빈 alt를 채우고,
        # 제품군 라벨을 붙인다. 공개 86편 전수에서 마크다운 7편·alt 공백 75편·
        # 라벨 없음 54편이 나왔다 — 발행 직전 한 곳에서 정리한다.
        print("후처리: 라벨 %s" % " / ".join(r["labels"]), flush=True)
        res = publish(r["title"], r["html"], labels=r["labels"],
                      draft="--publish" not in sys.argv)
        print("%s: %s" % ("공개 발행" if res["status"] == "live" else "초안 저장",
                          res["url"] or res["id"]))


if __name__ == "__main__":
    main()
