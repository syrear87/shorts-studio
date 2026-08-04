#!/usr/bin/env python3
# 숏츠 제작 파이프라인: 스크립트 JSON → edge-tts(단어 타이밍) → 배경영상(Pexels)+키네틱 자막 → BGM 믹스 → mp4
# 사용: .venv/bin/python3 pipeline/make_short.py content/2026-07-29.json --out out/2026-07-29.mp4
# 배경: script JSON의 "bg_query"(예: "eiffel tower")로 Pexels에서 세로 영상 검색.
#       keys.env에 PEXELS_API_KEY 필요. 없거나 실패하면 그라데이션 배경으로 폴백.
import argparse, asyncio, glob, json, math, os, re, shutil, subprocess, sys, wave
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H, FPS = 1080, 1920, 30
ACCENT = (255, 182, 39)
TEXT = (245, 246, 250)
DIM = (170, 176, 195)
VOICES = {"female": "ko-KR-SunHiNeural", "male": "ko-KR-InJoonNeural"}
VOICE = VOICES["female"]
# InJoon(남)은 SunHi(여)+8%보다 실측 ~10%p 느림 → 성우별 기본 속도로 페이스 통일 (2026-07-29 실측)
RATES = {"female": "+8%", "male": "+18%"}
RATE = RATES["female"]
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
def _download(url, dst):
    """스트리밍 다운로드: dst+'.part'에 받고 완료 시에만 원자 교체 (2026-08-02 리뷰).
    다운로드 중 타임아웃·세션 킬로 잘린 파일이 최종 경로에 남아 캐시 히트로
    영구 재사용되는 오염을 차단한다. 진입 시 이전 런의 잔존 *.part도 청소."""
    import requests
    for stale in glob.glob(os.path.join(os.path.dirname(dst), "*.part")):
        try:
            os.remove(stale)
        except OSError:
            pass
    part = dst + ".part"
    with requests.get(url, stream=True, timeout=120) as resp:
        resp.raise_for_status()
        with open(part, "wb") as fh:
            for chunk in resp.iter_content(1 << 20):
                fh.write(chunk)
    os.replace(part, dst)

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
                _download(best_file["link"], dst)   # 2026-08-02 리뷰: .part+원자 교체
            print("배경 영상: query=%r → pexels id=%s (%ds, %dx%d) — Pexels License"
                  % (q, best["id"], best.get("duration", 0), best_file.get("width", 0), best_file.get("height", 0)),
                  flush=True)
            return dst
        except Exception as e:
            print("배경 검색 실패(%s: %s) → 다음 검색어" % (q, e), flush=True)
    print("배경 영상 없음 → 그라데이션 폴백", flush=True)
    return None

def used_bg_ids(exclude_script=None):
    """이미 다른 편에서 쓴 배경 id 집합 (2026-08-04 실사고: 에어컨 유래 편이
    한전 편과 같은 배경을 써서 피드에서 재탕처럼 보임 — 디렉터가 커버를 수동 교체).
    대체본(같은 날짜-슬롯의 재제작, 예: am ↔ am2)끼리는 공유를 허용한다."""
    def norm(p):
        return re.sub(r"\d+$", "", os.path.splitext(os.path.basename(p))[0])
    me = norm(exclude_script) if exclude_script else None
    used = set()
    for p in glob.glob(os.path.join(ROOT, "content", "2026-*.json")):
        if p.endswith(".meta.json") or (me and norm(p) == me):
            continue
        try:
            s = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        ids = s.get("bg_ids") or ([s["bg_id"]] if s.get("bg_id") else [])
        used.update(str(v) for v in ids)   # 영상은 "123", 사진은 "photo:123" 문자열로 통일
    return used


def fetch_bg_photo(photo_id):
    """Pexels '사진'을 받아 켄 번즈 배경으로 쓴다 (2026-08-04 디렉터 승인 —
    역사·유래 장면은 영상 스톡이 없어도 사진은 존재한다. 다큐의 표준 기법)."""
    key = load_keys().get("PEXELS_API_KEY") or os.environ.get("PEXELS_API_KEY")
    if not key or not photo_id:
        return None
    cache = os.path.join(ROOT, "assets", "bg_cache")
    os.makedirs(cache, exist_ok=True)
    dst = os.path.join(cache, "pexels_photo_%s.jpg" % photo_id)
    import requests
    try:
        if not os.path.exists(dst):
            r = requests.get("https://api.pexels.com/v1/photos/%s" % photo_id,
                             headers={"Authorization": key}, timeout=20)
            r.raise_for_status()
            src = r.json().get("src", {})
            url = src.get("large2x") or src.get("original")
            if not url:
                return None
            _download(url, dst)
        print("배경 사진(켄 번즈): pexels photo id=%s — Pexels License" % photo_id, flush=True)
        return dst
    except Exception as e:
        print("배경 사진 다운로드 실패(%s) — 기각 예정" % e, flush=True)
        return None


def fetch_bg_by_id(vid_id):
    """Pexels 영상 id를 직접 지정해 다운로드 (pick_bg.py로 눈으로 고른 뒤 사용).
    2026-07-29 디렉터 피드백: 검색 1순위 자동 사용은 소재 연관성이 떨어짐 → 시각 선별 도입."""
    key = load_keys().get("PEXELS_API_KEY") or os.environ.get("PEXELS_API_KEY")
    if not key or not vid_id:
        return None
    cache = os.path.join(ROOT, "assets", "bg_cache")
    os.makedirs(cache, exist_ok=True)
    import requests
    try:
        r = requests.get("https://api.pexels.com/videos/videos/%s" % vid_id,
                         headers={"Authorization": key}, timeout=20)
        r.raise_for_status()
        v = r.json()
        best_file, best_score = None, -1
        for f in v.get("video_files", []):
            w_, h_ = f.get("width") or 0, f.get("height") or 0
            if not f.get("link") or min(w_, h_) < 1080:
                continue
            score = (2000 if h_ > w_ else 0) + min(h_, 2200)
            if score > best_score:
                best_file, best_score = f, score
        if not best_file:
            return None
        dst = os.path.join(cache, "pexels_%d.mp4" % v["id"])
        if not os.path.exists(dst):
            _download(best_file["link"], dst)   # 2026-08-02 리뷰: .part+원자 교체
        print("배경 영상(지정): pexels id=%s (%ds, %dx%d) — Pexels License"
              % (v["id"], v.get("duration", 0), best_file.get("width", 0), best_file.get("height", 0)), flush=True)
        return dst
    except Exception as e:
        # 2026-08-02 리뷰: bg_id 실패는 main에서 즉시 기각되므로 '폴백' 문구는 모순 — 로그 정정
        print("배경 id 다운로드 실패(%s) — 기각 예정" % e, flush=True)
        return None

# ---------- TTS ----------
def tts_azure(text, mp3_path):
    """Azure Speech 공식 API (2026-08-04 디렉터 승인 S-004 — aitutor와 리소스 공유).

    edge-tts와 같은 보이스(SunHi/InJoon)를 SSML로 합성 — 문어체 조각을 어색하게
    읽던 문제("띄어쓰기를 이해 못 하는 느낌", 2026-08-04 디렉터)의 근본 대응.
    word boundary 이벤트로 edge-tts와 동일한 (초, 단어) 타이밍을 반환한다.
    키 없음/실패 시 None 반환 → 호출부가 edge-tts로 폴백."""
    keys = load_keys()
    key = keys.get("AZURE_SPEECH_KEY") or os.environ.get("AZURE_SPEECH_KEY")
    if not key:
        return None
    try:
        import azure.cognitiveservices.speech as speechsdk
        from xml.sax.saxutils import escape
        cfg = speechsdk.SpeechConfig(
            subscription=key,
            region=keys.get("AZURE_SPEECH_REGION") or os.environ.get("AZURE_SPEECH_REGION") or "koreacentral")
        cfg.set_speech_synthesis_output_format(
            speechsdk.SpeechSynthesisOutputFormat.Audio24Khz96KBitRateMonoMp3)
        synth = speechsdk.SpeechSynthesizer(speech_config=cfg, audio_config=None)
        boundaries = []

        def on_boundary(evt):
            # 구두점·문장 경계 이벤트는 제외 — 단어 팝인 타이밍에는 단어만
            bt = getattr(evt, "boundary_type", None)
            if bt is not None and bt != speechsdk.SpeechSynthesisBoundaryType.Word:
                return
            boundaries.append((evt.audio_offset / 1e7, evt.text))

        synth.synthesis_word_boundary.connect(on_boundary)
        ssml = ('<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="ko-KR">'
                '<voice name="%s"><prosody rate="%s">%s</prosody></voice></speak>'
                % (VOICE, RATE, escape(text)))
        result = synth.speak_ssml_async(ssml).get()
        if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
            detail = getattr(getattr(result, "cancellation_details", None), "error_details", result.reason)
            print("Azure TTS 실패(%s) → edge-tts 폴백" % str(detail)[:200], flush=True)
            return None
        with open(mp3_path, "wb") as f:
            f.write(result.audio_data)
        return boundaries
    except Exception as e:
        print("Azure TTS 예외(%s) → edge-tts 폴백" % str(e)[:200], flush=True)
        return None


async def tts_edge(text, mp3_path):
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


def tts_scene_sync(text, mp3_path):
    """Azure 우선, 실패 시 edge-tts 폴백 (같은 보이스라 톤 연속성 유지)."""
    b = tts_azure(text, mp3_path)
    if b is not None:
        return b, "azure"
    return asyncio.run(tts_edge(text, mp3_path)), "edge"

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
    # 2026-08-02 리뷰: 머리·꼬리 미매칭 단어가 한 시각에 뭉텅이 팝업되던 것을 균등 분할 외삽으로 교정
    #                 (voice 구어 ≠ lines 압축 자막이 기본 스타일이라 퍼지 매칭 실패는 일상적)
    first, last = known[0], known[-1]
    for i in range(len(times)):
        if times[i] is None:
            if i < first[0]:
                # 첫 매칭 이전: [0, first[1]] 균등 분할
                times[i] = first[1] * (i + 1) / (first[0] + 1)
            elif i > last[0]:
                # 마지막 매칭 이후: [last[1], dur] 균등 분할
                times[i] = last[1] + (dur - last[1]) * (i - last[0]) / (len(times) - last[0])
            else:
                prev = max([k for k in known if k[0] < i], key=lambda x: x[0])
                nxt = min([k for k in known if k[0] > i], key=lambda x: x[0])
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
    frames_dir = os.path.join(out_dir, "frames")
    # 이전 런 잔여 고번호 프레임(f01500+)이 ffmpeg 입력에 섞이지 않게 비우고 시작 (2026-08-02 리뷰)
    shutil.rmtree(frames_dir, ignore_errors=True)
    os.makedirs(frames_dir, exist_ok=True)
    total = int(total_dur * FPS)
    fact_counter, fact_nums = 0, {}
    for i, sc in enumerate(script["scenes"]):
        if sc.get("kind") == "fact":
            fact_counter += 1
            fact_nums[i] = "%02d" % fact_counter

    # 자막 팝인을 어절 단위 → 2어절 청크 단위로 (2026-08-04 디렉터: 단어 단위가 촐싹대고 어설픔)
    # 같은 줄 안에서 2어절씩 묶어 청크 첫 어절의 시각에 함께 등장시킨다.
    for tl in timeline:
        ct = list(tl["word_times"])
        i0 = 0
        while i0 < len(tl["dwords"]):
            line = tl["dwords"][i0]["line"]
            j = i0
            while j < len(tl["dwords"]) and tl["dwords"][j]["line"] == line:
                j += 1
            k = i0
            while k < j:
                for m in range(k, min(k + 2, j)):
                    ct[m] = tl["word_times"][k]
                k += 2
            i0 = j
        tl["chunk_times"] = ct

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
                    if lw > W - 90:
                        # 2026-08-02 리뷰: 44px 클램프 후에도 초과면 좌우 잘린 채 게시됨 — 명시 기각
                        sys.exit("기각: scene %d 줄 %d 폭 초과(%.0fpx > %dpx) — 줄을 나눠라"
                                 % (si, li, lw, W - 90))
                x = (W - lw) / 2
                y = y_cursor + li * line_h
                for w_ in line.split(" "):
                    # 2026-08-04: 청크 시각 + 완만한 등장 (스케일 진폭·수직 이동 축소 — '촐싹거림' 제거)
                    t_in = tl["chunk_times"][wi] - tl["start"]
                    a = clamp((local - t_in) / 0.28, 0, 1)
                    if a > 0:
                        s = ease_out_back(a)
                        col = ACCENT if tl["dwords"][wi]["hl"] else TEXT
                        alpha = int(255 * a * fade)
                        fs = load_font(int(line_font.size * (0.85 + 0.15 * s))) if abs(s - 1) > 0.01 else line_font
                        yo = (1 - a) * 14
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
    ap.add_argument("--keep-work", action="store_true",
                    help="work 디렉터리 보존 (디버깅용, 2026-08-02 리뷰)")
    args = ap.parse_args()
    with open(args.script_json, encoding="utf-8") as f:
        script = json.load(f)
    global VOICE, RATE
    nar = script.get("narrator", "female")
    VOICE = VOICES.get(nar, nar if "Neural" in str(nar) else VOICES["female"])
    RATE = script.get("rate") or RATES.get(nar, RATES["female"])
    print("성우: %s (%s, rate=%s)" % (VOICE, nar, RATE), flush=True)
    base = os.path.splitext(os.path.basename(args.script_json))[0]
    out_mp4 = args.out or os.path.join("out", base + ".mp4")
    work = os.path.join("out", "work_" + base)
    os.makedirs(work, exist_ok=True)

    # 0-0) 기각 소재 기계 대조 (2026-08-02 디렉터 승인 — 프롬프트 전용 규칙 3회 실패로 기계화)
    import check_topic
    hits = check_topic.check_script(args.script_json)
    if hits:
        sys.exit("기각: 영구금지 소재 키워드 일치(%s) — content/REJECTED.md 참조. "
                 "각도를 바꿔도 금지다, 소재를 교체하라" % ", ".join(hits))

    # 0) 자막 구조 하드게이트 (2026-07-29 실사고: CTA 3줄이 구독 문구와 겹침)
    # 2026-08-02 리뷰: 스키마 누락은 KeyError 원시 traceback 대신 명시적 '기각:'으로 —
    #                 헤드리스 세션이 로그만 보고 자가 수정하는 유일한 피드백 채널
    if not script.get("scenes"):
        sys.exit("기각: scenes 없음")
    for i, sc in enumerate(script["scenes"]):
        if not sc.get("lines") or not sc.get("voice"):
            sys.exit("기각: scene %d lines/voice 누락" % i)
        limit = 2 if sc.get("kind") == "cta" else 3
        if len(sc.get("lines", [])) > limit:
            sys.exit("기각: scene %d(%s) 자막 %d줄 — %s 씬은 최대 %d줄 (구독 문구 겹침 방지)"
                     % (i, sc.get("kind"), len(sc["lines"]), sc.get("kind"), limit))

    # 0-1b) 씬 문법 하드게이트 (2026-08-03 실사고: 지식 3비트를 body에 넣고 fact 씬이
    #       마무리 문장 1개뿐인 편이 게시됨 — 번호 카드는 fact 씬에만 붙으므로 시청자에겐
    #       '핵심 사실 1개짜리 영상'으로 보였고 디렉터가 규칙 위반으로 지적)
    kinds = [sc.get("kind") for sc in script["scenes"]]
    n_fact = kinds.count("fact")
    # 2026-08-03 디렉터 재확정: 규약 원문 '훅 하나, 핵심 사실 셋' — 3개 고정
    # (신설 당시 과거 관행에 맞춰 2~3으로 느슨하게 잡았다가 2개짜리가 통과해 지적받음)
    if n_fact != 3:
        sys.exit("기각: fact 씬 %d개 — 핵심 사실 카드는 정확히 3개여야 한다(훅 하나·사실 셋·반전). "
                 "지식 비트를 body에 숨기지 마라(번호 카드는 fact 씬에만 렌더된다)" % n_fact)
    if "twist" in kinds:
        first_twist = kinds.index("twist")
        if sum(1 for k in kinds[:first_twist] if k == "fact") < 2:
            sys.exit("기각: 반전(twist) 앞에 fact 씬이 2개 미만 — 사실을 쌓은 뒤 뒤집어야 반전이 성립한다")

    # 0-2) 채널 아이덴티티 하드게이트 (2026-07-31 실사고: 마지막 씬을 twist로 만들어
    #      음성 마무리 멘트와 화면 '1일 1지식 · 구독' 표시가 둘 다 누락된 채 발송됨)
    last = script["scenes"][-1]
    if last.get("kind") != "cta":
        sys.exit("기각: 마지막 씬 kind가 '%s' — 반드시 'cta'여야 화면 하단 구독 표시가 렌더된다"
                 % last.get("kind"))
    if not last.get("sub"):
        sys.exit("기각: cta 씬에 sub 없음 — 화면 하단 '1일 1지식 · 구독' 표시 누락")
    if "1일 1지식" not in last.get("voice", ""):
        sys.exit("기각: cta 발화에 '1일 1지식' 마무리 멘트 없음 — 채널 아이덴티티 필수")
    # 2026-07-31 디렉터 확정: 전 슬롯 '오늘도'로 통일 (하루 4~5편이라 '내일도'는 어색)
    # 2026-08-02 리뷰: sub도 실제 렌더되므로(하단 구독 표시) 검사 대상에 포함
    if "내일도" in last.get("voice", "") or "내일도" in last.get("sub", "") \
            or any("내일도" in l[0] for l in last.get("lines", [])):
        sys.exit("기각: cta에 '내일도' 사용 — 전 슬롯 '오늘도 1일 1지식, 구독으로 받아보세요.'로 통일")
    # 2026-07-31 실사고: 음성은 '구독으로 받아보세요'인데 자막 줄이 없어 화면에 안 나옴
    cta_text = " ".join(l[0] for l in last.get("lines", []))
    if "구독" not in cta_text:
        sys.exit("기각: cta 자막에 '구독으로 받아보세요' 줄 없음 — 발화와 자막이 불일치 "
                 "(정규형: lines=[[\"오늘도 1일 1지식\",...], [\"구독으로 받아보세요\",...]])")

    # 1) 씬별 TTS
    timeline = []
    cursor = LEAD_IN
    for i, sc in enumerate(script["scenes"]):
        mp3 = os.path.join(work, "s%02d.mp3" % i)
        boundaries, tts_engine = tts_scene_sync(sc["voice"], mp3)
        if not boundaries:
            sys.exit("기각: scene %d WordBoundary 0개 — 자막 동기 불가 (TTS 응답 이상, 재시도 필요)" % i)
        dur = media_duration(mp3)
        dws = display_words(sc)
        times = assign_times(dws, boundaries, dur)
        timeline.append({"start": cursor, "end": cursor + dur + SCENE_GAP, "mp3": mp3,
                         "dwords": dws, "word_times": [cursor + t for t in times]})
        cursor += dur + SCENE_GAP
        print("scene %d: %.2fs, words=%d, boundaries=%d, tts=%s" % (i, dur, len(dws), len(boundaries), tts_engine), flush=True)
    total_dur = cursor + TAIL
    # 길이 하드게이트 (2026-07-29 감사: '경고만'은 QA 자기채점과 함께 51.5초 발송을 통과시킴)
    # 2026-08-02 디렉터 확정: 하드 게이트 20~55s로 통일 (문서마다 다르던 수치 일원화)
    if total_dur > 55 or total_dur < 20:
        sys.exit("기각: 총 길이 %.1fs — 허용 범위(20~55s) 밖. 대본을 압축/보강해 재렌더하라" % total_dur)
    if total_dur > 50:
        print("경고: 총 길이 %.1fs — 50s 초과분은 리포트에 사유 한 줄 기록" % total_dur, flush=True)

    # 2) 배경 영상 — bg_id가 명시됐는데 실패하면 무선별 폴백 금지 (시각 선별 게이트 우회 방지)
    # 2026-08-04 디렉터 지시: 배경 1개는 지루하다 → bg_ids(2~3개)로 씬 경계에서 배경 전환
    bg_items = []   # {"kind": "video"|"photo", "path": ...}
    if not args.no_bg_video:
        ids = script.get("bg_ids") or ([script["bg_id"]] if script.get("bg_id") else [])
        if ids:
            # 배경 재사용 하드게이트 (2026-08-05): 다른 편에서 쓴 배경이면 기각 (사진 포함)
            dup = [v for v in ids[:3] if str(v) in used_bg_ids(exclude_script=args.script_json)]
            if dup:
                sys.exit("기각: 배경 %s 는 이미 다른 게시본에서 사용됨 — 피드에서 재탕처럼 보인다. "
                         "pick_bg.py 출력의 ⚠️ 표시를 피해 다른 배경을 골라라" % dup)
            for entry in ids[:3]:
                if isinstance(entry, str) and entry.startswith("photo:"):
                    p = fetch_bg_photo(entry.split(":", 1)[1])
                    if p is None:
                        sys.exit("기각: 지정 사진 %s 다운로드 실패 — pick_bg.py로 다시 고르거나 목록에서 제거하라" % entry)
                    bg_items.append({"kind": "photo", "path": p})
                else:
                    p = fetch_bg_by_id(entry)
                    if p is None:
                        sys.exit("기각: 지정 bg_id=%s 다운로드 실패 — pick_bg.py로 다시 고르거나 목록에서 제거하라" % entry)
                    bg_items.append({"kind": "video", "path": p})
        else:
            p = fetch_bg(script.get("bg_query", ""), total_dur)
            if p:
                bg_items = [{"kind": "video", "path": p}]
    video_bg = bool(bg_items)

    # 배경 전환 지점: 총 길이를 배경 수로 등분한 목표 시각에 가장 가까운 씬 경계로 스냅
    bg_segs = [total_dur]
    if len(bg_items) > 1:
        ends = [tl["end"] for tl in timeline[:-1]]
        cuts = sorted(set(min(ends, key=lambda e: abs(e - total_dur * k / len(bg_items)))
                          for k in range(1, len(bg_items))))
        bounds = [0.0] + cuts + [total_dur]
        bg_segs = [bounds[i + 1] - bounds[i] for i in range(len(bounds) - 1)]
        bg_items = bg_items[:len(bg_segs)]   # 경계가 겹쳐 줄었으면 배경 수도 맞춤

    # 3) 렌더 + BGM
    render(script, timeline, work, total_dur, script.get("chip", "오늘의 지식 · 1일 1지식"), video_bg)
    bgm = os.path.join(work, "bgm.wav")
    make_bgm(total_dur, bgm)

    # 4) 합성·인코딩
    cmd = ["ffmpeg", "-y"]
    if video_bg:
        nb = len(bg_items)
        for it in bg_items:
            if it["kind"] == "photo":
                cmd += ["-loop", "1", "-i", it["path"]]
            else:
                cmd += ["-stream_loop", "-1", "-i", it["path"]]
        cmd += ["-framerate", str(FPS), "-i", os.path.join(work, "frames", "f%05d.png"),
                "-i", bgm]
        scale = "scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,setsar=1,fps=%d" % (W, H, W, H, FPS)
        parts = []
        for i, (it, seg) in enumerate(zip(bg_items, bg_segs)):
            if it["kind"] == "photo":
                # 켄 번즈: 구간마다 줌 방향·초점을 바꿔 단조로움 방지. 총 줌 폭은 길이 무관 +0.45
                fr = max(int(seg * FPS) + FPS, FPS)
                zi = 0.45 / max(seg * FPS, 1)
                styles = [
                    "z='min(1.0+%.6f*on,1.5)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'" % zi,
                    "z='min(1.0+%.6f*on,1.5)':x='iw/2-(iw/zoom/2)':y='ih/3-(ih/zoom/2)'" % zi,
                    "z='max(1.45-%.6f*on,1.0)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'" % zi,
                ]
                parts.append(
                    "[%d:v]scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,"
                    "zoompan=%s:d=%d:s=%dx%d:fps=%d,eq=saturation=0.88:brightness=-0.02,"
                    "setsar=1,trim=duration=%.3f,setpts=PTS-STARTPTS[b%d]"
                    % (i, W * 2, H * 2, W * 2, H * 2, styles[i % 3], fr, W, H, FPS, seg, i))
            else:
                parts.append("[%d:v]%s,trim=duration=%.3f,setpts=PTS-STARTPTS[b%d]"
                             % (i, scale, seg, i))
        parts.append("%sconcat=n=%d:v=1:a=0[bgv]" % ("".join("[b%d]" % i for i in range(nb)), nb))
        parts.append("[bgv][%d:v]overlay=format=auto[vout]" % nb)
        vf = ";".join(parts)
        a_base = nb + 1
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
    # 텔레그램 봇 전송 한도 50MB — 배경 영상이 고디테일이면 CRF 20에서 12Mbps까지 튄다.
    # 2026-08-01 실사고: 49초짜리가 78MB로 나와 발송 실패. maxrate로 상한을 걸어 원천 차단한다.
    cmd += ["-filter_complex", ";".join(fl), "-map", "[vout]", "-map", "[aout]",
            "-map_metadata", "-1",   # 스톡 원본 메타데이터(GPS 등) 상속 차단 (2026-07-29 두바이 좌표 실사고)
            "-c:v", "libx264", "-preset", "medium", "-crf", "22",
            "-maxrate", "6M", "-bufsize", "12M", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "160k", "-t", str(total_dur), out_mp4]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=900)
    except subprocess.CalledProcessError as e:
        sys.exit("ffmpeg 인코딩 실패:\n%s" % e.stderr.decode(errors="ignore")[-2000:])
    except subprocess.TimeoutExpired:
        sys.exit("ffmpeg 인코딩 타임아웃(15분)")

    # 그래도 한도를 넘으면 CRF를 올려 가며 자동 재인코딩 (발송 실패 원천 차단)
    TG_LIMIT_MB = 45
    for crf in (26, 30):
        size_mb = os.path.getsize(out_mp4) / 1048576
        if size_mb <= TG_LIMIT_MB:
            break
        print("경고: %.1fMB — 텔레그램 한도 초과, crf %d로 재인코딩" % (size_mb, crf), flush=True)
        tmp = out_mp4 + ".shrink.mp4"
        try:
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", out_mp4,
                            "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
                            "-maxrate", "4M", "-bufsize", "8M", "-pix_fmt", "yuv420p",
                            "-c:a", "copy", "-map_metadata", "-1", tmp],
                           check=True, capture_output=True, timeout=900)
            os.replace(tmp, out_mp4)
        except Exception as e:
            print("재인코딩 실패: %s" % e, flush=True)
            if os.path.exists(tmp):   # 실패한 .shrink.mp4 잔여물 제거 (2026-08-02 리뷰)
                os.remove(tmp)
            break
    final_mb = os.path.getsize(out_mp4) / 1048576
    if final_mb > TG_LIMIT_MB:
        print("경고: 최종 %.1fMB — 여전히 한도 초과, 발송 시 파일 경로만 전달됨" % final_mb, flush=True)
    # 인코딩·크기검사까지 끝난 뒤 중간 산출물 정리 — 무인 반복 실행의 디스크 무한 누적 차단 (2026-08-02 리뷰)
    if not args.keep_work:
        shutil.rmtree(work, ignore_errors=True)
    print("완료: %s (%.1fs, %.1fMB, 배경=%s)"
          % (out_mp4, total_dur, final_mb, "영상" if video_bg else "그라데이션"))

if __name__ == "__main__":
    main()
