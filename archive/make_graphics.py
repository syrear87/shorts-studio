#!/usr/bin/env python3
# 자체 제작 배경 그래픽 (2026-08-04 디렉터: "열돔에 대한 그래픽 영상", "실제 돌핀의 예상 경로 영상")
# 채널 톤(어두운 남색 + 앰버 강조) 유지. 산출: out/graphics/heatdome.mp4, dolphin_track.mp4
import math
import os
import shutil
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "out", "graphics")
W, H, FPS = 1920, 1080, 30
NAVY = (14, 21, 38)
NAVY_HI = (24, 36, 62)
AMBER = (255, 190, 60)
RED = (235, 90, 60)
ORANGE = (250, 140, 70)
TEXT = (240, 242, 246)
DIM = (150, 160, 180)
LAND = (52, 66, 96)
LAND_EDGE = (90, 108, 148)
SEA = (18, 27, 48)

FONT_PATHS = [
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    "/Library/Fonts/AppleGothic.ttf",
]


def load_font(size):
    for p in FONT_PATHS:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def bg_gradient():
    im = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(im)
    for y in range(H):
        t = y / H
        c = tuple(int(NAVY[i] + (NAVY_HI[i] - NAVY[i]) * (1 - abs(t - 0.35) * 1.4)) for i in range(3))
        d.line([(0, y), (W, y)], fill=c)
    return im


# 한반도 간이 실루엣 (정밀 지도가 아닌 도식 — 라벨로 명시)
# 북부 넓고(두만강 유역), 동해안 완만, 남해안 들쭉, 서해안 요철 — 세로:가로 ≈ 1:0.62
KOREA = [(0.25, 0.10), (0.45, 0.00), (0.72, 0.06), (0.85, 0.16),
         (0.78, 0.28), (0.70, 0.38), (0.72, 0.50), (0.80, 0.62),
         (0.78, 0.74), (0.70, 0.84), (0.62, 0.92), (0.52, 0.88),
         (0.44, 0.95), (0.34, 0.90), (0.24, 0.94), (0.16, 0.87),
         (0.20, 0.76), (0.12, 0.68), (0.20, 0.58), (0.14, 0.48),
         (0.24, 0.40), (0.18, 0.30), (0.28, 0.22), (0.22, 0.14)]


def scale_pts(pts, x0, y0, w, h):
    return [(x0 + px * w, y0 + py * h) for px, py in pts]


def ease(t):
    return t * t * (3 - 2 * t)


def frames_dir(name):
    d = os.path.join(OUT, "frames_" + name)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d, exist_ok=True)
    return d


def encode(name, dur):
    d = os.path.join(OUT, "frames_" + name)
    mp4 = os.path.join(OUT, name + ".mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS),
                    "-i", os.path.join(d, "f%05d.png"),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", mp4], check=True)
    shutil.rmtree(d, ignore_errors=True)
    print("완료: %s (%.0fs)" % (mp4, dur))


def draw_typhoon(d, cx, cy, r, angle, color=TEXT):
    # 태풍 기호: 중심원 + 두 갈래 나선 꼬리
    d.ellipse([cx - r * 0.34, cy - r * 0.34, cx + r * 0.34, cy + r * 0.34], outline=color, width=6)
    for k in (0, math.pi):
        pts = []
        for i in range(28):
            t = i / 27.0
            a = angle + k + t * 2.4
            rr = r * (0.38 + 0.62 * t)
            pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
        d.line(pts, fill=color, width=6, joint="curve")


def make_heatdome(dur=17.0):
    name = "heatdome"
    fdir = frames_dir(name)
    total = int(dur * FPS)
    base = bg_gradient()
    f_med, f_small = load_font(46), load_font(36)
    ground_y = H * 0.76
    dome_cx = W * 0.50
    # 측면 단면도이므로 지도 대신 도시 스카이라인 (건물 [x중심비, 폭, 높이])
    BUILDINGS = [(-0.145, 46, 70), (-0.105, 60, 120), (-0.06, 52, 92), (-0.02, 70, 150),
                 (0.03, 56, 105), (0.075, 64, 135), (0.12, 48, 80), (0.155, 58, 112)]
    for fi in range(total):
        t = fi / FPS
        im = base.copy()
        ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(ov)
        # 지면선 + 바다
        d.rectangle([0, ground_y, W, H], fill=SEA + (170,))
        d.line([(0, ground_y), (W, ground_y)], fill=LAND_EDGE + (200,), width=4)
        # 도시 스카이라인 (지면 위, 도식)
        for bx, bw_, bh_ in BUILDINGS:
            x0 = dome_cx + bx * W - bw_ / 2
            d.rectangle([x0, ground_y - bh_, x0 + bw_, ground_y],
                        fill=LAND + (255,), outline=LAND_EDGE + (255,))
        lb = "한반도"
        tw_ = d.textlength(lb, font=f_med)
        d.text((dome_cx - tw_ / 2, ground_y + 26), lb, font=f_med, fill=TEXT + (230,))
        # 등장 진행도
        a1 = ease(min(1.0, max(0.0, (t - 0.6) / 1.2)))   # 북태평양(아래 돔)
        a2 = ease(min(1.0, max(0.0, (t - 2.2) / 1.2)))   # 티베트(위 돔)
        pulse = 1 + 0.012 * math.sin(t * 2.2)
        # 돔 2겹 (아래=주황 북태평양, 위=붉은 티베트) — 지면에서 시작
        dome_h = {"low": H * 0.62, "high": H * 0.78}
        for (hh, col, aa) in [(dome_h["low"], ORANGE, a1), (dome_h["high"], RED, a2)]:
            if aa <= 0:
                continue
            rx = W * 0.335 * pulse
            box = [dome_cx - rx, ground_y - hh, dome_cx + rx, ground_y + hh]
            d.arc(box, 180, 360, fill=col + (int(230 * aa),), width=16)
        # 라벨은 좌측 범례로 (중앙 자막 영역 회피)
        for (yy, col, aa, label) in [
            (H * 0.60, ORANGE, a1, "북태평양 고기압 (아래층)"),
            (H * 0.525, RED, a2, "티베트 고기압 (위층)"),
        ]:
            if aa <= 0:
                continue
            d.rectangle([W * 0.045, yy + 8, W * 0.045 + 34, yy + 42], fill=col + (int(255 * aa),))
            d.text((W * 0.045 + 50, yy), label, font=f_med, fill=col + (int(255 * aa),))
        # 갇힌 열 화살표: 돔 안에서 상승하다 소멸 (중앙 자막 영역 아래쪽만)
        a3 = ease(min(1.0, max(0.0, (t - 3.6) / 1.0)))
        if a3 > 0:
            for j, ax in enumerate([dome_cx - W * 0.13, dome_cx + W * 0.045, dome_cx + W * 0.155]):
                ph = (t * 0.55 + j * 0.33) % 1.0
                y_from, y_to = H * 0.64, H * 0.54
                yy = y_from + (y_to - y_from) * ph
                al = int(255 * a3 * (1 - abs(ph - 0.5) * 1.6))
                if al <= 0:
                    continue
                col = AMBER + (max(0, al),)
                d.line([(ax, yy + 46), (ax, yy)], fill=col, width=10)
                d.polygon([(ax - 14, yy + 8), (ax + 14, yy + 8), (ax, yy - 14)], fill=col)
        # 주석 (타이틀 없음 — 본편 칩·자막과 겹침 방지)
        a0 = ease(min(1.0, t / 0.8))
        note = "· 개념 도식 (실제 축척 아님)"
        d.text((W * 0.035, H * 0.045), note, font=f_small, fill=DIM + (int(200 * a0),))
        im.paste(ov, (0, 0), ov)
        im.save(os.path.join(fdir, "f%05d.png" % fi))
    encode(name, dur)


# 동아시아 간이 해안선: 중국 동해안(좌), 일본 열도(우) — 도식
CHINA = [(0.0, 0.05), (0.16, 0.06), (0.20, 0.16), (0.155, 0.28), (0.175, 0.42),
         (0.14, 0.55), (0.16, 0.70), (0.12, 0.86), (0.145, 1.0), (0.0, 1.0)]
JAPAN = [(0.86, 0.34), (0.90, 0.30), (0.955, 0.34), (0.93, 0.42), (0.885, 0.485),
         (0.86, 0.56), (0.815, 0.62), (0.79, 0.57), (0.825, 0.47)]


def make_dolphin_track(dur=15.0):
    name = "dolphin_track"
    fdir = frames_dir(name)
    total = int(dur * FPS)
    f_med, f_small = load_font(44), load_font(36)
    # 지도 베이스
    base = Image.new("RGB", (W, H), SEA)
    db = ImageDraw.Draw(base)
    for y in range(H):
        tt = y / H
        c = tuple(int(SEA[i] * (1 - 0.25 * tt) + NAVY_HI[i] * 0.25 * tt) for i in range(3))
        db.line([(0, y), (W, y)], fill=c)
    db.polygon(scale_pts(CHINA, 0, 0, W, H), fill=LAND, outline=LAND_EDGE)
    db.polygon(scale_pts(JAPAN, 0, 0, W, H), fill=LAND, outline=LAND_EDGE)
    korea = scale_pts(KOREA, W * 0.415, H * 0.10, W * 0.21, H * 0.55)
    db.polygon(korea, fill=LAND, outline=LAND_EDGE)
    db.text((W * 0.645, H * 0.13), "한반도", font=f_med, fill=TEXT)
    db.text((W * 0.055, H * 0.42), "중국", font=f_med, fill=DIM)
    db.text((W * 0.845, H * 0.40), "일본", font=f_med, fill=DIM)
    # 경로: 남해 남쪽 → 북서진 → 서해로 비켜감 (상륙 없음)
    P = [(0.60, 0.86), (0.55, 0.76), (0.50, 0.67), (0.43, 0.545), (0.375, 0.44), (0.345, 0.33), (0.335, 0.22)]
    path = [(px * W, py * H) for px, py in P]

    def path_pos(s):
        s = max(0.0, min(1.0, s)) * (len(path) - 1)
        i = min(int(s), len(path) - 2)
        f = s - i
        return (path[i][0] * (1 - f) + path[i + 1][0] * f,
                path[i][1] * (1 - f) + path[i + 1][1] * f)

    for fi in range(total):
        t = fi / FPS
        im = base.copy()
        ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(ov)
        prog = ease(min(1.0, max(0.0, (t - 1.0) / 8.0)))
        # 지나온 경로 실선 + 예상 경로 점선
        steps = 90
        for i in range(steps):
            s0, s1 = i / steps, (i + 1) / steps
            x0, y0 = path_pos(s0)
            x1, y1 = path_pos(s1)
            if s1 <= prog:
                d.line([(x0, y0), (x1, y1)], fill=TEXT + (235,), width=8)
            elif i % 2 == 0:
                d.line([(x0, y0), (x1, y1)], fill=DIM + (160,), width=5)
        # 태풍 심볼
        cx, cy = path_pos(prog)
        draw_typhoon(d, cx, cy, 74, angle=-t * 2.4, color=AMBER)
        lb = "태풍 돌핀"
        d.text((cx + 92, cy - 24), lb, font=f_med, fill=AMBER + (255,))
        # 동풍 화살표: 태풍 오른편에서 한반도로 (경로 후반부터)
        a2 = ease(min(1.0, max(0.0, (t - 6.5) / 1.2)))
        if a2 > 0:
            for j in range(3):
                ph = (t * 0.5 + j * 0.33) % 1.0
                x_from, x_to = W * 0.72, W * 0.545
                yy = H * (0.38 + j * 0.10)
                xx = x_from + (x_to - x_from) * ph
                al = int(255 * a2 * (1 - abs(ph - 0.5) * 1.7))
                if al <= 0:
                    continue
                col = ORANGE + (max(0, al),)
                d.line([(xx + 60, yy), (xx, yy)], fill=col, width=10)
                d.polygon([(xx + 10, yy - 14), (xx + 10, yy + 14), (xx - 16, yy)], fill=col)
            lab = "뜨거운 동풍"
            d.text((W * 0.60, H * 0.295), lab, font=f_med, fill=ORANGE + (int(255 * a2),))
        # 주석 (타이틀 없음 — 본편 칩·자막과 겹침 방지)
        a0 = ease(min(1.0, t / 0.8))
        d.text((W * 0.035, H * 0.045), "· 경로 개념 도식 (실측 지도 아님)", font=f_small,
               fill=DIM + (int(200 * a0),))
        im.paste(ov, (0, 0), ov)
        im.save(os.path.join(fdir, "f%05d.png" % fi))
    encode(name, dur)


# ── 태극기 도해 (2026-08-12 제작 → 같은 날 디렉터 기각: "그래픽 허접, 하지 마") ──
# ⚠️ 사용 금지. PIL 도해류는 디렉터 사전 승인 없이 편에 넣지 마라 (롱폼 heatdome/dolphin도 같은 평가).
# 코드는 도형 검증 로직(규격 태극기 기하) 참고용으로만 남긴다.
# ── (이하 기각된 도해 2종: 쇼츠 9:16 네이티브 1080×1920) ──
# 방향 오류가 곧 사고인 편이라 도형은 국기법 시행령 도식 그대로 그린다:
#   빨강 위 / 태극 경계는 깃면 대각선을 따라(빨강이 왼쪽에서 내려오고 파랑이 오른쪽에서 올라감)
#   괘 = 건(왼위·3획)·리(왼아래·4조각)·감(오른위·5조각)·곤(오른아래·6조각), 획은 대각선과 직각
# 렌더 후 반드시 프레임을 눈으로 재검증할 것 (태극기 화면 검증 절차 — CALENDAR §태극기).
SW, SH = 1080, 1920
TG_RED, TG_BLUE = (205, 46, 58), (0, 71, 160)   # 국기 규격색 CD2E3A / 0047A0
TG_BLACK = (22, 22, 26)
DIAG = math.degrees(math.atan2(2, 3))            # 깃면(3:2) 대각선 각도


def bg_gradient_v():
    im = Image.new("RGB", (SW, SH))
    d = ImageDraw.Draw(im)
    for y in range(SH):
        t = y / SH
        c = tuple(int(NAVY[i] + (NAVY_HI[i] - NAVY[i]) * (1 - abs(t - 0.30) * 1.3)) for i in range(3))
        d.line([(0, y), (SW, y)], fill=c)
    return im


def draw_taegukgi(a):
    """규격 태극기 패널 (a × a*2/3, RGBA) + 부속 좌표 반환."""
    b = int(a * 2 / 3)
    im = Image.new("RGBA", (a, b), (255, 255, 255, 255))
    d = ImageDraw.Draw(im)
    ox, oy, r = a / 2, b / 2, b / 4
    u = (math.cos(math.radians(DIAG)), math.sin(math.radians(DIAG)))
    box = [ox - r, oy - r, ox + r, oy + r]
    d.ellipse(box, fill=TG_BLUE)
    d.pieslice(box, DIAG - 180, DIAG, fill=TG_RED)              # 대각선 위쪽 절반 = 빨강
    m1 = (ox - r / 2 * u[0], oy - r / 2 * u[1])                  # 왼위 반원 → 빨강이 왼쪽에서 내려옴
    m2 = (ox + r / 2 * u[0], oy + r / 2 * u[1])                  # 오른아래 반원 → 파랑이 오른쪽에서 올라감
    d.ellipse([m1[0] - r / 2, m1[1] - r / 2, m1[0] + r / 2, m1[1] + r / 2], fill=TG_RED)
    d.ellipse([m2[0] - r / 2, m2[1] - r / 2, m2[0] + r / 2, m2[1] + r / 2], fill=TG_BLUE)
    # 괘 비례 (시행령 도식): 길이 = 태극지름 1/2 (b/4), 너비(3효+간격) = 태극지름 1/3 (b/6)
    L, th = b / 4, b / 24
    g = (b / 6 - 3 * th) / 2          # 효 사이 간격 (= b/48)
    split = th * 0.8                  # 끊긴 효의 트임
    depth = 3 * th + 2 * g
    corners = {}   # 이름 → (중심좌표, 하이라이트 반경)
    # PIL rotate는 화면상 시계 방향으로 돈다(실측 2026-08-12) — 부호 주의
    for name, pat, cx_, cy_, rot in [
        ("건", [0, 0, 0], -1, -1, DIAG - 90),   # 왼위, 획 "/" (대각선과 직각)
        ("리", [0, 1, 0], -1, +1, 90 - DIAG),   # 왼아래, 획 "\"
        ("감", [1, 0, 1], +1, -1, 90 - DIAG),   # 오른위, 획 "\"
        ("곤", [1, 1, 1], +1, +1, DIAG - 90),   # 오른아래, 획 "/"
    ]:
        tile = Image.new("RGBA", (int(L), int(depth)), (0, 0, 0, 0))
        td = ImageDraw.Draw(tile)
        for i, broken in enumerate(pat):
            y0 = i * (th + g)
            if broken:
                td.rectangle([0, y0, L / 2 - split / 2, y0 + th], fill=TG_BLACK)
                td.rectangle([L / 2 + split / 2, y0, L, y0 + th], fill=TG_BLACK)
            else:
                td.rectangle([0, y0, L, y0 + th], fill=TG_BLACK)
        rt = tile.rotate(rot, expand=True, resample=Image.BICUBIC)
        n = math.hypot(cx_ * 3, cy_ * 2)
        dvec = (cx_ * 3 / n, cy_ * 2 / n)
        dist = r + b / 8 + depth / 2
        px, py = ox + dvec[0] * dist, oy + dvec[1] * dist
        im.paste(rt, (int(px - rt.width / 2), int(py - rt.height / 2)), rt)
        corners[name] = ((px, py), max(rt.width, rt.height))
    return im, (ox, oy, r), corners


def _arrow(d, pts, color, w=14):
    d.line(pts, fill=color, width=w, joint="curve")
    (x0, y0), (x1, y1) = pts[-2], pts[-1]
    ang = math.atan2(y1 - y0, x1 - x0)
    a1, a2 = ang + math.radians(152), ang - math.radians(152)
    hl = w * 2.6
    d.polygon([(x1, y1), (x1 + hl * math.cos(a1), y1 + hl * math.sin(a1)),
               (x1 + hl * math.cos(a2), y1 + hl * math.sin(a2))], fill=color)


def make_taeguk_wave(dur=12.0):
    """물결 방향 도해: 대각선 점선 + 빨강↓(왼쪽)·파랑↑(오른쪽) 화살표."""
    name = "taeguk_wave"
    fdir = frames_dir(name)
    total = int(dur * FPS)
    base = bg_gradient_v()
    f_small, f_chip = load_font(34), load_font(52)
    PA = 800                                   # 패널 폭
    panel, (ox, oy, r), _ = draw_taegukgi(PA)
    px0, py0 = (SW - PA) // 2, 225             # 패널 위치 (채널 칩 150~210 아래, 자막 지대 y≥768 위)
    pb = panel.height
    gx, gy = px0 + ox, py0 + oy                # 태극 중심 (캔버스 좌표)
    for fi in range(total):
        t = fi / FPS
        im = base.copy()
        a0 = ease(min(1.0, t / 0.9))
        pf = panel.copy()
        if a0 < 1:
            pf.putalpha(pf.getchannel("A").point(lambda v: int(v * a0)))
        im.paste(pf, (px0, py0), pf)
        ov = Image.new("RGBA", (SW, SH), (0, 0, 0, 0))
        d = ImageDraw.Draw(ov)
        # 대각선 점선 (왼위 → 오른아래) — 괘도 대각선 위에 있어 전체를 그리면 괘를 관통한다
        # → 태극 주변 구간(0.30~0.70)만 그려 경계가 대각선을 따른다는 것만 보여준다
        a1 = ease(min(1.0, max(0.0, (t - 1.2) / 0.9)))
        if a1 > 0:
            steps = 12
            for i in range(int(steps * a1)):
                s0 = 0.30 + 0.40 * i / steps
                s1 = 0.30 + 0.40 * (i + 0.55) / steps
                d.line([(px0 + PA * s0, py0 + pb * s0), (px0 + PA * s1, py0 + pb * s1)],
                       fill=AMBER + (235,), width=8)
        # 빨강: 왼쪽에서 내려온다 (원 왼쪽 바깥, 아래 방향 곡선 화살표)
        a2 = ease(min(1.0, max(0.0, (t - 2.6) / 0.8)))
        pulse = 10 * math.sin(t * 2.4)
        if a2 > 0:
            x = gx - r - 64
            ys, ye = gy - r * 0.62, gy + r * 0.30 + pulse
            col = TG_RED + (int(255 * a2),)
            _arrow(d, [(x + 26, ys), (x, (ys + ye) / 2), (x + 8, ye)], col)
            d.text((px0 + 18, (ys + ye) / 2 - 30), "빨강", font=f_chip, fill=col)
        # 파랑: 오른쪽에서 올라온다
        a3 = ease(min(1.0, max(0.0, (t - 3.6) / 0.8)))
        if a3 > 0:
            x = gx + r + 64
            ys, ye = gy + r * 0.62, gy - r * 0.30 - pulse
            col = TG_BLUE + (int(255 * a3),)
            _arrow(d, [(x - 26, ys), (x, (ys + ye) / 2), (x - 8, ye)], col)
            tw = d.textlength("파랑", font=f_chip)
            d.text((px0 + PA - tw - 18, (ys + ye) / 2 - 30), "파랑", font=f_chip, fill=col)
        d.text((40, 46), "· 개념 도식 (국기법 시행령 도식 기준)", font=f_small,
               fill=DIM + (int(200 * a0),))
        im.paste(ov, (0, 0), ov)
        im.save(os.path.join(fdir, "f%05d.png" % fi))
    encode(name, dur)


def make_gwae_count(dur=14.0):
    """건곤감리 도해: 왼위 3 → 왼아래 4 → 오른위 5 → 오른아래 6 순서로 하이라이트."""
    name = "gwae_count"
    fdir = frames_dir(name)
    total = int(dur * FPS)
    base = bg_gradient_v()
    f_small, f_pos, f_num = load_font(34), load_font(36), load_font(76)
    PA = 800
    panel, (ox, oy, r), corners = draw_taegukgi(PA)
    px0, py0 = (SW - PA) // 2, 225
    SEQ = [("건", "왼쪽 위", "3", 1.4), ("리", "왼쪽 아래", "4", 3.2),
           ("감", "오른쪽 위", "5", 5.0), ("곤", "오른쪽 아래", "6", 6.8)]
    chip_w, chip_h, gap = 224, 128, 14
    row_x0 = (SW - (chip_w * 4 + gap * 3)) // 2
    for fi in range(total):
        t = fi / FPS
        im = base.copy()
        a0 = ease(min(1.0, t / 0.9))
        pf = panel.copy()
        if a0 < 1:
            pf.putalpha(pf.getchannel("A").point(lambda v: int(v * a0)))
        im.paste(pf, (px0, py0), pf)
        ov = Image.new("RGBA", (SW, SH), (0, 0, 0, 0))
        d = ImageDraw.Draw(ov)
        for i, (nm, pos, num, t0) in enumerate(SEQ):
            aa = ease(min(1.0, max(0.0, (t - t0) / 0.6)))
            if aa <= 0:
                continue
            (cx, cy), sz = corners[nm]
            cx, cy = px0 + cx, py0 + cy
            hb = sz / 2 + 26
            live = 1.0 + (0.04 * math.sin((t - t0) * 3.0) if t - t0 < 1.6 else 0.0)
            d.rounded_rectangle([cx - hb * live, cy - hb * live, cx + hb * live, cy + hb * live],
                                radius=26, outline=AMBER + (int(255 * aa),), width=8)
            # 상단 칩: 위치 + 조각 수
            x0 = row_x0 + i * (chip_w + gap)
            y0 = 16   # 채널 칩(150~) 위에서 끝나도록
            d.rounded_rectangle([x0, y0, x0 + chip_w, y0 + chip_h], radius=20,
                                fill=NAVY_HI + (int(235 * aa),),
                                outline=AMBER + (int(255 * aa),), width=4)
            tw = d.textlength(pos, font=f_pos)
            d.text((x0 + (chip_w - tw) / 2, y0 + 12), pos, font=f_pos,
                   fill=TEXT + (int(255 * aa),))
            label = "%s %s" % (nm, num)
            tw = d.textlength(label, font=f_num)
            d.text((x0 + (chip_w - tw) / 2, y0 + 44), label, font=f_num,
                   fill=AMBER + (int(255 * aa),))
        # 주석은 자막 지대(H*0.40≈768 이하)를 피해 화면 하단 여백에
        d.text((40, 1560), "· 개념 도식 (국기법 시행령 도식 기준)",
               font=f_small, fill=DIM + (int(200 * a0),))
        im.paste(ov, (0, 0), ov)
        im.save(os.path.join(fdir, "f%05d.png" % fi))
    encode(name, dur)


def make_flag_card(dur=8.0):
    """CTA 엔드카드: 규격 태극기 패널 + 은은한 앰버 테두리 펄스 (텍스트는 렌더러가 얹는다)."""
    name = "flag_card"
    fdir = frames_dir(name)
    total = int(dur * FPS)
    base = bg_gradient_v()
    PA = 800
    panel, _, _ = draw_taegukgi(PA)
    px0, py0 = (SW - PA) // 2, 225
    for fi in range(total):
        t = fi / FPS
        im = base.copy()
        a0 = ease(min(1.0, t / 0.7))
        pf = panel.copy()
        if a0 < 1:
            pf.putalpha(pf.getchannel("A").point(lambda v: int(v * a0)))
        im.paste(pf, (px0, py0), pf)
        ov = Image.new("RGBA", (SW, SH), (0, 0, 0, 0))
        d = ImageDraw.Draw(ov)
        m = 18 + 6 * math.sin(t * 2.0)
        d.rounded_rectangle([px0 - m, py0 - m, px0 + PA + m, py0 + panel.height + m],
                            radius=18, outline=AMBER + (int(190 * a0),), width=6)
        im.paste(ov, (0, 0), ov)
        im.save(os.path.join(fdir, "f%05d.png" % fi))
    encode(name, dur)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which in ("all", "heatdome"):
        make_heatdome()
    if which in ("all", "dolphin"):
        make_dolphin_track()
    if which in ("all", "taeguk_wave"):
        make_taeguk_wave()
    if which in ("all", "gwae_count"):
        make_gwae_count()
    if which in ("all", "flag_card"):
        make_flag_card()
