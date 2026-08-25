#!/usr/bin/env python3
# 숏츠 제작 파이프라인: 스크립트 JSON → edge-tts(단어 타이밍) → 배경영상(Pexels)+키네틱 자막 → BGM 믹스 → mp4
# 사용: .venv/bin/python3 pipeline/make_short.py content/2026-07-29.json --out out/2026-07-29.mp4
# 배경: script JSON의 "bg_query"(예: "eiffel tower")로 Pexels에서 세로 영상 검색.
#       keys.env에 PEXELS_API_KEY 필요. 없거나 실패하면 그라데이션 배경으로 폴백.
import argparse, asyncio, functools, glob, json, math, os, re, shutil, subprocess, sys, wave
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from bg_history import used_bg_ids   # 정본은 bg_history.py — pick_bg와 공유 (2026-08-23: 무거운 렌더러 임포트 없이 쓰도록 분리)

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
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def font_path():
    cands = [
        # 2026-08-11 고급화: Pretendard 우선 (OFL 오픈소스 — 상위 채널 표준 서체)
        os.path.join(ROOT, "assets", "fonts", "Pretendard-ExtraBold.otf"),
        os.path.join(ROOT, "assets", "fonts", "NotoSansCJKkr-Black.otf"),
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc",
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    ]
    for c in cands:
        if os.path.exists(c):
            return c
    sys.exit("한글 폰트를 찾을 수 없습니다 — setup.sh를 먼저 실행하세요")

FONT = font_path()
FONT_HOOK = os.path.join(ROOT, "assets", "fonts", "Pretendard-Black.otf")   # 훅·CTA용 최대 굵기
TTC_IDX = 1 if FONT.endswith("NotoSansCJK-Black.ttc") else 0

@functools.lru_cache(maxsize=None)   # 렌더 핫루프에서 폭 초과 줄마다 폰트 파일을 매 프레임 재로드하던 것 차단 (2026-08-23 감사)
def load_font(size, hook=False):
    try:
        if hook and os.path.exists(FONT_HOOK):
            return ImageFont.truetype(FONT_HOOK, size)
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

def fetch_bg(query):
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
# 2026-08-11 blind A/B (디렉터 선정): 남성 = HD(Hyunsu HD, eastus 신규 리소스) / 여성 = 현행(SunHi) 유지
HD_VOICE_MAP = {"ko-KR-InJoonNeural": ("ko-KR-Hyunsu:DragonHDLatestNeural", "+12%")}


def tts_azure(text, mp3_path):
    """Azure Speech 공식 API (2026-08-04 디렉터 승인 S-004 — aitutor와 리소스 공유).

    edge-tts와 같은 보이스(SunHi/InJoon)를 SSML로 합성 — 문어체 조각을 어색하게
    읽던 문제("띄어쓰기를 이해 못 하는 느낌", 2026-08-04 디렉터)의 근본 대응.
    word boundary 이벤트로 edge-tts와 동일한 (초, 단어) 타이밍을 반환한다.
    키 없음/실패 시 None 반환 → 호출부가 edge-tts로 폴백."""
    keys = load_keys()
    voice, rate = VOICE, RATE
    # 남성이면 HD 보이스·HD 리소스(eastus)로 라우팅 — HD 키가 없으면 현행 유지
    if VOICE in HD_VOICE_MAP and keys.get("AZURE_SPEECH_KEY_HD"):
        voice, rate = HD_VOICE_MAP[VOICE]
        key = keys["AZURE_SPEECH_KEY_HD"]
        region = keys.get("AZURE_SPEECH_REGION_HD", "eastus")
    else:
        key = keys.get("AZURE_SPEECH_KEY") or os.environ.get("AZURE_SPEECH_KEY")
        region = keys.get("AZURE_SPEECH_REGION") or os.environ.get("AZURE_SPEECH_REGION") or "koreacentral"
    if not key:
        return None
    try:
        import azure.cognitiveservices.speech as speechsdk
        from xml.sax.saxutils import escape
        cfg = speechsdk.SpeechConfig(subscription=key, region=region)
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
                % (voice, rate, escape(text)))
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
    # 2026-08-08: 숫자+단위를 한글 수사로 선변환 — TTS의 고유어/한자어 선택 실수("열두개월") 원천 차단
    from voice_clone import normalize_ko
    text = normalize_ko(text)
    b = tts_azure(text, mp3_path)
    if b is not None:
        return b, "azure"
    return asyncio.run(tts_edge(text, mp3_path)), "edge"

def media_duration(path):
    out = subprocess.run(["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                          "-of", "csv=p=0", path], capture_output=True, text=True)
    try:
        return float(out.stdout.strip())
    except ValueError:
        sys.exit("기각: %s 길이 판독 불가(ffprobe 출력 '%s') — 파일 손상/0바이트, TTS 재합성 필요"
                 % (os.path.basename(path), out.stdout.strip()[:40]))

# ---------- 타이밍 매핑 ----------
def display_words(scene):
    """어절별 하이라이트 여부 리스트 — 렌더 루프가 wi 순번으로 조회 (2026-08-23 감사: line·word 키는 미사용이라 불리언으로 축소)."""
    ws = []
    for line, hl in scene["lines"]:
        for w in line.split(" "):
            ws.append(any(h in w for h in hl))
    return ws


# ---------- 렌더 ----------
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

def render(script, timeline, out_dir, total_dur, channel_chip, video_bg, fx_underline=False, light_bg=False):
    """video_bg=True → 투명 오버레이 PNG(+스크림), False → 그라데이션 JPG."""
    if not video_bg:
        BG = make_bg()
        GA = make_glow(520, ACCENT, 26)
        GB = make_glow(640, (90, 110, 220), 22)
    F_BIG, F_MED = load_font(92, hook=True), load_font(78)
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

    # 텍스트 그림자용 헬퍼
    def text_sh(d, xy, s, font, fill):
        # 2026-08-08 품질 감사: 흰 트럭·크롬·LED 위 흰 글자 저대비 실측 — 얇은 외곽선 추가 (그림자와 병행)
        a = fill[3] if len(fill) > 3 else 255
        x, y = xy
        if video_bg:
            d.text((x + 3, y + 3), s, font=font, fill=(0, 0, 0, min(200, a)))
        d.text(xy, s, font=font, fill=fill, stroke_width=2, stroke_fill=(0, 0, 0, min(190, a)))

    # 2026-08-08 품질 감사: 균일 스크림이 배경을 전체적으로 탁하게 만듦 — 세로 그라데이션 1회 프리렌더
    # (상단 칩존 150 / 중앙 95 — 배경이 살아남 / 자막존 160 — 대비 확보 / 하단 140)
    scrim = Image.new("RGBA", (W, H))
    _sd = ImageDraw.Draw(scrim)
    # 흰 도판(퀴즈·비교 이미지) 배경은 스크림이 과하면 회색으로 죽는다 → --light-bg로 약화 (2026-08-15)
    _k = 0.42 if light_bg else 1.0
    for _y in range(H):
        r = _y / H
        if r < 0.16:  a_ = 150
        elif r < 0.34: a_ = int(150 + (95 - 150) * (r - 0.16) / 0.18)
        elif r < 0.40: a_ = int(95 + (160 - 95) * (r - 0.34) / 0.06)
        elif r < 0.72: a_ = 160
        elif r < 0.80: a_ = int(160 + (140 - 160) * (r - 0.72) / 0.08)
        else:          a_ = 140
        _sd.line([(0, _y), (W, _y)], fill=(0, 0, 0, int(a_ * _k)))

    for fi in range(total):
        t = fi / FPS
        if video_bg:
            im = scrim.copy()
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
        # 2026-08-08 품질 감사(4방향 전원 합의): 첫 프레임이 곧 피드 인상 — LEAD_IN 구간에도 훅을 그린다
        if si is None and t < timeline[0]["start"]:
            si = 0
        if si is not None:
            sc, tl = script["scenes"][si], timeline[si]
            local = max(0.0, t - tl["start"])
            fade = clamp((tl["end"] - t) / 0.20, 0, 1) if tl["end"] - t < 0.20 else 1.0
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
                # 긴 줄은 화면 폭에 맞게 폰트 자동 축소 — 여백 160px(양쪽 80px씩, 2026-08-05 디렉터: 글자가 화면 끝에 붙음)
                line_font = font
                lw = d.textlength(line, font=line_font)
                if lw > W - 160:
                    line_font = load_font(max(44, int(font.size * (W - 160) / lw)))
                    lw = d.textlength(line, font=line_font)
                    if lw > W - 160:
                        # 2026-08-02 리뷰: 44px 클램프 후에도 초과면 좌우 잘린 채 게시됨 — 명시 기각
                        sys.exit("기각: scene %d 줄 %d 폭 초과(%.0fpx > %dpx) — 줄을 나눠라"
                                 % (si, li, lw, W - 160))
                x = (W - lw) / 2
                y = y_cursor + li * line_h
                # 2026-08-07 디렉터: 어절 팝인 폐지 — 대사 요약 자막을 성우 발화에 억지로 맞추다
                # '지나간 얘기의 자막이 뒤늦게 두둥' 하는 어긋남이 생겼다. 줄 단위로 순차 등장하되
                # 등장 시각은 씬 내 균등 배분(발화 매칭 의존 제거), 0.25s 페이드인만 남긴다.
                n_lines = len(sc["lines"])
                line_gap = 0.55 if n_lines > 1 else 0.0
                t_in = li * line_gap
                # 훅 첫 줄은 0프레임부터 완성 상태 (페이드 없음 — 스와이프 판정은 첫 프레임에서 난다)
                a = 1.0 if (si == 0 and li == 0) else clamp((local - t_in) / 0.15, 0, 1)
                if a > 0:
                    alpha = int(255 * a * fade)
                    for w_ in line.split(" "):
                        col = ACCENT if tl["dwords"][wi] else TEXT
                        text_sh(d, (x, y), w_, line_font, col + (alpha,))
                        if fx_underline and col == ACCENT:
                            uw = d.textlength(w_, font=line_font)
                            uy = y + line_font.size * 1.06
                            d.line([(x, uy), (x + uw, uy)], fill=ACCENT + (alpha,),
                                   width=max(3, int(line_font.size * 0.06)))
                        x += d.textlength(w_ + " ", font=line_font)
                        wi += 1
                else:
                    wi += len(line.split(" "))
            if sc.get("kind") == "cta" and sc.get("sub"):
                a = clamp((local - 0.6) / 0.3, 0, 1)   # 2026-08-08: CTA는 종료 전 완전 노출 (noon 편 실사고)
                text_sh(d, ((W - d.textlength(sc["sub"], font=F_SUB)) / 2, H * 0.56),
                        sc["sub"], F_SUB, DIM + (int(255 * a * fade),))
        d.rectangle([0, H - 14, W * (t / total_dur), H], fill=ACCENT + (230,))
        if video_bg:
            im.save(os.path.join(out_dir, "frames", "f%05d.png" % fi), compress_level=1)
        else:
            im.convert("RGB").save(os.path.join(out_dir, "frames", "f%05d.jpg" % fi), quality=92)
        if fi % 150 == 0:
            print("frame %d/%d" % (fi, total), flush=True)

# ---------- BGM ----------
def make_bgm(dur, path, lift_spans=None):
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
    # 2026-08-08: twist 구간 게인 리프트(1.0→1.30, 0.4s 램프) — 반전 긴장 상승, 이후 재정규화
    if lift_spans:
        env = np.ones(len(audio))
        for s0, e0 in lift_spans:
            i0, i1 = int(s0 * SR), min(int(e0 * SR), len(audio))
            r = int(0.4 * SR)
            if i1 - i0 > 2 * r:
                env[i0:i0 + r] = np.linspace(1.0, 1.30, r)
                env[i0 + r:i1 - r] = 1.30
                env[i1 - r:i1] = np.linspace(1.30, 1.0, r)
        audio *= env
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
    # 2026-08-09 실험 4종 (품질 감사 experiment 등급 — 디렉터 A/B용, 채택 전 기본 off)
    ap.add_argument("--no-fx-xfade", dest="fx_xfade", action="store_false", help="크로스페이드 끄기")
    ap.add_argument("--no-fx-zoom", dest="fx_zoom", action="store_false", help="슬로우 줌 끄기")
    ap.set_defaults(fx_xfade=True, fx_zoom=True)   # 2026-08-09 디렉터 채택 ("0+1+2로") — 기본 on
    ap.add_argument("--fx-underline", action="store_true", help="강조어 ACCENT 밑줄")
    ap.add_argument("--light-bg", action="store_true", help="흰 도판 배경용 약한 스크림 (2026-08-15)")
    ap.add_argument("--fx-sfx", action="store_true", help="배경 전환 소프트 스윕음 (-18dB)")
    ap.add_argument("--no-fx-cine", dest="fx_cine", action="store_false", help="시네마틱 톤 끄기")
    ap.set_defaults(fx_cine=True)   # 2026-08-11 디렉터 채택 ("영상은 일단 ㅇㅋ") — 기본 on
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
        # 2026-08-15: 화면 자체가 콘텐츠인 씬(퀴즈 문제 등)은 "no_sub": true로 자막을 비울 수 있다.
        # 그 외에는 무자막이 곧 사고이므로 기존대로 기각한다.
        if sc.get("no_sub"):
            sc["lines"] = []
            if not sc.get("voice"):
                sys.exit("기각: scene %d voice 누락 (자막을 비웠으면 나레이션은 필수다)" % i)
            continue
        if not sc.get("lines") or not sc.get("voice"):
            sys.exit("기각: scene %d lines/voice 누락" % i)
        # 2026-08-14 감사: 스키마 이상은 원시 traceback 대신 명시적 기각 (578행 설계 원칙)
        for li, ln in enumerate(sc["lines"]):
            if not (isinstance(ln, (list, tuple)) and len(ln) == 2 and isinstance(ln[0], str)
                    and isinstance(ln[1], (list, tuple))):
                sys.exit("기각: scene %d 줄 %d 형식 오류 — 각 줄은 [\"자막 텍스트\", [강조어절...]] 2요소여야 한다"
                         % (i, li))
            # 강조어가 그 줄에 실제로 없으면 조용히 소실된다 — 하드 기각 (2026-08-14 감사)
            for hw in ln[1]:
                if not isinstance(hw, str) or hw not in ln[0]:
                    sys.exit("기각: scene %d 강조어 '%s'가 줄 '%s'에 없음 — 강조는 자막 어절 그대로 적어라"
                             % (i, hw, ln[0][:24]))
        limit = 2 if sc.get("kind") == "cta" else 3
        if len(sc.get("lines", [])) > limit:
            sys.exit("기각: scene %d(%s) 자막 %d줄 — %s 씬은 최대 %d줄 (구독 문구 겹침 방지)"
                     % (i, sc.get("kind"), len(sc["lines"]), sc.get("kind"), limit))

    # 0-0a2) 폰트 미지원 글자 게이트 (2026-08-14 실사고 2회: 스토리 🔗 두부, 자막 ⅔ 두부 ☒)
    _bad_re = re.compile(u"[\u2150-\u215F\u2460-\u24FF\u2600-\u27BF\u2B00-\u2BFF"
                         u"\U0001F000-\U0001FAFF\u2610-\u2612]")
    for i, sc in enumerate(script["scenes"]):
        for ln_, _h in sc.get("lines", []):
            hit = _bad_re.search(ln_)
            if hit:
                sys.exit("기각: scene %d 자막에 폰트 미지원 글자 %r — 분수·이모지·기호는 ☒로 깨진다. 한글·숫자로 풀어 써라 (예: ⅔ → 3분의 2)" % (i, hit.group(0)))

    # 0-0a3) 15시(대박 슬롯) 공유 트리거 게이트 (2026-08-14 결산: 공유 0 → 도달 정체가 성장 병목)
    #        당일성·시한·행동 지시 중 최소 하나가 훅/반전에 문장으로 있어야 한다.
    # 2026-08-16 밤 확대: 16시 전용 → **전 슬롯**. 실측이 결정적이다 —
    #   시한성 있는 편 30.4만/16.0만/7.5만 vs 없는 편 203/164/152 (약 1,500배).
    #   "오늘 해야 할 이유"가 없으면 아무리 좋은 지식도 200회에서 끝난다.
    _sc = script["scenes"]
    _txt = " ".join([_sc[0].get("voice", "")] +
                    [s_.get("voice", "") for s_ in _sc if s_.get("kind") == "twist"])
    _trig = ("당일성", r"오늘|내일|이번 주|이번 주말|밤|새벽|지금"), \
            ("시한", r"마지막|까지|남았|끝나|마감|한정|올해만|다시 보려면"), \
            ("행동", r"보세요|해보세요|나가|확인해|재보|챙기|눌러|기억해|찾아보")
    _hit = [n for n, p in _trig if re.search(p, _txt)]
    if not _hit:
        sys.exit("기각: 공유 트리거가 없다 — 훅이나 반전에 "
                 "①당일성(오늘/내일/오늘 밤) ②시한(마지막·~까지) ③행동 지시(보세요·확인해보세요) "
                 "중 최소 하나를 문장으로 넣어라.\n  실측: 시한성 있는 편 30.4만·16.0만·7.5만 / 없는 편 203·164·152 — **1,500배 차이다.**\n  '왜 오늘 이걸 봐야 하는가'에 한 문장으로 답하지 못하면 그 소재는 버려라.")
    print("공유 트리거: %s ✓" % ", ".join(_hit), flush=True)

    # 0-0a1) 훅 첫 줄 완결성 게이트 (2026-08-16 — YouTube Studio 조언 + 오늘 5편 첫 프레임 실사)
    # 실사 결과: 5편 중 3편이 첫 1초에 미완성 문장만 떴다("이불을 자주 빨아도" / "여름에 피부가
    #   번들거리면" / "결혼 전에 산 주식"). '그래서 뭐?'가 둘째 줄에 가서야 나오는데,
    #   Shorts 피드 시청자는 그때까지 기다려주지 않는다(채널 스와이프 통과율 36.2%).
    # 규칙: 훅 첫 줄은 그 한 줄만 읽어도 긴장이 서야 한다.
    #   ✗ 조건절로 끝남(~면/~아도/~어도/~라도/~지만) — 답이 유예된다
    #   ✗ 조사 없는 명사구로 끝남 — 문장이 아니다
    #   ○ 행동 요구("한 발로 서 보세요") / 완결 정보("오늘 밤 최대 250mm") / 단정("진드기는 안 죽습니다")
    _hook = next((sc for sc in script["scenes"] if sc.get("kind") == "hook"), None)
    if _hook and _hook.get("lines"):
        _first = _hook["lines"][0][0].strip().rstrip(",")
        if re.search(r"(면|아도|어도|여도|라도|지만|는데|은데|다가|려면)$", _first):
            sys.exit(
                "기각: 훅 첫 줄이 조건절이라 1초 안에 답이 없다 — %r\n"
                "  Shorts 피드는 첫 1~3초에 스와이프가 갈린다. 첫 줄만 읽고도 '어?' 소리가 나야 한다.\n"
                "  고치는 법: 결론을 첫 줄로 끌어올려라 "
                "(예: '이불을 자주 빨아도' → '찬물로 빨면 진드기는 안 죽습니다')." % _first)
        _last_word = _first.split()[-1] if _first.split() else ""
        # 숫자가 든 마지막 어절은 완결 정보로 본다 ("최대 250mm", "43초", "9,400억 원")
        if not (re.search(r"(다|요|까|나|죠|음|것|\?|!)$", _first) or re.search(r"\d", _last_word)):
            sys.exit(
                "기각: 훅 첫 줄이 명사구로 끝나 문장이 아니다 — %r\n"
                "  첫 1초에 뜨는 것은 제목이 아니라 **말**이어야 한다.\n"
                "  고치는 법: 서술어를 붙여 한 문장으로 끝내라 "
                "(예: '결혼 전에 산 주식' → '결혼 전에 산 주식도 나눠야 합니다')." % _first)

    # 0-0a3) 시각·자연현상 인과 게이트 (2026-08-17 밤 실사고: 거제 편 삭제)
    # 사고: "새벽 만조와 겹쳐 배수구가 막혔다"로 냈으나 실제로는 **새벽 4:56이 간조**였다
    #   (지세포 조석표: 만조 11:29·23:27 / 간조 04:56·17:15). 침수 시각 새벽 3~4시는
    #   만조가 아니라 간조 직전이었다. 매체 보도를 그대로 옮기고 조석표를 확인하지 않았다.
    #   현장 피해자가 댓글로 지적했고 전 채널에서 삭제했다.
    # 규칙: **만조·간조·일출·일몰·월출·조수처럼 공식 데이터가 존재하는 자연현상을
    #   인과로 쓸 때는, sources에 그 1차 데이터 출처가 반드시 있어야 한다.**
    _TIDE = r"(만조|간조|밀물|썰물|조수|사리|대조기|일출|일몰|월출|월몰|남중)"
    _sc_text = " ".join((sc.get("voice") or "") + " " + " ".join(l[0] for l in sc.get("lines", []))
                        for sc in script["scenes"])
    if re.search(_TIDE, _sc_text):
        _src = " ".join(script.get("sources", []))
        _OK = r"(국립해양조사원|해양조사원|khoa|조석표|물때|바다타임|천문연구원|KASI|기상청 조석)"
        if not re.search(_OK, _src):
            sys.exit(
                "기각: 조석·천문 현상을 인과로 쓰면서 1차 데이터 출처가 없다.\n"
                "  대본에 '%s' 류가 나오는데 sources에 국립해양조사원·조석표·천문연 근거가 없다.\n"
                "  ⚠️ 실사고(2026-08-17): 매체 보도만 믿고 '새벽 만조'라 했으나 실제는 간조였다 — 전 채널 삭제.\n"
                "  **시각과 수치는 매체가 아니라 원 데이터로 확인하라.** 조석: khoa.go.kr / badatime.com"
                % re.search(_TIDE, _sc_text).group(0))

    # 0-0a2) 통시 일반화 게이트 (2026-08-16 실사고 — 밥그릇 편 게시 후 삭제)
    # 디렉터: "제발 논란은 만들지 말자. 지식 정보 전달인데 사기를 치면 안 되는데."
    # 사고: "한국만 삼국시대부터 금속 그릇을 써 왔습니다" → 삼국시대 금속기는 상류층 부장품이고
    #   일반민은 토기·목기였다(한국민족문화대백과 '식기'). 지배층을 전 국민으로 확대한 일반화라
    #   "사기 친다"는 댓글이 달렸고 편이 삭제됐다. 원인은 출처 개수(2개)는 채웠으나
    #   출처가 뒷받침하지 않는 범위까지 말한 것 — 역사 부분의 근거가 블로그성 매체였다.
    _ERA = r"(삼국시대|고려시대|조선시대|신라|백제|고구려|예로부터|옛날부터|고대부터|수천 ?년|수백 ?년)"
    _CONT = r"(써 ?왔|썼|사용해 ?왔|먹어 ?왔|해 ?왔|이어져|전통이|내려온)"
    _SCOPE = r"(양반|귀족|왕실|지배층|상류층|서민|백성|일부|주로|중심으로|무덤|부장품|기록|출토|추정)"
    for _i, _sc in enumerate(script["scenes"]):
        for _ln in _sc.get("lines", []) + [[_sc.get("voice", "")]]:
            _t = _ln[0] if _ln else ""
            if re.search(_ERA, _t) and re.search(_CONT, _t) and not re.search(_SCOPE, _t):
                sys.exit(
                    "기각: scene %d 통시 일반화 — %r\n"
                    "  옛 시대부터 '쭉 그래 왔다'고 쓰려면 **누가** 그랬는지 밝혀야 한다. 옛 시대의 "
                    "금속기·비단·약재 따위는 대개 지배층 것이었고 일반민은 달랐다.\n"
                    "  고치는 법: (1) 범위를 넣어라 — '왕실에서는', '기록에 남은 것은' "
                    "(2) 시대를 특정하라 — '조선 후기 유기는' (3) 통시 주장을 버리고 현재만 말하라.\n"
                    "  실사고: 밥그릇 편(2026-08-16) '한국만 삼국시대부터 금속 그릇을 써 왔습니다' → 게시 후 삭제."
                    % (_i, _t[:60]))

    # 0-0b) 자막 문장부호·문구 게이트 (2026-08-14 디렉터: "= 너무 많이 쓴다 — 수식·킥일 때만")
    eq_lines = [(i, ln[0]) for i, sc in enumerate(script["scenes"]) if sc.get("kind") != "cta"
                for ln in sc.get("lines", []) if "=" in ln[0]]
    if len(eq_lines) > 1:
        sys.exit("기각: 자막 등호(=) %d회(%s) — 편당 최대 1회, 양변이 숫자+단위인 환산식일 때만"
                 % (len(eq_lines), "; ".join("scene %d '%s'" % (i, t[:20]) for i, t in eq_lines)))
    # 2026-08-14 디렉터 2차 강화: 등호는 수치 등식만 — 바로 앞·뒤 어절에 둘 다 숫자가 있어야 한다
    # ("지방 1kg = 7,700kcal" ✓ / "식빵 두 쪽 = 밥 3분의 2공기" ✗ — 사물이 오면 문장으로 풀어라)
    for i, t in eq_lines:
        left, right = t.split("=", 1)
        lw = left.strip().split(" ")[-1] if left.strip() else ""
        rw = right.strip().split(" ")[0] if right.strip() else ""
        if not (re.search(r"\d", lw) and re.search(r"\d", rw)):
            sys.exit("기각: scene %d 등호 '%s' — 등호는 양변이 숫자+단위인 환산식만 허용"
                     "(디렉터 2026-08-14: '수치 비교일 때만'). 문장으로 풀어 써라 (예: '식빵 두 쪽 = 밥 3분의 2공기' → '식빵 두 쪽이면 밥 3분의 2공기')" % (i, t[:30]))
    for i, sc in enumerate(script["scenes"]):
        v = sc.get("voice", "")
        for sym in "=→×±":
            if sym in v:
                print("경고: scene %d 나레이션에 기호 '%s' — TTS가 묵음 처리해 의미가 사라진다. 말로 풀어 써라" % (i, sym), flush=True)
        if re.search(r"(^|[ ,])사실(은|,| )", v):
            print("경고: scene %d 나레이션에 부사 '사실' — 금지어다(2026-08-12 디렉터). 명사 용법이면 무시" % i, flush=True)
        if re.search(r"\d+번(?![째0-9])", v):
            print("경고: scene %d '%s번' — 발음 모호(이번/두 번). 횟수면 '두 번'처럼 한글로 쓰라"
                  % (i, re.search(r"(\d+)번(?![째0-9])", v).group(1)), flush=True)

    # 0-0c) 자막-나레이션 정합 경고 (2026-08-12 규칙의 기계화 — 오탐 여지가 있어 경고만, 기각 아님)
    def _core_words(s_):
        return [w for w in re.sub(r"[^\w가-힣 ]", " ", s_).split()
                if w and not re.search(r"[0-9A-Za-z]", w) and len(w) >= 2]
    for i, sc in enumerate(script["scenes"]):
        if sc.get("kind") == "cta":
            continue
        v = sc.get("voice", "")
        miss = [w for ln in sc.get("lines", []) for w in _core_words(ln[0])
                if w not in v and w[:2] not in v]
        if miss:
            print("경고: scene %d 자막 어절 %s — 나레이션에 없는 말이다. 자막은 나레이션의 같은 단어로 (숫자·단위 표기 차이는 무시해도 됨)"
                  % (i, miss), flush=True)

    # 0-1c) 강조 분량 게이트 (2026-08-08 품질 감사: 줄 절반이 노랑이면 강조가 죽는다 — cta 고정 블록은 제외)
    for i_, sc_ in enumerate(script["scenes"]):
        if sc_.get("kind") == "cta":
            continue
        # 대조 쌍 예외 (2026-08-15 디렉터: "양·음·위·아래" 같은 대비어는 강조가 곧 의미다)
        # 씬에 "hl_pair": true 를 두면 줄당 2어절·씬당 4어절까지 허용한다.
        pair = bool(sc_.get("hl_pair"))
        per_line, per_scene = (2, 4) if pair else (1, 2)
        tot_hl = 0
        for ln_, hl_ in sc_.get("lines", []):
            if len(hl_) > per_line:
                sys.exit("기각: scene %d 줄 '%s' 강조 %d어절 — 줄당 %d어절만 (강조는 아껴야 강조다)"
                         % (i_, ln_[:20], len(hl_), per_line))
            tot_hl += len(hl_)
        if tot_hl > per_scene:
            sys.exit("기각: scene %d 강조 합계 %d어절 — 씬당 %d어절 이내" % (i_, tot_hl, per_scene))

    # 0-1c-2) 영상 전체 강조 예산 (2026-08-24 디렉터: "강조 터무니 없게 하지 말고 정말 핵심만")
    #   씬당 게이트는 지키면서 '모든 줄에 하나씩' 넣는 패턴이 실측됐다(8/24 pm: 12줄에 강조 12개,
    #   '옷까지·셀카를·끝' 같은 비핵심 어절). 전부 노랑이면 아무것도 노랑이 아니다 —
    #   cta 제외 전체 줄의 절반까지만 강조를 허용한다. 대부분의 줄은 강조 []가 정상이다.
    _body = [(ln, hl) for sc in script["scenes"] if sc.get("kind") != "cta"
             for ln, hl in sc.get("lines", [])]
    _n_hl = sum(1 for _, hl in _body if hl)
    if _body and _n_hl * 2 > len(_body):
        sys.exit("기각: 강조 줄 %d/%d — 전체 줄의 절반 이내만 (핵심 숫자·반전어·고유명사에만 강조. "
                 "나머지 줄은 [] 로 비워라)" % (_n_hl, len(_body)))

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
    cta_text = " ".join(l[0] for l in last.get("lines", []))
    # 2026-08-11 디렉터 승인 변형: 태극기·광복절 시리즈(8/15까지) 한정 CTA —
    #   "다가오는 8월 15일, 올바른 태극기 정보 받아가세요." (구독 멘트 대신 날짜+행동 안내)
    #   구분 조건: 발화에 '태극기'와 '8월 15일'이 함께 있으면 이 변형으로 검증한다.
    is_flag_cta = "태극기" in last.get("voice", "") and "8월 15일" in last.get("voice", "")
    if is_flag_cta:
        if "1일 1지식" not in last.get("sub", ""):
            sys.exit("기각: 태극기 CTA의 sub에 '1일 1지식' 없음 — 채널 표기는 유지해야 한다")
        if "태극기" not in cta_text or "8월 15일" not in cta_text:
            sys.exit("기각: 태극기 CTA 자막에 '8월 15일'/'태극기' 누락 — 발화와 자막 불일치")
    else:
        if "1일 1지식" not in last.get("voice", ""):
            sys.exit("기각: cta 발화에 '1일 1지식' 마무리 멘트 없음 — 채널 아이덴티티 필수")
        # 2026-07-31 디렉터 확정: 전 슬롯 '오늘도'로 통일 (하루 4~5편이라 '내일도'는 어색)
        # 2026-08-02 리뷰: sub도 실제 렌더되므로(하단 구독 표시) 검사 대상에 포함
        if "내일도" in last.get("voice", "") or "내일도" in last.get("sub", "") \
                or any("내일도" in l[0] for l in last.get("lines", [])):
            sys.exit("기각: cta에 '내일도' 사용 — 전 슬롯 '오늘도 1일 1지식, 구독으로 받아보세요.'로 통일")
        # 2026-07-31 실사고: 음성은 '구독으로 받아보세요'인데 자막 줄이 없어 화면에 안 나옴
        if "구독" not in cta_text:
            sys.exit("기각: cta 자막에 '구독으로 받아보세요' 줄 없음 — 발화와 자막이 불일치 "
                     "(정규형: lines=[[\"오늘도 1일 1지식\",...], [\"구독으로 받아보세요\",...]])")

    # 0-0d) 자막 폭 선행 게이트 (2026-08-14 감사: 폭 초과가 TTS 합성·배경 다운로드·렌더를 다 마친
    #        뒤에야 기각되던 늦은 실패 — 같은 폰트·같은 축소 규칙으로 렌더 전에 판정한다.
    #        렌더 루프 안의 기존 검사는 최후 방어선으로 유지)
    _wd = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    for i, sc in enumerate(script["scenes"]):
        _base = load_font(92, hook=True) if sc.get("kind") in ("hook", "cta") else load_font(78)
        for li, (ln_, _hl) in enumerate(sc["lines"]):
            _lw = _wd.textlength(ln_, font=_base)
            if _lw > W - 160:
                _shr = load_font(max(44, int(_base.size * (W - 160) / _lw)))
                if _wd.textlength(ln_, font=_shr) > W - 160:
                    sys.exit("기각: scene %d 줄 %d 폭 초과 — 최소 폰트(44px)로도 화면을 넘는다. 줄을 나눠라: '%s…'"
                             % (i, li, ln_[:24]))

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
        # 2026-08-14 감사: 어절별 시각 매핑은 2026-08-07 어절 팝인 폐지 후 아무도 읽지 않는 계산이었다 — 제거
        timeline.append({"start": cursor, "end": cursor + dur + SCENE_GAP, "mp3": mp3,
                         "dwords": dws})
        cursor += dur + SCENE_GAP
        print("scene %d: %.2fs, words=%d, boundaries=%d, tts=%s" % (i, dur, len(dws), len(boundaries), tts_engine), flush=True)
    total_dur = cursor + TAIL
    # 길이 하드게이트 (2026-07-29 감사: '경고만'은 QA 자기채점과 함께 51.5초 발송을 통과시킴)
    # 2026-08-02 디렉터 확정: 하드 게이트 20~55s로 통일 (문서마다 다르던 수치 일원화)
    if total_dur > 55 or total_dur < 20:
        sys.exit("기각: 총 길이 %.1fs — 허용 범위(20~55s) 밖. 대본을 압축/보강해 재렌더하라" % total_dur)
    if total_dur > 50:
        print("경고: 총 길이 %.1fs — 50s 초과분은 리포트에 사유 한 줄 기록" % total_dur, flush=True)

    # 인스타 커버 시점 기록 (2026-08-05 디렉터: 커버는 훅 텍스트가 전부 노출된 첫 장면):
    # 훅 씬 마지막 어절 등장 시각 + 팝인 0.28s + 여유 → meta.json의 ig_thumb_ms로.
    # upload_instagram.py가 이 값을 릴스 thumb_offset으로 쓴다.
    meta_path = os.path.splitext(args.script_json)[0] + ".meta.json"
    if os.path.exists(meta_path):
        try:
            m = json.load(open(meta_path, encoding="utf-8"))
            # 2026-08-08: 훅 노출은 줄 스태거가 결정 (첫 줄 0s + 이후 줄 0.55s 간격 + 0.15s 페이드)
            m["ig_thumb_ms"] = int((LEAD_IN + 0.55 * max(0, len(script["scenes"][0]["lines"]) - 1) + 0.30) * 1000)
            tmp = meta_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(m, f, ensure_ascii=False, indent=2)
            os.replace(tmp, meta_path)
            print("ig_thumb_ms=%d 기록 (인스타 커버 시점)" % m["ig_thumb_ms"], flush=True)
        except Exception as e:
            print("meta ig_thumb_ms 기록 실패(%s) — 커버는 기본값 사용" % e, flush=True)

    # 2) 배경 영상 — bg_id가 명시됐는데 실패하면 무선별 폴백 금지 (시각 선별 게이트 우회 방지)
    # 2026-08-04 디렉터 지시: 배경 1개는 지루하다 → bg_ids(2~3개)로 씬 경계에서 배경 전환
    bg_items = []   # {"kind": "video"|"photo", "path": ...}
    # 씬 배경 키 정규화 (2026-08-20 실사고: 세션이 씬에 "bg_id"로 써서 조용히 무시됨 →
    # bg_query 검색 폴백이 '사이렌 타워'로 장대축제 영상을 골라 42초 단일 배경으로 게시됐다.
    # 별칭을 흡수해 씬별 모드로 태우고, 다시는 조용히 버리지 않는다)
    for sc in script["scenes"]:
        if not sc.get("bg") and sc.get("bg_id"):
            sc["bg"] = sc.pop("bg_id")
    scene_bg_mode = (not args.no_bg_video) and all(sc.get("bg") for sc in script["scenes"])
    if (not args.no_bg_video) and not scene_bg_mode and any(sc.get("bg") for sc in script["scenes"]):
        sys.exit("기각: 일부 씬에만 bg가 있다 — 씬별 배경은 전 씬에 지정하거나 전부 빼라 (조용한 폴백 금지)")
    if scene_bg_mode:
        # 씬별 배경 (2026-08-07 디렉터: "각 페이즈마다 알맞은 영상" — 롱폼에서 검증된 방식을 쇼츠로).
        # 각 씬이 "bg"로 자기 화면을 지정한다: 숫자=Pexels 영상, "photo:<id>"=사진(켄 번즈).
        # 연속 씬이 같은 bg면 병합 — 전환은 정확히 씬 경계에서 일어난다.
        seen = used_bg_ids(exclude_script=args.script_json)
        dup = [str(sc["bg"]) for sc in script["scenes"] if str(sc["bg"]) in seen]
        if dup:
            sys.exit("기각: 배경 %s 는 이미 다른 게시본에서 사용됨 — 다른 배경을 골라라" % sorted(set(dup)))
        groups = []   # [bg, start, end]
        for sc, tl in zip(script["scenes"], timeline):
            if groups and groups[-1][0] == sc["bg"]:
                groups[-1][2] = tl["end"]
            else:
                groups.append([sc["bg"], tl["start"], tl["end"]])
        groups[0][1] = 0.0
        groups[-1][2] = total_dur
        cache = {}
        for b, s_, e_ in groups:
            if b not in cache:
                if isinstance(b, str) and b.startswith("nasa:"):
                    # 2026-08-11: NASA 공개 아카이브 (퍼블릭 도메인) — 우주·천문 소재의 정합 배경
                    from fetch_nasa import fetch as fetch_nasa
                    p = fetch_nasa(b.split(":", 1)[1])
                    if p is None:
                        sys.exit("기각: NASA 배경 %s 다운로드 실패" % b)
                    cache[b] = {"kind": "video", "path": p}
                elif isinstance(b, str) and b.startswith("photo:"):
                    p = fetch_bg_photo(b.split(":", 1)[1])
                    if p is None:
                        sys.exit("기각: 지정 사진 %s 다운로드 실패" % b)
                    cache[b] = {"kind": "photo", "path": p}
                elif isinstance(b, str) and (b.startswith("file:") or b.startswith("file!:")):
                    # 로컬 파일 배경 (make_long.py와 동일 스킴, 2026-08-12)
                    p = b.split(":", 1)[1]
                    if not os.path.isabs(p):
                        p = os.path.join(ROOT, p)
                    if not os.path.exists(p):
                        sys.exit("기각: 지정 로컬 배경 %s 없음" % p)
                    if os.path.splitext(p)[1].lower() in (".jpg", ".jpeg", ".png", ".webp"):
                        # 로컬 사진 → 켄 번즈 (2026-08-13 유성우 실사진 편: CC/PD 소스는 Pexels 밖에서 온다)
                        # 단 "file!:" 처럼 '!'를 붙이면 고정(줌 없음) — 문제 화면·비교 도판처럼
                        # 화면 전체를 한눈에 봐야 하는 배경용 (2026-08-15 디렉터: "포커싱 이동 말고 중앙에 그냥 떠있게")
                        if b.startswith("file!:"):
                            print("배경 사진(로컬, 고정): %s" % os.path.basename(p), flush=True)
                            cache[b] = {"kind": "still", "path": p}
                        else:
                            print("배경 사진(로컬, 켄 번즈): %s" % os.path.basename(p), flush=True)
                            cache[b] = {"kind": "photo", "path": p}
                    else:
                        print("배경 영상(자체 제작): %s" % os.path.basename(p), flush=True)
                        # graphic: 이미 최종 프레이밍이라 줌·시네톤을 걸지 않는다 (가장자리 요소가 잘림)
                        cache[b] = {"kind": "graphic", "path": p}
                else:
                    p = fetch_bg_by_id(b)
                    if p is None:
                        sys.exit("기각: 지정 bg_id=%s 다운로드 실패" % b)
                    cache[b] = {"kind": "video", "path": p}
            bg_items.append(dict(cache[b]))
        scene_bg_segs = [e_ - s_ for _, s_, e_ in groups]
        for b_, s_, e_ in groups:
            if e_ - s_ > 12:
                print("경고: 배경 %s 구간 %.1fs — 한 구도 12초 초과는 이탈 구간이 된다. 연속 씬에 같은 bg를 몰아주지 마라" % (b_, e_ - s_), flush=True)
        print("씬별 배경: 구간 %d개 (고유 화면 %d개)" % (len(groups), len(cache)), flush=True)
    elif not args.no_bg_video:
        ids = script.get("bg_ids") or ([script["bg_id"]] if script.get("bg_id") else [])
        if ids:
            # 배경 재사용 하드게이트 (2026-08-05): 다른 편에서 쓴 배경이면 기각 (사진 포함)
            seen = used_bg_ids(exclude_script=args.script_json)   # 2026-08-23 감사: 원소마다 content/ 풀스캔하던 것을 1회로
            dup = [v for v in ids[:3] if str(v) in seen]
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
            p = fetch_bg(script.get("bg_query", ""))
            if p:
                bg_items = [{"kind": "video", "path": p}]
    video_bg = bool(bg_items)

    # 배경 전환 지점: 총 길이를 배경 수로 등분한 목표 시각에 가장 가까운 씬 경계로 스냅
    bg_segs = [total_dur]
    if scene_bg_mode:
        bg_segs = scene_bg_segs
    elif len(bg_items) > 1:
        ends = [tl["end"] for tl in timeline[:-1]]
        cuts = sorted(set(min(ends, key=lambda e: abs(e - total_dur * k / len(bg_items)))
                          for k in range(1, len(bg_items))))
        bounds = [0.0] + cuts + [total_dur]
        bg_segs = [bounds[i + 1] - bounds[i] for i in range(len(bounds) - 1)]
        bg_items = bg_items[:len(bg_segs)]   # 경계가 겹쳐 줄었으면 배경 수도 맞춤
        # 씬별 bg 모드와 동일한 이탈 경고 (2026-08-14 감사: 폴백 모드에만 누락돼 있었다)
        for sl in bg_segs:
            if sl > 12:
                print("경고: 배경 구간 %.1fs — 한 구도 12초 초과는 이탈 구간이 된다. bg_ids 수를 늘려라" % sl, flush=True)

    # 3) 렌더 + BGM
    render(script, timeline, work, total_dur, script.get("chip", "오늘의 지식 · 1일 1지식"), video_bg, fx_underline=args.fx_underline, light_bg=args.light_bg)
    bgm = os.path.join(work, "bgm.wav")
    twist_spans = [(tl["start"], tl["end"]) for sc_, tl in zip(script["scenes"], timeline)
                   if sc_.get("kind") == "twist"]
    make_bgm(total_dur, bgm, twist_spans)

    # 4) 합성·인코딩
    cmd = ["ffmpeg", "-y"]
    if video_bg:
        nb = len(bg_items)
        for it in bg_items:
            if it["kind"] in ("photo", "still"):
                cmd += ["-loop", "1", "-i", it["path"]]
            else:
                cmd += ["-stream_loop", "-1", "-i", it["path"]]
        cmd += ["-framerate", str(FPS), "-i", os.path.join(work, "frames", "f%05d.png"),
                "-i", bgm]
        # 2026-08-11 고급화 실험: 필름룩 — 미드톤 대비↑·채도 살짝↓·섀도 블루틴트 (차분한 시네마 톤)
        # 주의: colorbalance에 'ms' 옵션은 없다(bs/bm/bh 등만 유효) — 'ms'로 두면 이 경로 사용 시 ffmpeg가 죽는다 (2026-08-12 발견)
        cine = ",curves=master='0/0 0.25/0.21 0.5/0.5 0.75/0.79 1/1',eq=saturation=0.92,colorbalance=bs=0.03:bm=0.01" if args.fx_cine else ""
        scale = "scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,setsar=1,fps=%d%s" % (W, H, W, H, FPS, cine)
        parts = []
        _xf_ext = 0.35 if args.fx_xfade else 0.0
        for i, (it, seg0) in enumerate(zip(bg_items, bg_segs)):
            seg = seg0 + (_xf_ext if i < len(bg_items) - 1 else 0)
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
            elif it["kind"] == "still":
                # 고정 배경: 줌·이동 없이 그대로 (문제 화면·비교 도판 — 2026-08-15)
                # 이미 1080x1920로 만든 도판이므로 확대·크롭하지 않는다 (잘림 방지, 2026-08-15)
                parts.append(
                    "[%d:v]scale=%d:%d:force_original_aspect_ratio=decrease,"
                    "pad=%d:%d:(ow-iw)/2:(oh-ih)/2:color=0xF7F6F3,setsar=1,fps=%d,"
                    "trim=duration=%.3f,setpts=PTS-STARTPTS[b%d]"
                    % (i, W, H, W, H, FPS, seg, i))
            elif it["kind"] == "graphic":
                # 자체 도해: 줌·시네톤 없이 원본 프레이밍 그대로 (2026-08-12)
                parts.append(
                    "[%d:v]scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,setsar=1,fps=%d,"
                    "trim=duration=%.3f,setpts=PTS-STARTPTS[b%d]" % (i, W, H, W, H, FPS, seg, i))
            elif args.fx_zoom:
                # 슬로우 줌 (2026-08-09 실험): 2배 중간 해상도 경유(서브픽셀 쉬머 방지), 구간당 +6% 줌
                parts.append(
                    "[%d:v]scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,"
                    "zoompan=z='min(1.0+%.7f*on,1.12)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=%dx%d:fps=%d,"
                    "setsar=1,trim=duration=%.3f,setpts=PTS-STARTPTS[b%d]"
                    % (i, W * 2, H * 2, W * 2, H * 2, 0.06 / max(seg * FPS, 1), W, H, FPS, seg, i))
            else:
                parts.append("[%d:v]%s,trim=duration=%.3f,setpts=PTS-STARTPTS[b%d]"
                             % (i, scale, seg, i))
        if args.fx_xfade and nb > 1:
            # 크로스페이드 (2026-08-09 실험): 각 세그를 d만큼 연장 렌더했으므로 xfade가 총길이를 보존한다
            D = 0.35
            chain, acc = "[b0]", bg_segs[0]
            for i in range(1, nb):
                out = "[bgv]" if i == nb - 1 else "[x%d]" % i
                parts.append("%s[b%d]xfade=transition=fade:duration=%.2f:offset=%.3f%s"
                             % (chain, i, D, acc - D, out))
                chain, acc = out, acc + bg_segs[i] - D
        else:
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
    sfx_n = 0
    if getattr(args, "fx_sfx", False) and video_bg and len(bg_segs) > 1:
        # 소프트 전환음 (2026-08-09 실험): 밴드패스 노이즈 스윕 0.30s, -18dB — 자체 합성(저작권 클린)
        sfx_path = os.path.join(work, "sfx.wav")
        SRs = 44100
        n = int(SRs * 0.30)
        tt = np.arange(n) / SRs
        rng = np.random.default_rng(7)
        noise = rng.standard_normal(n)
        sweep = np.sin(2 * np.pi * (900 - 500 * tt / 0.30) * tt)
        sig = (0.6 * noise * np.exp(-((tt - 0.10) ** 2) / 0.004) + 0.4 * sweep) * np.hanning(n)
        sig /= max(np.abs(sig).max(), 1e-9)
        pcm = (sig * 32767 * 0.125).astype(np.int16)   # ≈ -18dB
        with wave.open(sfx_path, "wb") as wf:
            wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(SRs)
            wf.writeframes(pcm.tobytes())
        cuts = []
        acc = 0.0
        for seg in bg_segs[:-1]:
            acc += seg
            cuts.append(acc)
        for ci, cut in enumerate(cuts):
            cmd += ["-i", sfx_path]
            fl.append("[%d:a]adelay=%d:all=1[sfx%d]" % (a_base + 1 + ci, max(0, int((cut - 0.15) * 1000)), ci))
            amix_in += "[sfx%d]" % ci
        sfx_n = len(cuts)
        a_base += sfx_n
    for i, tl in enumerate(timeline):
        cmd += ["-i", tl["mp3"]]
        fl.append("[%d:a]adelay=%d:all=1,volume=1.0[v%d]" % (a_base + 1 + i, int(tl["start"] * 1000), i))
        amix_in += "[v%d]" % i
    fl.append("%samix=inputs=%d:normalize=0[aout]" % (amix_in, len(timeline) + 1 + sfx_n))
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
    # 🚨 문화 게이트 (2026-08-25 실사고 — 추석 편에 중국 한푸 배경이 게시됨)
    #   한국 고유 소재일 때만, 완성본 프레임을 비전 모델로 검사해 외국 전통 요소를 잡는다.
    #   세션의 눈(프레임 QA)은 8/25에 "통과"로 기록하고도 놓쳤다 — 기계가 한 번 더 본다.
    #   판정 불가(키 부재·네트워크)는 통과시키되 경고를 남긴다(게이트 고장이 슬롯을 죽이면 안 된다).
    try:
        from culture_gate import is_korean_topic, check_frames
        # 판정 재료에 **나레이션(voice)·topic·chip·bg_query**를 모두 넣는다 —
        # title만 보면 title 키가 없는 편(실측 137편 중 25편)과 "한복"이 자막이 아닌
        # 나레이션에만 나오는 편이 통째로 미검사로 빠진다 (2026-08-25 재감사).
        _blob = " ".join([str(script.get("title", "")), str(script.get("topic", "")),
                          str(script.get("chip", "")), " ".join(script.get("bg_query") or [])] +
                         [str(sc.get("voice", "")) for sc in script["scenes"]] +
                         [ln for sc in script["scenes"] for ln, _ in sc.get("lines", [])])
        # 소재국이 한국이 아님이 명백한 편(중국산 배추·피사의 사탑 등)은 json에
        # "culture_gate": false 로 끈다 — 그런 편에 한국 기준을 대면 정상 배경이 기각된다.
        if script.get("culture_gate") is not False and is_korean_topic(_blob):
            import subprocess as _sp, tempfile as _tf, shutil as _sh
            _d = _tf.mkdtemp(prefix="culture_")
            try:
                # 씬마다 중앙 1프레임 — 3지점 샘플은 6씬 중 최대 3씬만 덮어
                # 씬 2·4의 위험 배경이 그대로 통과한다 (2026-08-25 감사). 호출당 약 5초.
                _mids = []
                for _sc in timeline:
                    try:
                        _mids.append((_sc["start"] + _sc["end"]) / 2.0)
                    except Exception:
                        pass
                if not _mids:
                    _mids = [1.0, total_dur * 0.45, max(0.0, total_dur - 4)]
                _shots = []
                for _t in _mids:
                    _f = os.path.join(_d, "f%.0f.jpg" % (_t * 10))
                    _sp.run(["ffmpeg", "-v", "error", "-ss", "%.2f" % _t, "-i", out_mp4,
                             "-frames:v", "1", _f, "-y"], check=False, timeout=60)
                    if os.path.exists(_f):
                        _shots.append(_f)
                # 프레임이 하나도 안 뽑히면(ffmpeg PATH 사고·손상 파일) check_frames는 ([],[])를
                # 반환해 "통과"가 찍힌다 — fail-closed 전환의 목적을 정면으로 무력화하는
                # 가장 흔한 고장 모드였다 (2026-08-25 재감사). 판정 불가로 취급한다.
                if not _shots:
                    _bad, _unknown = [], [(None, "프레임 추출 0장(ffmpeg 확인 필요)")]
                else:
                    _bad, _unknown = check_frames(_shots)
                if _bad:
                    _why = " / ".join(w for _, w in _bad)
                    # ⚠️ 산출물을 반드시 치운다 — 기각했는데 mp4가 out/에 남으면
                    #    러너의 자동 복구(check_artifacts)가 "영상 있는데 미게시"로 읽고
                    #    **기각된 바로 그 영상을 3채널에 무인 게시한다**. 게이트가 잡을수록
                    #    사고가 나는 구조가 된다 (2026-08-25 감사 지적).
                    try:
                        _rej = os.path.join(ROOT, "out", "rejected")
                        os.makedirs(_rej, exist_ok=True)
                        os.replace(out_mp4, os.path.join(_rej, os.path.basename(out_mp4)))
                        print("기각 산출물 격리: out/rejected/%s" % os.path.basename(out_mp4), flush=True)
                    except Exception as _me:
                        try:
                            os.remove(out_mp4)
                        except Exception:
                            print("경고: 기각 산출물 정리 실패 — 수동 삭제 필요: %s (%s)"
                                  % (out_mp4, str(_me)[:80]), flush=True)
                    sys.exit("기각: 한국 고유 소재인데 배경에 외국 전통 요소가 감지됐다 — %s\n"
                             "     → 해당 씬의 bg를 교체하라. 확실한 한국 자산이 없으면 "
                             "국적이 드러나지 않는 자연물(보름달·밤하늘·황금 들녘·벼·추수)로 가라." % _why)
                if _unknown:
                    # fail-CLOSED: 한국 고유 소재는 전체의 7%뿐이고, 디렉터 판정상
                    # "슬롯 1개 손실" < "나락 한순간"이다. 자동 게시가 생긴 뒤로 fail-open은
                    # **게이트가 죽은 채 아무도 안 보는 밤에 무인 게시**를 뜻한다 (2026-08-25 감사).
                    _m = ("⚠️ 문화 게이트 판정 불가 — 한국 소재 편이라 게시를 보류합니다(%s): %s. "
                          "네트워크·GEMINI_API_KEY 확인 후 재렌더하세요."
                          % (_unknown[0][1][:80], os.path.basename(out_mp4)))
                    try:
                        import subprocess as _sp2
                        _sp2.run(["bash", os.path.join(ROOT, "bin", "tg-send.sh"), _m],
                                 check=False, timeout=30)
                    except Exception:
                        pass
                    try:
                        _rej = os.path.join(ROOT, "out", "rejected")
                        os.makedirs(_rej, exist_ok=True)
                        os.replace(out_mp4, os.path.join(_rej, os.path.basename(out_mp4)))
                    except Exception:
                        try:
                            os.remove(out_mp4)
                        except Exception:
                            pass
                    sys.exit("기각: 문화 게이트 판정 불가 — %s" % _unknown[0][1][:120])
                else:
                    print("문화 게이트 통과: 한국 고유 소재, 외국 전통 요소 없음", flush=True)
            finally:
                _sh.rmtree(_d, ignore_errors=True)
    except SystemExit:
        raise
    except Exception as _e:
        print("경고: 문화 게이트 실행 실패(무해, 통과 처리):", str(_e)[:120], flush=True)

    print("완료: %s (%.1fs, %.1fMB, 배경=%s)"
          % (out_mp4, total_dur, final_mb, "영상" if video_bg else "그라데이션"))

if __name__ == "__main__":
    main()
