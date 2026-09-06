#!/usr/bin/env python3
"""훅 채점 — 도달을 가르는 두 축이 훅에 있는지 본다. (2026-09-06 실측으로 신설)

무엇을 재나 (스레드 112글 전수, 24h 이상 익은 것만):
  ① **아는 대상** — 독자가 이미 쓰고 있거나 아는 것이 훅에 나오나 (아이폰·삼성·HDMI·CD…)
  ② **변화** — 그것이 **달라졌다**는 사건이 훅에 있나 (깨졌다·바뀐다·사라졌다·처음·N년 만에)

실측 (조회 중앙값):
  아는대상 O + 변화 O   n=8   **12,390**
  아는대상 O + 변화 X   n=27       685
  아는대상 X + 변화 O   n=9        315
  아는대상 X + 변화 X   n=68       322
**둘 다 있어야 터진다.** 변화만 있으면 효과가 없다 — 모르는 물건이 "바뀌었다"고 하면
무엇이 바뀐 건지 알 수가 없기 때문이다. 곱셈이지 덧셈이 아니다.

1,000회 돌파율: 아는대상 O 37% / X 12% · 변화 O 53% / X 14%
**소개형 술어("된다"·"생긴다"·"있다")로 끝나는 훅은 0/12 = 0%다.**

⚠️ **이 도구는 상단을 예측하지 하단을 가르지 못한다.** 회귀에서 ◎(strong)는 4/4 정확했지만
△(weak) 구간은 12회부터 685회까지 퍼진다 — 한 축만 있는 훅의 성패는 다른 요인이 정한다.
그러니 "△니까 괜찮다"로 읽지 말고 **"◎로 올릴 수 있나"만 물어라.**

⚠️ 이건 게이트가 아니라 **경고**다. 없는 변화를 지어내라는 뜻이 절대 아니다 —
2026-09-04 사고가 그렇게 났다. 재료가 본문에 있는데 훅으로 안 올린 경우를 잡는 것이다.
실제로 9/6 급식기 카드는 본문 6번에 "기존엔 목걸이가 필요했는데 이건 없이 된다"는
변화가 있었는데 훅은 "급식기가 고양이 얼굴을 구분한다"였다.
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ① 아는 대상 — 브랜드만이 아니다. **독자가 이미 갖고 있거나 써본 것**이면 된다.
KNOWN = (
    # 브랜드·서비스
    "아이폰", "애플", "삼성", "갤럭시", "아이패드", "맥북", "맥 미니", "맥미니", "에어팟",
    "아이클라우드", "챗GPT", "ChatGPT", "제미나이", "구글", "닌텐도", "스위치", "플스",
    "플레이스테이션", "엑스박스", "테슬라", "다이슨", "카카오", "네이버", "유튜브",
    "인스타", "넷플릭스", "소니", "LG", "밸브", "스팀", "샤오미", "안드로이드", "윈도우",
    # 누구나 쓰는 물건·규격
    "무선이어폰", "이어폰", "헤드폰", "헤드셋", "무선 헤드폰", "스피커", "마우스패드",
    "에어컨", "선풍기", "공기청정기", "밥솥", "전자레인지", "공유기", "와이파이", "WiFi", "HDMI", "USB", "C타입",
    "충전기", "보조배터리", "케이블", "리모컨", "TV", "냉장고", "세탁기", "청소기",
    "노트북", "모니터", "키보드", "마우스", "카메라", "CD", "USB메모리", "SD카드",
    "블루투스", "콘센트", "멀티탭", "도어락", "택배", "지하철", "고속도로",
)
# ② 변화 — 상태 서술이 아니라 **사건**
CHANGE = (
    "깨졌", "깨진", "바뀝", "바뀐", "바뀌었", "웁니다", "못 박", "나왔다", "돌아왔",
    "이겼", "졌다", "끝났", "끝난", "사라", "멈췄", "멈춘", "뒤집", "무너", "막혔", "막고",
    "열렸", "풀어", "처음", "드디어", "마침내", "만에", "이제", "더는", "안 된다",
    "없어졌", "필요 없", "안 팔", "단종", "중단", "복귀", "부활",
)
# 소개형 술어 — 1,000회 돌파 0/12
INTRO_TAIL = ("된다", "됩니다", "생긴다", "생깁니다", "있다", "있습니다", "나온다", "나옵니다")


def _has(text, words):
    return [w for w in words if w in text]


def hook_of(d):
    """훅 = threads_text 첫 줄(스레드에서 실제로 보이는 한 줄)."""
    t = (d.get("threads_text") or d.get("caption") or "").strip()
    return t.split("\n")[0] if t else ""


def body_of(d):
    parts = [d.get("threads_text") or "", d.get("caption") or "", d.get("topic") or ""]
    for c in d.get("cards") or []:
        parts += [str(c.get(k, "")) for k in ("title", "body", "sub")]
    return "\n".join(parts)


def score(d):
    """(등급, 진단들). 등급: strong | weak | flat"""
    hook, body = hook_of(d), body_of(d)
    k, c = _has(hook, KNOWN), _has(hook, CHANGE)
    out = []
    if k:
        out.append("✓ 아는 대상: %s" % ", ".join(k[:3]))
    else:
        out.append("✗ 아는 대상 없음 — 독자가 이미 아는 것에 걸어라(브랜드가 아니어도 된다: "
                   "CD·HDMI·리모컨·공유기처럼 써본 물건이면 된다)")
    if c:
        out.append("✓ 변화: %s" % ", ".join(c[:3]))
    else:
        out.append("✗ 변화 없음 — '무엇이 달라졌나'가 훅에 없다")
        # 본문에 재료가 있는데 훅으로 안 올린 경우를 짚어준다
        bc = _has(body, CHANGE)
        if bc:
            for line in body.splitlines():
                if any(w in line for w in bc) and line.strip() != hook:
                    out.append("  → 본문에 재료가 있다: %r" % line.strip()[:70])
                    break
    tail = _has(hook, INTRO_TAIL)
    if tail and not c:
        out.append("⚠ 소개형 술어(%s)로 끝난다 — 실측 1,000회 돌파 0/12" % tail[0])
    grade = "strong" if (k and c) else ("weak" if (k or c) else "flat")
    return grade, out


MSG = {"strong": "아는 대상 × 변화 — 실측 중앙값 12,390 구간",
       "weak": "한 축만 있다 — 실측 중앙값 315~685 구간",
       "flat": "두 축 다 없다 — 실측 중앙값 322 구간"}


def main(argv):
    paths = argv[1:]
    if not paths:
        print("사용법: hook_check.py <cards-*.json> [...]")
        return 2
    for p in paths:
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception as e:
            print("[hook] %s 읽기 실패: %s" % (os.path.basename(p), e))
            continue
        g, notes = score(d)
        mark = {"strong": "◎", "weak": "△", "flat": "▽"}[g]
        print("[hook] %s %s — %s" % (mark, os.path.basename(p), MSG[g]))
        print("       훅: %s" % hook_of(d)[:70])
        for n in notes:
            print("       " + n)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
