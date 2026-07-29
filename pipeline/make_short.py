#!/usr/bin/env python3
# 숏츠 제작 파이프라인: 스크립트 JSON → edge-tts(단어 타이밍) → 배경영상(Pexels)+키네틱 자막 → BGM 믹스 → mp4
# 사용: .venv/bin/python3 pipeline/make_short.py content/2026-07-29.json --out out/2026-07-29.mp4
# 배경: script JSON의 "bg_query"(예: "eiffel tower")로 Pexels에서 세로 영상 검색.
#       keys.env에 PEXELS_API_KEY 필요. 없거나 실패하면 그라데이션 배경으로 폴백.
import argparse, asyncio, json, math, os, re, subprocess, sys, wave
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H, FPS = 1080, 1920, 30
ACCENT = (255, 182, 39)
TEXT = (245, 246, 250)
DIM = (170, 176, 195)
VOICES = {"female": "ko-KR-SunHiNeural", "male": "ko-KR-InJoonNeural"}
VOICE = VOICES["female"]
RATE = "+8%"
SCENE_GAP = 0.35
LEAD_IN = 0.30
TAIL = 0.9
SCRIM = 130           # 배경영상 위 어두운 막 (0~255)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def font_path():
    cands = [
        os.path.join(ROOT, "assets", "fonts", "NotoSansCJKkr-Black.otf"),
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc",
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    ]
    for c in cands:
        if os.path.exists(c):
            return c
    sys.exit("한글 폰트를 찾을 수 없습니다 — setup.sh를 먼저 실행하세요")

FONT = font_path()
TTC_IDX = 1 if FONT.endswith("NotoSansCJK-Black.ttc") else 0

def load_font(size):
    try:
        return ImageFont.truetype(FONT, size, index=TTC_IDX)
    except Exception:
        return ImageFont.truetype(FONT, size, index=0)

def load_keys():
    env = {}
    p = os.path.join(ROOT, "keys.env")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env

# ---------- Pexels 배경 영상 ----------
def fetch_bg(query, need_dur):
    """Pexels에서 배경 영상 검색·다운로드 → 로컬 경로 (실패 시 None).
    query: 문자열 또는 문자열 리스트(우선순위 순 폴백).
    소재 적합성이 우선 — 세로가 없으면 가로 HD를 받아 크롭한다."""
    key = load_keys().get("PEXELS_API_KEY") or os.environ.get("PEXELS_API_KEY")
    queries = query if isinstance(query, list) else [query]
    queries = [q for q in queries if q]
    if not key or not queries:
        return None
    cache = os.path.join(ROOT, "assets", "bg_cache")
    os.makedirs(cache, exist_ok=True)
    import requests
    for q in queries:
        try:
            r = requests.get("https://api.pexels.com/videos/search",
                             params={"query": q, "per_page": 25},
                             headers={"Authorization": key}, timeout=20)
            r.raise_for_status()
            vids = r.json().get("videos", [])
            best, best_file, best_score = None, None, -1
            for v in sorted(vids, key=lambda x: -min(x.get("duration", 0), 60)):
                for f in v.get("video_files", []):
                    w_, h_ = f.get("width") or 0, f.get("height") or 0
                    if not f.get("link") or min(w_, h_) < 1080:
                        continue
                    portrait = h_ > w_
                    score = (2000 if portrait else 0) + min(h_, 2200) + min(v.get("duration", 0), 60) * 5
                    if score > best_score:
                        best, best_file, best_score = v, f, score
            if not best:
                continue
            dst = os.path.join(cache, "pexels_%d.mp4" % best["id"])
            if not os.path.exists(dst):
                with requests.get(best_file["link"], stream=True, timeout=120) as resp:
                    resp.raise_for_status()
                    with open(dst, "wb") as fh:
                        for chunk in resp.iter_content(1 << 20):
                            fh.write(chunk)
            print("배경 영상: query=%r → pexels id=%s (%ds, %dx%d) — Pexels License"
                  % (q, best["id"], best.get("duration", 0), best_file.get("width", 0), best_file.get("height", 0)),
                  flush=True)
            return dst
        except Exception as e:
            print("배경 검색 실패(%s: %s) → 다음 검색어" % (q, e), flush=True)
    print("배경 영상 없음 → 그라데이션 폴백", flush=True)
    return None

# ---------- TTS ----------
async def tts_scene(text, mp3_path):
    import edge_tts
    try:
        # edge-tts 7.x: 기본이 SentenceBoundary라 단어 타이밍을 명시 요청해야 함
        comm = edge_tts.Communicate(text, VOICE, rate=RATE, boundary="WordBoundary")
    except TypeError:
        comm = edge_tts.Communicate(text, VOICE, rate=RATE)
    boundaries = []
    with open(mp3_path, "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                boundaries.append((chunk["offset"] / 1e7, chunk["text"]))
    return boundaries

def media_duration(path):
    out = subprocess.run(["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                          "-of", "csv=p=0", path], capture_output=True, text=True)
    return float(out.stdout.strip())

# ---------- 타이밍 매핑 ----------
def display_words(scene):
    ws = []
    for li, (line, hl) in enumerate(scene["lines"]):
        for w in line.split(" "):
            ws.append({"line": li, "word": w, "hl": any(h in w for h in hl)})
    return ws

def norm(s):
    return re.sub(r"[^\w가-힣%]", "", s)

def assign_times(dwords, boundaries, dur):
    if boundaries and len(boundaries) == len(dwords):
        return [b[0] for b in boundaries]
    times, bi = [], 0
    for dw in dwords:
        t_norm = norm(dw["word"])
        matched = None
        for j in range(bi, min(bi + 3, len(boundaries))):
            if norm(boundaries[j][1]) and (norm(boundaries[j][1]) in t_norm or t_norm in norm(boundaries[j][1])):
                matched = j
                break
        if matched is not None:
            times.append(boundaries[matched][0])
            bi = matched + 1
        else:
            times.append(None)
    known = [(i, t) for i, t in enumerate(times) if t is not None]
    if not known:
        return [i * dur / max(len(dwords), 1) for i in range(len(dwords))]
    for i in range(len(times)):
        if times[i] is None:
            prev = max([k for k in known if k[0] < i], default=known[0], key=lambda x: x[0])
            nxt = min([k for k in known if k[0] > i], default=known[-1], key=lambda x: x[0])
            if prev[0] == nxt[0]:
                times[i] = prev[1]
            else:
                f = (i - prev[0]) / (nxt[0] - prev[0])
                times[i] = prev[1] + f * (nxt[1] - prev[1])
    return times

# ---------- 렌더 ----------
def ease_out_back(t, s=1.35):
    t -= 1
    return 1 + (s + 1) * t ** 3 + s * t ** 2

def clamp(x, a, b):
    return max(a, min(b, x))

def make_bg():
    g = Image.new("RGB", (W, H))
    top, bot = (11, 16, 32), (24, 28, 54)
    px = g.load()
    for y in range(H):
        f = y / H
        row = tuple(int(top[i] + (bot[i] - top[i]) * f) for i in range(3))
        for x in range(W):
            px[x, y] = row
    return g

def make_glow(r, color, alpha):
    s = r * 2
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ImageDraw.Draw(im).ellipse([r * 0.3, r * 0.3, s - r * 0.3, s - r * 0.3], fill=color + (alpha,))
    return im.filter(ImageFilter.GaussianBlur(r * 0.35))

def render(script, timeline, out_dir, total_dur, channel_chip, video_bg):
    """video_bg=True → 투명 오버레이 PNG(+스크림), False → 그라데이션 JPG."""
    if not video_bg:
        BG = make_bg()
        GA = make_glow(520, ACCENT, 26)
        GB = make_glow(640, (90, 110, 220), 22)
    F_BIG, F_MED = load_font(92), load_font(78)
    F_CHIP, F_NUM, F_SUB = load_font(36), load_font(140), load_font(40)

    # 채널 배너: 1회 프리렌더 (불투명 필 + 정중앙 정렬 → 압축·움직임에도 또렷)
    def make_chip(text):
        tmp = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
        bb = tmp.textbbox((0, 0), text, font=F_CHIP)
        tw = bb[2] - bb[0]
        pw, ph = int(tw + 76), 80
        c = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
        dc = ImageDraw.Draw(c)
        dc.rounded_rectangle([0, 0, pw - 1, ph - 1], radius=ph // 2, fill=(14, 18, 33, 232))
        dc.text((pw / 2, ph / 2 - 2), text, font=F_CHIP, fill=ACCENT, anchor="mm")
        return c

    CHIP = make_chip(channel_chip)
    os.makedirs(os.path.join(out_dir, "frames"), exist_ok=True)
    total = int(total_dur * FPS)
    fact_counter, fact_nums = 0, {}
    for i, sc in enumerate(script["scenes"]):
        if sc.get("kind") == "fact":
            fact_counter += 1
            fact_nums[i] = "%02d" % fact_counter

    # 텍스트 그림자용 헬퍼
    def text_sh(d, xy, s, font, fill):
        x, y = xy
        if video_bg:
            d.text((x + 3, y + 3), s, font=font, fill=(0, 0, 0, min(200, fill[3] if len(fill) > 3 else 255)))
        d.text(xy, s, font=font, fill=fill)

    for fi in range(total):
        t = fi / FPS
        if video_bg:
            im = Image.new("RGBA", (W, H), (0, 0, 0, SCRIM))   # 어두운 스크림 + 투명 텍스트층
        else:
            im = BG.copy().convert("RGBA")
            ax = int(W * 0.75 + 60 * math.sin(t * 0.35)); ay = int(H * 0.20 + 40 * math.cos(t * 0.28))
            bx = int(W * 0.12 + 50 * math.sin(t * 0.22 + 2)); by = int(H * 0.78 + 55 * math.cos(t * 0.30 + 1))
            im.alpha_composite(GA, (ax - 520, ay - 520))
            im.alpha_composite(GB, (bx - 640, by - 640))
        d = ImageDraw.Draw(im)
        im.alpha_composite(CHIP, ((W - CHIP.width) // 2, 150))

        si = None
        for idx, tl in enumerate(timeline):
            if tl["start"] <= t < tl["end"]:
                si = idx
                break
        if si is not None:
            sc, tl = script["scenes"][si], timeline[si]
            local = t - tl["start"]
            fade = clamp((tl["end"] - t) / 0.35, 0, 1) if tl["end"] - t < 0.35 else 1.0
            font = F_BIG if sc.get("kind") in ("hook", "cta") else F_MED
            y_cursor = H * 0.40
            if si in fact_nums:
                a = clamp(local / 0.3, 0, 1)
                num = fact_nums[si]
                d.text((W / 2 - d.textlength(num, font=F_NUM) / 2, H * 0.26),
                       num, font=F_NUM, fill=ACCENT + (int((140 if video_bg else 80) * a * fade),))
                y_cursor = H * 0.42
            line_h = int(font.size * 1.42)
            wi = 0
            for li, (line, hl) in enumerate(sc["lines"]):
                # 긴 줄은 화면 폭(여백 90px)에 맞게 폰트 자동 축소
                line_font = font
                lw = d.textlength(line, font=line_font)
                if lw > W - 90:
                    line_font = load_font(max(44, int(font.size * (W - 90) / lw)))
                    lw = d.textlength(line, font=line_font)
                x = (W - lw) / 2
                y = y_cursor + li * line_h
                for w_ in line.split(" "):
                    t_in = tl["word_times"][wi] - tl["start"]
                    a = clamp((local - t_in) / 0.22, 0, 1)
                    if a > 0:
                        s = ease_out_back(a)
                        col = ACCENT if tl["dwords"][wi]["hl"] else TEXT
                        alpha = int(255 * a * fade)
                        fs = load_font(int(line_font.size * (0.7 + 0.3 * s))) if abs(s - 1) > 0.01 else line_font
                        yo = (1 - a) * 26
                        text_sh(d, (x, y + yo + (line_font.size - fs.size) / 2), w_, fs, col + (alpha,))
                    x += d.textlength(w_ + " ", font=line_font)
                    wi += 1
            if sc.get("kind") == "cta" and sc.get("sub"):
                a = clamp((local - 0.9) / 0.4, 0, 1)
                text_sh(d, ((W - d.textlength(sc["sub"], font=F_SUB)) / 2, H * 0.56),
                        sc["sub"], F_SUB, DIM + (int(255 * a * fade),))
        d.rectangle([0, H - 14, W * (t / total_dur), H], fill=ACCENT + (230,))
        if video_bg:
            im.save(os.path.join(out_dir, "frames", "f%05d.png" % fi))
        else:
            im.convert("RGB").save(os.path.join(out_dir, "frames", "f%05d.jpg" % fi), quality=92)
        if fi % 150 == 0:
            print("frame %d/%d" % (fi, total), flush=True)

# ---------- BGM ----------
def make_bgm(dur, path):
    SR = 44100
    prog = [[220.0, 261.63, 329.63], [174.61, 220.0, 261.63],
            [130.81, 164.81, 196.0, 261.63], [196.0, 246.94, 293.66]]
    bar = 3.4
    audio = np.zeros(int(SR * dur))
    for bi in range(int(dur / bar) + 1):
        chord = prog[bi % 4]
        n = int(SR * bar)
        tt = np.arange(n) / SR
        seg = np.zeros(n)
        for f0 in chord:
            for mult, amp in [(1, 1.0), (2, 0.25), (0.5, 0.5)]:
                seg += amp * np.sin(2 * np.pi * f0 * mult * tt + 0.7 * np.sin(2 * np.pi * 0.15 * tt))
        env = np.minimum(tt / 0.8, 1.0) * np.clip((bar - tt) / 1.2, 0.25, 1)
        seg *= env
        i0 = int(bi * bar * SR)
        i1 = min(i0 + n, len(audio))
        audio[i0:i1] += seg[: i1 - i0]
    audio /= max(np.abs(audio).max(), 1e-9)
    fo = int(SR * 1.5)
    fade = np.ones(len(audio)); fade[-fo:] = np.linspace(1, 0, fo)
    pcm = (audio * fade * 32767).astype(np.int16)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(SR)
        wf.writeframes(pcm.tobytes())

# ---------- main ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("script_json")
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-bg-video", action="store_true", help="배경영상 없이 그라데이션")
    args = ap.parse_args()
    with open(args.script_json, encoding="utf-8") as f:
        script = json.load(f)
    global VOICE
    nar = script.get("narrator", "female")
    VOICE = VOICES.get(nar, nar if "Neural" in str(nar) else VOICES["female"])
    print("성우: %s (%s)" % (VOICE, nar), flush=True)
    base = os.path.splitext(os.path.basename(args.script_json))[0]
    out_mp4 = args.out or os.path.join("out", base + ".mp4")
    work = os.path.join("out", "work_" + base)
    os.makedirs(work, exist_ok=True)

    # 1) 씬별 TTS
    timeline = []
    cursor = LEAD_IN
    for i, sc in enumerate(script["scenes"]):
        mp3 = os.path.join(work, "s%02d.mp3" % i)
        boundaries = asyncio.run(tts_scene(sc["voice"], mp3))
        dur = media_duration(mp3)
        dws = display_words(sc)
        times = assign_times(dws, boundaries, dur)
        timeline.append({"start": cursor, "end": cursor + dur + SCENE_GAP, "mp3": mp3,
                         "dwords": dws, "word_times": [cursor + t for t in times]})
        cursor += dur + SCENE_GAP
        print("scene %d: %.2fs, words=%d, boundaries=%d" % (i, dur, len(dws), len(boundaries)), flush=True)
    total_dur = cursor + TAIL
    if not (15 <= total_dur <= 55):
        print("경고: 총 길이 %.1fs — 목표 20~50s 밖" % total_dur, flush=True)

    # 2) 배경 영상
    bg_path = None
    if not args.no_bg_video:
        bg_path = fetch_bg(script.get("bg_query", ""), total_dur)
    video_bg = bg_path is not None

    # 3) 렌더 + BGM
    render(script, timeline, work, total_dur, script.get("chip", "오늘의 지식 · 1일 1지식"), video_bg)
    bgm = os.path.join(work, "bgm.wav")
    make_bgm(total_dur, bgm)

    # 4) 합성·인코딩
    cmd = ["ffmpeg", "-y"]
    if video_bg:
        cmd += ["-stream_loop", "-1", "-i", bg_path,
                "-framerate", str(FPS), "-i", os.path.join(work, "frames", "f%05d.png"),
                "-i", bgm]
        vf = ("[0:v]scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,setsar=1,fps=%d[bgv];"
              "[bgv][1:v]overlay=format=auto[vout]" % (W, H, W, H, FPS))
        a_base = 2
    else:
        cmd += ["-framerate", str(FPS), "-i", os.path.join(work, "frames", "f%05d.jpg"), "-i", bgm]
        vf = "[0:v]copy[vout]"
        a_base = 1
    fl = [vf, "[%d:a]volume=0.14[bg]" % a_base]
    amix_in = "[bg]"
    for i, tl in enumerate(timeline):
        cmd += ["-i", tl["mp3"]]
        fl.append("[%d:a]adelay=%d:all=1,volume=1.0[v%d]" % (a_base + 1 + i, int(tl["start"] * 1000), i))
        amix_in += "[v%d]" % i
    fl.append("%samix=inputs=%d:normalize=0[aout]" % (amix_in, len(timeline) + 1))
    cmd += ["-filter_complex", ";".join(fl), "-map", "[vout]", "-map", "[aout]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "160k", "-t", str(total_dur), out_mp4]
    subprocess.run(cmd, check=True, capture_output=True)
    print("완료: %s (%.1fs, 배경=%s)" % (out_mp4, total_dur, "영상" if video_bg else "그라데이션"))

if __name__ == "__main__":
    main()
