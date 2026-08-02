#!/usr/bin/env python3
"""축구 골 장면 재현 그래픽 (2026-08-02 신설).

실제 중계 화면은 저작권 때문에 쓸 수 없으므로, 골 장면을 우리가 직접 그린다.
경기장 도면 + 패스·턴·슈팅 궤적 + 공 애니메이션. 저작권·비용 0.

content json의 씬에 "pitch" 스펙을 넣으면 렌더러가 이 모듈을 호출한다:

  "pitch": {
    "pass":  {"from": [0.14, 0.72], "to": [0.40, 0.60], "label": "부앙가"},
    "turn":  {"at": [0.40, 0.60], "label": "180° 턴"},
    "shot":  {"from": [0.40, 0.60], "to": [0.90, 0.46], "curve": -0.16, "label": "오른발"},
    "phase": [0.0, 0.45, 0.62, 1.0]      # 패스시작·턴시작·슛시작·종료 (씬 진행률 0~1)
  }

좌표는 그래픽 박스 기준 0~1 정규화. x는 왼쪽→오른쪽(공격 방향), y는 위→아래.
"""
import math

ACCENT = (255, 182, 39)
LINE = (235, 240, 250)
GRASS = (30, 62, 44)


def _lerp(a, b, t):
    return a + (b - a) * t


def _bez(p0, p1, p2, t):
    """2차 베지어 — 슈팅 궤적의 휘어짐 표현."""
    x = (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t ** 2 * p2[0]
    y = (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t ** 2 * p2[1]
    return x, y


def _ctrl(a, b, curve):
    """시작·끝점과 휘어짐 계수로 베지어 제어점 산출 (수직 방향으로 밀어냄)."""
    mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
    dx, dy = b[0] - a[0], b[1] - a[1]
    return mx - dy * curve, my + dx * curve


def _dashed(d, pts, color, width, dash=16, gap=12):
    """점선 폴리라인 — 패스 표현."""
    acc, on = 0.0, True
    for i in range(len(pts) - 1):
        (x1, y1), (x2, y2) = pts[i], pts[i + 1]
        seg = math.hypot(x2 - x1, y2 - y1)
        if seg == 0:
            continue
        pos = 0.0
        while pos < seg:
            step = min((dash if on else gap) - acc, seg - pos)
            if on:
                s = pos / seg
                e = (pos + step) / seg
                d.line([(_lerp(x1, x2, s), _lerp(y1, y2, s)),
                        (_lerp(x1, x2, e), _lerp(y1, y2, e))], fill=color, width=width)
            pos += step
            acc += step
            if acc >= (dash if on else gap):
                on, acc = not on, 0.0


def _arrow(d, tip, ang, color, size=18):
    for da in (2.5, -2.5):
        d.line([tip, (tip[0] - size * math.cos(ang + da), tip[1] - size * math.sin(ang + da))],
               fill=color, width=6)


def draw_pitch(im, box, spec, progress, font=None):
    """im 위 box=(x0,y0,x1,y1) 영역에 골 장면 그래픽을 그린다.
    progress: 해당 씬 내 진행률 0~1."""
    from PIL import ImageDraw
    d = ImageDraw.Draw(im, "RGBA")
    x0, y0, x1, y1 = box
    bw, bh = x1 - x0, y1 - y0

    def P(p):
        return (x0 + p[0] * bw, y0 + p[1] * bh)

    # --- 경기장 배경·라인 (공격 진영 확대 뷰) ---
    # fill을 거의 불투명하게 — 반투명이면 뒤 배경영상이 비쳐 도면이 안 읽힌다(2026-08-02 실측)
    d.rounded_rectangle([x0, y0, x1, y1], radius=18, fill=GRASS + (238,), outline=LINE + (110,), width=3)
    # 페널티 박스
    pb = [x0 + bw * 0.62, y0 + bh * 0.16, x1 - 6, y0 + bh * 0.84]
    d.rectangle(pb, outline=LINE + (120,), width=3)
    # 골 에어리어
    ga = [x0 + bw * 0.84, y0 + bh * 0.33, x1 - 6, y0 + bh * 0.67]
    d.rectangle(ga, outline=LINE + (120,), width=3)
    # 골대
    d.rectangle([x1 - 10, y0 + bh * 0.40, x1 + 6, y0 + bh * 0.60], outline=ACCENT + (200,), width=5)
    # 페널티 아크
    d.arc([x0 + bw * 0.50, y0 + bh * 0.34, x0 + bw * 0.74, y0 + bh * 0.66],
          start=-70, end=70, fill=LINE + (90,), width=3)

    ps, tn, sh = spec.get("pass"), spec.get("turn"), spec.get("shot")
    ph = spec.get("phase", [0.0, 0.45, 0.62, 1.0])
    t_pass_end, t_turn_end = ph[1], ph[2]

    # --- 1) 패스 (점선 + 화살표) ---
    if ps:
        a, b = P(ps["from"]), P(ps["to"])
        seg = clamp01((progress - ph[0]) / max(t_pass_end - ph[0], 1e-6))
        cur = (_lerp(a[0], b[0], seg), _lerp(a[1], b[1], seg))
        _dashed(d, [a, cur], LINE + (210,), 5)
        if seg > 0.02:
            _arrow(d, cur, math.atan2(b[1] - a[1], b[0] - a[0]), LINE + (210,))
        d.ellipse([a[0] - 9, a[1] - 9, a[0] + 9, a[1] + 9], fill=LINE + (230,))

    # --- 2) 턴 (회전 호) ---
    if tn and progress >= t_pass_end:
        c = P(tn["at"])
        r = 34
        sweep = clamp01((progress - t_pass_end) / max(t_turn_end - t_pass_end, 1e-6))
        d.arc([c[0] - r, c[1] - r, c[0] + r, c[1] + r],
              start=-90, end=-90 + int(180 * sweep), fill=ACCENT + (230,), width=6)

    # --- 3) 슈팅 (곡선 궤적 + 공) ---
    ball = None
    if sh and progress >= t_turn_end:
        a, b = P(sh["from"]), P(sh["to"])
        cp = _ctrl(a, b, sh.get("curve", -0.15))
        seg = clamp01((progress - t_turn_end) / max(ph[3] - t_turn_end, 1e-6))
        pts = [_bez(a, cp, b, i / 28 * seg) for i in range(29)]
        for i in range(len(pts) - 1):
            d.line([pts[i], pts[i + 1]], fill=ACCENT + (235,), width=7)
        ball = pts[-1]
        if seg > 0.97:   # 골 순간 임팩트
            for rr, al in ((46, 90), (30, 150)):
                d.ellipse([b[0] - rr, b[1] - rr, b[0] + rr, b[1] + rr], outline=ACCENT + (al,), width=5)

    if ball:
        d.ellipse([ball[0] - 13, ball[1] - 13, ball[0] + 13, ball[1] + 13],
                  fill=(255, 255, 255, 250), outline=ACCENT + (255,), width=3)

    # --- 라벨 (2026-08-02 수정: turn.at과 shot.from이 같은 점이라 겹쳐 뭉개지던 문제 해결.
    #     라벨마다 서로 다른 기준점·오프셋을 주고, 화면 밖으로 나가지 않게 클램프한다) ---
    if font:
        items = []
        if ps and ps.get("label"):
            items.append((ph[0], P(ps["from"]), (0, -26), ps["label"], "mb"))
        if tn and tn.get("label"):
            items.append((t_pass_end, P(tn["at"]), (0, -62), tn["label"], "mb"))
        if sh and sh.get("label"):
            a, b = P(sh["from"]), P(sh["to"])
            mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            items.append((t_turn_end, mid, (0, 40), sh["label"], "mt"))
        for show, pt, off, label, anch in items:
            if progress < show:
                continue
            tx = min(max(pt[0] + off[0], x0 + 70), x1 - 70)
            ty = min(max(pt[1] + off[1], y0 + 20), y1 - 14)
            d.text((tx + 2, ty + 2), label, font=font, fill=(0, 0, 0, 190), anchor=anch)
            d.text((tx, ty), label, font=font, fill=(255, 255, 255, 240), anchor=anch)


def clamp01(v):
    return 0.0 if v < 0 else (1.0 if v > 1 else v)
