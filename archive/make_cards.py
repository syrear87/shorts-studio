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
import re
import sys

from PIL import Image, ImageDraw, ImageFont

# PIL+AppleSDGothicNeo는 컬러 이모지를 못 그린다(□ 깨짐) — 카드 텍스트에서 기계 제거 (2026-08-20 디렉터 지적)
_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿️‍]")

def _clean(t):
    return _EMOJI.sub("", t or "").rstrip()

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
W, H = 1080, 1350
# 로고(profile_1080.png) 배경 실측: 모서리 (11,16,32) ~ (23,27,53) — 카드 배경을 로고와 통일 (2026-08-05 디렉터)
NAVY, NAVY_HI = (11, 16, 32), (23, 27, 53)
ACCENT = (255, 182, 39)
TEXT, DIM = (245, 246, 250), (176, 184, 202)
FP = "/System/Library/Fonts/AppleSDGothicNeo.ttc"
WEIGHTS = {"r": 0, "m": 2, "sb": 4, "b": 6}


def font(sz, w="r"):
    return ImageFont.truetype(FP, sz, index=WEIGHTS[w])


def base(page, total, img=None):
    if img:
        # 풀블리드: 이미지를 카드 전체에 cover-crop, 상·하 어두운 스크림으로 텍스트 가독 확보 (2026-08-20 디렉터: "꽉 찬 이미지")
        pi = Image.open(os.path.join(ROOT, img)).convert("RGB")
        sc = max(W / pi.width, H / pi.height)
        pi = pi.resize((int(pi.width * sc) + 1, int(pi.height * sc) + 1))
        x0, y0 = (pi.width - W) // 2, (pi.height - H) // 2
        im = pi.crop((x0, y0, x0 + W, y0 + H))
        ov = Image.new("RGB", (W, H), NAVY)
        mask = Image.new("L", (1, H))
        mp = []
        for y in range(H):
            t = y / H
            if t < 0.42:          # 상단: 배지·제목 영역 — 진하게
                a = int(235 - t / 0.42 * 130)
            elif t < 0.62:        # 중단: 이미지 살리기
                a = 90
            else:                 # 하단: 본문·크레딧 — 다시 진하게
                a = int(90 + (t - 0.62) / 0.38 * 140)
            mp.append(a)
        mask.putdata(mp)
        im.paste(ov, (0, 0), mask.resize((W, H)))
        d = ImageDraw.Draw(im)
    else:
        im = Image.new("RGB", (W, H), NAVY)
        d = ImageDraw.Draw(im)
        for y in range(H):
            t = y / H
            c = tuple(int(NAVY_HI[i] * (1 - t) + NAVY[i] * t) for i in range(3))
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
        for k in ("title", "body", "sub", "badge", "credit"):
            if c.get(k):
                c[k] = _clean(c[k])
        im, d = base(i, total, img=c.get("img"))
        kind = c.get("kind", "fact")
        # 배지 (2026-08-19 테크 카드 라인: 루머는 카드에 박는다 — "루머 · 블룸버그" / "공식" / "컨셉 이미지")
        if c.get("badge"):
            bf = font(34, "b")
            bw = d.textlength(c["badge"], font=bf)
            d.rounded_rectangle([64, 52, 64 + bw + 48, 116], radius=32,
                                outline=ACCENT, width=3)
            d.text((88, 62), c["badge"], font=bf, fill=ACCENT)
        # 출처 크레딧 (이미지·정보 출처, 하단 고정)
        if c.get("credit"):
            d.text((64, H - 152), c["credit"], font=font(28, "m"), fill=DIM)
        max_y = H - 140   # 페이지 카운터 상단 여백
        t_hl, b_hl = c.get("title_hl", []), c.get("body_hl", [])
        last_y = [0]

        def P(*a, **kw):
            y_ = para(*a, **kw)
            last_y[0] = max(last_y[0], y_)
            return y_

        try:
            if kind == "hook":
                y = P(d, c["title"], font(86, "b"), 80, 400, W - 160, hl=t_hl, lh=1.32)
                if c.get("body"):
                    P(d, c["body"], font(48, "sb"), 80, y + 100, W - 160, color=TEXT, hl=b_hl)
            elif kind == "end":
                y = P(d, c["title"], font(64, "b"), 80, 410, W - 160, hl=t_hl, lh=1.38)
                if c.get("body"):
                    y = P(d, c["body"], font(50, "sb"), 80, y + 56, W - 180, color=TEXT, hl=b_hl)
                if c.get("sub"):
                    P(d, c["sub"], font(46, "b"), 80, max(y + 90, 800), W - 160, color=ACCENT)
            else:  # fact
                y = P(d, c["title"], font(66, "b"), 80, 280, W - 180, hl=t_hl)
                if c.get("body"):
                    y = P(d, c["body"], font(52, "sb"), 80, y + 64, W - 180, color=TEXT, hl=b_hl)
                if c.get("sub"):
                    P(d, c["sub"], font(46, "m"), 80, y + 48, W - 180, color=DIM)
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
