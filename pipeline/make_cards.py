#!/usr/bin/env python3
# 지식 카드(인스타 캐러셀) 렌더러 — 2026-08-05 디렉터 승인 스타일 v2
#  · 3장 이하 (훅 → 핵심 → 마무리+저장 유도) · 볼드 혼용 · 로고 우상단 · 페이지 카운터
#  · 소재 분리 원칙: 릴스와 겹치지 않는 전용 소재(유래·개념·달력 지식 등 저장형)만 쓴다
# 입력 JSON:
#  {"topic": "...", "caption": "인스타 캡션 전문",
#   "cards": [{"kind": "hook|fact|end", "title": "...", "title_hl": ["강조어"],
#              "body": "...", "body_hl": ["강조어"], "sub": "하단 보조문(선택)"}]}
# 사용: .venv/bin/python3 pipeline/make_cards.py content/cards-2026-08-14.json
#  → out/cards/<이름>/card_N.png
import json
import os
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
W, H = 1080, 1350
NAVY, NAVY_HI = (10, 15, 30), (38, 54, 92)
ACCENT = (255, 182, 39)
TEXT, DIM = (245, 246, 250), (176, 184, 202)
FP = "/System/Library/Fonts/AppleSDGothicNeo.ttc"
WEIGHTS = {"r": 0, "m": 2, "sb": 4, "b": 6}


def font(sz, w="r"):
    return ImageFont.truetype(FP, sz, index=WEIGHTS[w])


def base(page, total):
    im = Image.new("RGB", (W, H), NAVY)
    d = ImageDraw.Draw(im)
    for y in range(H):
        t = y / H
        c = tuple(int(NAVY_HI[i] * (1 - t) * 0.9 + NAVY[i] * (0.1 + t * 0.9)) for i in range(3))
        d.line([(0, y), (W, y)], fill=c)
    logo = Image.open(os.path.join(ROOT, "assets", "brand", "profile_1080.png")).convert("RGBA").resize((116, 116))
    mask = Image.new("L", (464, 464), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, 463, 463], fill=255)
    logo.putalpha(mask.resize((116, 116)))
    im.paste(logo, (W - 156, 44), logo)
    d = ImageDraw.Draw(im)
    d.text((64, H - 96), "%d / %d" % (page, total), font=font(30, "m"), fill=DIM)
    return im, d


def wrap(d, text, f, max_w):
    words, lines, cur = text.split(), [], ""
    for w_ in words:
        t = (cur + " " + w_).strip()
        if d.textlength(t, font=f) <= max_w:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w_
            if d.textlength(w_, font=f) > max_w:
                # 한 어절이 폭 초과 — 렌더하면 우측이 잘린다. 게이트에서 기각되도록 표식.
                raise OverflowError("어절 '%s'가 카드 폭을 초과" % w_)
    if cur:
        lines.append(cur)
    return lines


def para(d, text, f, x, y0, max_w, color=TEXT, lh=1.42, hl=()):
    y = y0
    for ln in wrap(d, text, f, max_w):
        cx = x
        for w_ in ln.split(" "):
            core = w_.strip("'\"()[].,!?…·—")
            col = ACCENT if any(h and (core == h or core.startswith(h) or h in w_ and len(h) >= max(2, len(core) - 2))
                                for h in hl) else color
            d.text((cx, y), w_, font=f, fill=col)
            cx += d.textlength(w_ + " ", font=f)
        y += int(f.size * lh)
    return y


def render(script_path):
    s = json.load(open(script_path, encoding="utf-8"))
    cards = s["cards"]
    if not (2 <= len(cards) <= 3):
        sys.exit("기각: 카드 %d장 — 2~3장만 허용 (2026-08-05 디렉터: 3장 이하)" % len(cards))
    # 영구금지 소재 기계 게이트 (2026-08-05 점검: 프롬프트 수동 확인은 3회 실패로 기계화된 이력)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        import check_topic
        all_text = " ".join([s.get("topic", ""), s.get("caption", "")] +
                            [str(c.get(k, "")) for c in cards for k in ("title", "body", "sub")])
        hits = check_topic.check_text(all_text)
        if hits:
            sys.exit("기각: 영구금지 키워드 일치(%s) — content/REJECTED.md 참조" % ", ".join(hits))
    except SystemExit:
        raise
    except Exception as e:
        print("check_topic 게이트 실행 불가(%s) — REJECTED.md 수동 확인 필요" % e, flush=True)
    # 캡션 게이트 (2026-08-05 점검)
    cap = s.get("caption", "")
    if cap:
        if any(l.strip().startswith("태그:") for l in cap.splitlines()):
            sys.exit("기각: 캡션에 '태그:' 줄 포함 — 인스타 캡션에는 금지")
        n_tags = cap.count("#")
        if not (3 <= n_tags <= 7):
            sys.exit("기각: 캡션 해시태그 %d개 — 3~7개(권장 5) 범위 밖" % n_tags)
        if len(cap) > 2200:
            sys.exit("기각: 캡션 %d자 — 2200자 초과" % len(cap))
    base_name = os.path.splitext(os.path.basename(script_path))[0]
    out_dir = os.path.join(ROOT, "out", "cards", base_name)
    os.makedirs(out_dir, exist_ok=True)
    total = len(cards)
    paths = []
    for i, c in enumerate(cards, 1):
        im, d = base(i, total)
        kind = c.get("kind", "fact")
        max_y = H - 140   # 페이지 카운터 상단 여백
        t_hl, b_hl = c.get("title_hl", []), c.get("body_hl", [])
        last_y = [0]

        def P(*a, **kw):
            y_ = para(*a, **kw)
            last_y[0] = max(last_y[0], y_)
            return y_

        try:
            if kind == "hook":
                y = P(d, c["title"], font(76, "b"), 80, 430, W - 200, hl=t_hl, lh=1.35)
                if c.get("body"):
                    P(d, c["body"], font(40, "m"), 80, y + 120, W - 200, color=DIM, hl=b_hl)
            elif kind == "end":
                y = P(d, c["title"], font(56, "b"), 80, 430, W - 200, hl=t_hl, lh=1.4)
                if c.get("body"):
                    y = P(d, c["body"], font(44, "m"), 80, y + 60, W - 220, color=DIM, hl=b_hl)
                if c.get("sub"):
                    P(d, c["sub"], font(42, "m"), 80, max(y + 90, 780), W - 200, color=ACCENT)
            else:  # fact
                y = P(d, c["title"], font(58, "b"), 80, 300, W - 220, hl=t_hl)
                if c.get("body"):
                    y = P(d, c["body"], font(46, "m"), 80, y + 70, W - 220, hl=b_hl)
                if c.get("sub"):
                    P(d, c["sub"], font(44, "r"), 80, y + 50, W - 220, color=DIM)
        except OverflowError as e:
            sys.exit("기각: 카드 %d 가로 폭 초과(%s) — 어절을 나눠라" % (i, e))
        p = os.path.join(out_dir, "card_%d.png" % i)
        im.save(p)
        paths.append(p)
        if last_y[0] > max_y:
            sys.exit("기각: 카드 %d 텍스트가 하단 초과(y=%d > %d) — 본문을 줄여라" % (i, last_y[0], max_y))
    print("완료: %d장 → %s" % (total, out_dir))
    return paths


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        sys.exit("사용: make_cards.py <cards.json> [--publish]")
    paths = render(args[0])
    if "--publish" in sys.argv:
        s = json.load(open(args[0], encoding="utf-8"))
        if not s.get("caption"):
            sys.exit("기각: caption 없음 — 게시 불가")
        from upload_instagram import publish_carousel
        publish_carousel(paths, s["caption"])
