#!/usr/bin/env python3
"""블로그 글 후처리 — 기계가 쓴 티를 지우고, 검색이 읽을 것을 채운다.

왜 있는가 (2026-09-06 실측, 공개 86편 전수):
  · **마크다운 노출 7편** — Gemini가 뱉은 `**볼드**`가 HTML로 안 바뀌고 그대로 박혔다.
    독자 눈에 별표가 보인다. 사람이 쓴 글에는 없는 자국이라 "자동 생성" 신호가 된다.
  · **alt 공백 75편** — `<img alt="">`. 이미지 검색에 안 잡히고, 화면낭독기는 건너뛴다.
    블로그 총조회 53에 홈만 색인된 상태에서 색인 신호를 버리고 있었다.
  · **라벨 없음 54편** — 라벨이 'IT·테크' 하나뿐이라 분류가 없는 것과 같았다.
    라벨은 Blogger에서 내부링크를 만드는 유일한 수단인데(내부링크 0이었다),
    한 라벨에 전부 몰아넣으면 링크 구조가 안 생긴다.

신규 글(make_blog)과 기존 글(blog_backfill) **양쪽이 이 파일 하나를 쓴다** —
후처리가 두 벌이면 한쪽만 고쳐지는 걸 오늘 프롬프트에서 이미 겪었다.
"""
import re

STRONG_STYLE = "color:#1a4fa0;"

# 제품군 라벨 — Blogger에서 라벨은 내부링크를 만드는 유일한 수단이다.
# 8개로 끊었다: 너무 잘게 나누면 라벨당 글이 1~2편이라 링크가 안 생기고,
# 하나로 몰면 지금처럼 분류가 없는 것과 같다.
LABELS = (
    ("모바일·웨어러블", ("갤럭시", "아이폰", "폰", "스마트폰", "워치", "버즈", "이어폰", "헤드폰",
                    "에어팟", "태블릿", "아이패드", "밴드", "스마트워치", "글래스",
                    "스마트링", "반지", "픽셀")),
    ("PC·주변기기", ("노트북", "SSD", "HDD", "메모리", "RAM", "DRAM", "키보드", "마우스", "모니터",
                  "그래픽카드", "GPU", "CPU", "맥북", "아이맥", "iMac", "데스크탑", "microSD",
                  "USB", "도킹", "공유기", "WiFi", "와이파이", "라우터", "NAS")),
    ("게임기·게임", ("스위치", "닌텐도", "플레이스테이션", "PS5", "엑스박스", "스팀덱", "게임기",
                 "레트로", "콘솔", "게임패드", "포켓몬")),
    ("스마트홈·로봇", ("스마트홈", "로봇", "청소기", "공기청정기", "조명", "전구", "도어락",
                  "냉장고", "세탁기", "에어컨", "리모컨", "고양이 화장실", "펫", "외골격",
                  "자물쇠", "잠금", "보안 카메라", "홈캠", "창문형")),
    ("영상·오디오", ("프로젝터", "TV", "스피커", "사운드바", "카메라", "캠", "액션캠", "짐벌",
                 "마이크", "레이저", "빔", "헤드셋")),
    ("모빌리티", ("드론", "전기차", "자율주행", "로보택시", "자전거", "킥보드", "스쿠터",
               "테슬라", "웨이모", "블랙박스")),
    # ⚠️ 여기 낱말은 좁게 유지하라. "구글"·"앱"·"업데이트"를 넣었더니 폰 글마다
    # AI 라벨이 붙었다(2026-09-06 실측). 라벨은 주제를 말해야지 등장 낱말을 말하면 안 된다.
    ("AI·소프트웨어", ("인공지능", "챗GPT", "ChatGPT", "제미나이", "Gemini", "클로드",
                   "Claude", "LLM", "생성형", "머신러닝")),
    ("충전·전원", ("보조배터리", "충전기", "충전", "배터리", "케이블", "어댑터", "파워뱅크")),
)
BASE_LABEL = "IT·테크"


def demote_markdown(html):
    """Gemini가 남긴 마크다운을 HTML로 내린다.

    실측상 새는 건 `**볼드**` 하나뿐이었다(86편 전수). 다른 문법은 안 나왔으므로
    넓게 잡지 않는다 — 정규식이 넓으면 본문의 별표(곱셈·각주)까지 먹는다.
    """
    # 같은 줄에 짝 없는 ** 둘(각주·거듭제곱)이 있으면 엉뚱하게 묶인다 — 공백으로 시작·끝나는
    # 구간은 볼드가 아니다(마크다운 규칙)
    return re.sub(r"\*\*(?!\s)([^*\n]{1,120}?)(?<!\s)\*\*",
                  '<strong style="%s">\\1</strong>' % STRONG_STYLE, html)


def _subject(title):
    """제목에서 이미지 alt로 쓸 주어를 뽑는다 — 'Brand Model: 설명' 꼴이 많다."""
    # 공백 없는 하이픈은 모델명이다 — "USB-C 케이블"이 "USB"로 잘렸다(2026-09-06 감사)
    t = re.split(r"\s*[:—–]\s*|\s-\s", title.strip())[0].strip()
    if len(t) < 3 or len(t) > 40:
        t = title.strip()[:40]
    return t


def fill_alt(html, title, credit_as_alt=True):
    """빈 alt를 채운다. 캡션(출처)이 있으면 '제목 주어 — 출처' 꼴로.

    alt는 이미지 검색의 유일한 단서다. 비워두면 그 이미지는 검색에 존재하지 않는다.
    다만 **거짓을 쓰면 안 된다** — 스톡 사진에 제품명을 박으면 그 사진이 그 제품인 줄
    읽힌다. 그래서 캡션에 적힌 출처를 함께 남긴다.
    """
    subj = _subject(title)

    def one(m):
        whole = m.group(0)
        tail = html[m.end():m.end() + 400]
        cred = ""
        c = re.search(r"<figcaption[^>]*>(.*?)</figcaption>", tail, re.S)
        if c and credit_as_alt:
            cred = re.sub(r"<[^>]+>", "", c.group(1)).strip()[:40]
        # 스톡 사진에 제품명을 박으면 그 사진이 그 제품인 줄 읽힌다 — 일반형으로 쓴다.
        if cred and re.search(r"pexels|unsplash|픽사베이|pixabay", cred, re.I):
            alt = "%s 관련 이미지 — %s" % (subj, cred)
        else:
            alt = "%s — %s" % (subj, cred) if cred else subj
        alt = alt.replace('"', "'")
        return whole.replace('alt=""', 'alt="%s"' % alt)

    return re.sub(r'<img[^>]*alt=""[^>]*>', one, html)


def pick_labels(title, text="", tags=()):
    """제품군 라벨을 고른다. 기본 라벨 + 제품군 최대 2개.

    **제목이 먼저다.** 본문 전체를 세면 어떤 기기 글이든 "배터리"·"충전"을 스치므로
    라벨이 과배정된다(실측: 본문 기준으로는 86편 중 34편이 충전·전원이었다 —
    실제로 충전기가 주제인 글은 그보다 훨씬 적다). 본문은 제목에서 아무것도
    못 건졌을 때만 본다.
    """
    tag_blob = " ".join([title or "", " ".join(tags or ())])

    def _has(kw, blob):
        # 영문 낱말은 경계로 맞춘다 — "AI"가 "AINOTE"에 걸려 엉뚱한 라벨이 붙었다.
        if re.fullmatch(r"[A-Za-z0-9 ]+", kw):
            return re.search(r"(?<![A-Za-z])%s(?![A-Za-z])" % re.escape(kw), blob) is not None
        return kw in blob

    def score(blob):
        hits = []
        for name, kws in LABELS:
            n = sum(1 for k in kws if _has(k, blob))
            if n:
                hits.append((n, name))
        hits.sort(reverse=True)
        if not hits:
            return []
        # 1등만 쓴다. 2등은 **점수가 같을 때만** — 라벨이 둘씩 붙으면
        # 내부링크가 흐려지고 분류가 아니라 태그 구름이 된다.
        out = [hits[0][1]]
        if len(hits) > 1 and hits[1][0] == hits[0][0]:
            out.append(hits[1][1])
        return out

    picked = score(tag_blob) or score(text or "")
    return [BASE_LABEL] + picked


def polish(html, title, text="", tags=()):
    """신규·기존 공통 후처리. (html, labels)"""
    h = demote_markdown(html)
    h = fill_alt(h, title)
    return h, pick_labels(title, text or re.sub(r"<[^>]+>", " ", h), tags)
