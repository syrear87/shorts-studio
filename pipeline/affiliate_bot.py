#!/usr/bin/env python3
# 제휴 스티커 킷 워처 (2026-08-13 오후 디렉터 최종 확정 루틴 — 댓글·자동 게시 폐기)
#   흐름: 세션이 텔레그램으로 "제휴 후보+쿠팡 검색 딥링크" 발송 → 디렉터가 상품 공유
#   URL(link.coupang.com) 회신(=승인, S-007) → 이 워처가 ①허브 갱신 ②스티커 킷
#   (자막 완성 프레임 커버 이미지+링크+YT 설명란 블록) 발송 → 디렉터가 스토리+링크 스티커 게시.
#   명령: '스티커'(킷 재발송) / '취소'(허브 롤백 — 스토리는 앱에서 삭제).
#   ⚠️ IG 댓글·캡션 URL은 클릭 불가, 링크 스티커는 API 미지원 — 클릭 통로는 스토리 스티커·프로필 링크뿐.
# 실행: pm2 (studio-affiliate)
import json
import os
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OFFSET_F = os.path.join(ROOT, "logs", "affiliate_offset.txt")
STATE_F = os.path.join(ROOT, "logs", "affiliate_state.json")
DISCLOSURE = "* 이 게시물은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다"


def env(path, keys):
    out = {}
    for line in open(os.path.join(ROOT, path), encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            if k.strip() in keys:
                out[k.strip()] = v.strip().strip('"')
    return out


TG = env("telegram.env", {"STUDIO_TG_TOKEN", "STUDIO_TG_CHAT_ID"})
IG = env("keys.env", {"IG_ACCESS_TOKEN", "IG_USER_ID"})
KV = env("keys.env", {"R2_ACCOUNT_ID", "R2_ACCESS_KEY", "R2_SECRET_KEY", "R2_BUCKET", "R2_PUBLIC_URL"})
HUB = env("keys.env", {"HUB_COUNTER_URL", "HUB_STATS_KEY"})   # 허브 카운터 (2026-08-14, 미배포면 빈 dict)
G = "https://graph.instagram.com/v23.0"


def http(url, data=None, timeout=60):
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def tg_send(text):
    http("https://api.telegram.org/bot%s/sendMessage" % TG["STUDIO_TG_TOKEN"],
         urllib.parse.urlencode({"chat_id": TG["STUDIO_TG_CHAT_ID"], "text": text,
                                 "disable_web_page_preview": "true"}).encode())


def tg_send_photo(path, caption):
    import mimetypes, uuid
    boundary = uuid.uuid4().hex
    fields = {"chat_id": TG["STUDIO_TG_CHAT_ID"], "caption": caption}
    body = b""
    for k, v in fields.items():
        body += ("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (boundary, k, v)).encode()
    fn = os.path.basename(path)
    body += ("--%s\r\nContent-Disposition: form-data; name=\"document\"; filename=\"%s\"\r\nContent-Type: image/jpeg\r\n\r\n" % (boundary, fn)).encode()
    body += open(path, "rb").read() + b"\r\n"
    body += ("--%s--\r\n" % boundary).encode()
    req = urllib.request.Request("https://api.telegram.org/bot%s/sendDocument" % TG["STUDIO_TG_TOKEN"],
                                 data=body, method="POST")
    req.add_header("Content-Type", "multipart/form-data; boundary=%s" % boundary)
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def latest_media():
    d = http(f"{G}/{IG['IG_USER_ID']}/media?fields=id,permalink,caption,timestamp,media_type,media_url,thumbnail_url,children{{media_url}}&limit=1&access_token={IG['IG_ACCESS_TOKEN']}")
    if not d.get("data"):
        return None
    m = d["data"][0]
    # 캐러셀(카드)은 첫 장의 media_url을 커버로 사용
    if not m.get("media_url") and m.get("children", {}).get("data"):
        m["media_url"] = m["children"]["data"][0].get("media_url")
    return m


def match_media(product_name, limit=6):
    """상품과 짝이 되는 게시물을 고른다 (2026-08-16 실사고로 신설).
    사고: 세라마이드 로션 링크를 17:17에 회신했는데 커버가 16시 '결혼 전 주식' 편으로 나갔다.
      커버를 무조건 '최신 게시물'에서 뽑았기 때문이다 — 디렉터가 링크를 늦게 주면
      이미 다음 편이 올라가 있어 엉뚱한 화면이 커버가 된다.
    방법: 상품명을 2글자 이상 토큰으로 쪼개 최근 게시물 캡션(해시태그 포함)과 대조하고,
      가장 많이 겹치는 편을 쓴다. 하나도 안 겹치면 최신 편으로 폴백한다."""
    d = http(f"{G}/{IG['IG_USER_ID']}/media?fields=id,permalink,caption,timestamp,media_type,media_url,thumbnail_url,children{{media_url}}&limit={limit}&access_token={IG['IG_ACCESS_TOKEN']}")
    items = d.get("data") or []
    if not items:
        return None
    toks = [t for t in re.split(r"[^0-9A-Za-z가-힣]+", product_name or "") if len(t) >= 2]
    # 2글자 조각까지 본다 (2026-08-16 실사고: 상품 '비상용망치'와 대본 '비상탈출 망치'가
    # 낱말 단위로는 안 겹쳐 매칭이 실패했다. 같은 물건을 다르게 부르는 건 흔한 일이다).
    grams = set()
    for t in toks:
        for i in range(len(t) - 1):
            grams.add(t[i:i + 2])
    best, best_hit = None, 0
    for it in items:
        cap = it.get("caption") or ""
        hit = sum(2 for t in toks if t in cap)            # 낱말 일치는 가중 2
        hit += sum(1 for g in grams if g in cap)          # 2글자 조각은 1
        if hit > best_hit:
            best, best_hit = it, hit
    if best_hit < 3:      # 조각 두어 개 우연히 겹친 정도는 매칭으로 보지 않는다
        best = None
    m = best or items[0]
    if best:
        print("[affiliate_bot] 커버 매칭: '%s' → %s (겹친 낱말 %d)"
              % (product_name[:20], (m.get("caption") or "")[:24], best_hit), flush=True)
    else:
        print("[affiliate_bot] 커버 매칭 실패 — 최신 편 사용", flush=True)
    if not m.get("media_url") and m.get("children", {}).get("data"):
        m["media_url"] = m["children"]["data"][0].get("media_url")
    return m


def state(update=None):
    s = {}
    if os.path.exists(STATE_F):
        try:
            s = json.load(open(STATE_F, encoding="utf-8"))
        except Exception:
            s = {}   # 파손 시 초기화 — 모든 명령이 영구 실패하는 것보다 낫다 (2026-08-14 감사)
    if update:
        s.update(update)
        tmp = STATE_F + ".tmp"
        json.dump(s, open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
        os.replace(tmp, STATE_F)   # 원자적 교체
    return s


HUB_KEY = "hub/index.html"
STORY_KEY = "hub/story_%s.jpg"


def r2_client():
    import boto3
    return boto3.client("s3",
                        endpoint_url="https://%s.r2.cloudflarestorage.com" % KV["R2_ACCOUNT_ID"],
                        aws_access_key_id=KV["R2_ACCESS_KEY"],
                        aws_secret_access_key=KV["R2_SECRET_KEY"], region_name="auto")


def update_hub(items):
    """자체 미니 허브 페이지 갱신 (v2: 흰 배경 미니멀 — 2026-08-13 디렉터 "심플하게, 배경색 없이").
    items = [{name, url, date}] 최신순 최대 5개."""
    import html as _html
    cnt = HUB.get("HUB_COUNTER_URL", "").rstrip("/")
    def _href(it):
        if not cnt:
            return it["url"]
        # 카운터 경유: 클릭 집계 후 쿠팡으로 302 (2026-08-14 디렉터 — 상품별 클릭 체크)
        slug = urllib.parse.quote(it["name"][:24])
        return "%s/go?n=%s&u=%s" % (cnt, slug, urllib.parse.quote(it["url"], safe=""))
    rows = "\n".join(
        '<a class="item" href="%s"><span class="name">%s</span><span class="meta">%s</span></a>'
        % (_html.escape(_href(it), quote=True),
           _html.escape((it["name"][:34] + '…') if len(it["name"]) > 35 else it["name"]),
           _html.escape(("「%s」에 나온 물건 · %s" % (it["ep"], it["date"])) if it.get("ep") else ("%s · 쿠팡에서 보기 ›" % it["date"])))
        for it in items)
    beacon = ""
    if cnt:
        # 방문 비콘 — 세션당 1회. 디렉터 제외: 허브를 '#me' 붙여 한 번 열면 그 기기는 영구 제외
        # (localStorage 플래그 → 비콘 생략 + 클릭 링크에 me=1)
        beacon = ("<script>(function(){try{"
                  "if(location.hash==='#me'){localStorage.setItem('hub_admin','1');}"
                  "var me=localStorage.getItem('hub_admin')==='1';"
                  "if(me){document.querySelectorAll('a.item').forEach(function(a){a.href+='&me=1';});}"
                  "else if(!sessionStorage.getItem('hs')){sessionStorage.setItem('hs','1');"
                  "(new Image()).src='%s/px?r='+Date.now();}"
                  "}catch(e){}})();</script>" % cnt)
    html = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>1일 1지식 - 오늘의 추천</title><style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#fff;color:#111;font-family:-apple-system,BlinkMacSystemFont,'Apple SD Gothic Neo','Pretendard',sans-serif;
padding:56px 20px 40px;max-width:480px;margin:0 auto}
h1{font-size:26px;font-weight:900;text-align:center;letter-spacing:-0.5px}
h1 .d1{color:#12192e}h1 .d2{color:#ffb43c}
.underbar{width:58px;height:5px;background:#ffb43c;border-radius:3px;margin:8px auto 0}
p.sub{color:#8a8f98;font-size:13px;text-align:center;margin:6px 0 36px}
.item{display:block;border:1px solid #e6e8eb;border-radius:14px;padding:18px 20px;margin:10px 0;
text-decoration:none;color:#111;transition:border-color .15s}
.item:active{border-color:#111}
.name{display:block;font-size:15px;font-weight:650;line-height:1.45}
.meta{display:block;color:#a0a5ad;font-size:12px;margin-top:6px}
footer{color:#b3b8bf;font-size:11px;text-align:center;margin-top:44px;line-height:1.7}
</style></head><body>
<h1><span class="d1">1일</span> <span class="d2">1지식</span></h1><div class="underbar"></div><p class="sub" style="margin-top:14px">영상에 나온 것들 · 지식 아카이브</p>
%s
<footer>쿠팡 파트너스 활동의 일환으로,<br>이에 따른 일정액의 수수료를 제공받습니다</footer>
%s</body></html>""" % (rows, beacon)
    s3 = r2_client()
    s3.put_object(Bucket=KV["R2_BUCKET"], Key=HUB_KEY, Body=html.encode("utf-8"),
                  ContentType="text/html; charset=utf-8", CacheControl="no-cache")
    return KV["R2_PUBLIC_URL"].rstrip("/") + "/" + HUB_KEY


def local_cover_frame(media):
    """최신 IG 게시물이 우리 영상이면, 로컬 mp4에서 '결론(반전) 페이지' 자막이 전부 뜬 프레임을 커버로 쓴다
    (2026-08-14 디렉터 1차: "자막 다 나온 상태로" / 2차: "첫 문구 말고 1일 1지식 전 결론 페이지로").
    방법: 게시 시각 최근접 매칭 → 영상 끝에서 CTA(~6.5s) 제외한 마지막 창을 2fps 스캔,
    중앙 자막 밴드(세로 35~65%)의 흰 픽셀 최대(동률이면 늦은) 시점 = 결론 자막 완성 시점."""
    import subprocess
    import tempfile
    from datetime import timezone, timedelta
    try:
        rows = [ln.split() for ln in open(os.path.join(ROOT, "logs", "sent.log"), encoding="utf-8")]
        vids = [r for r in rows if len(r) == 2 and r[1].startswith("IG:") and r[1].endswith(".mp4")]
        if not vids:
            return None
        # 게시 시각과 가장 가까운 행 선택 (2026-08-14 감사: 정정 연타 때 '마지막 행'은 삭제본일 수 있다)
        mt = datetime.strptime(media["timestamp"], "%Y-%m-%dT%H:%M:%S%z")
        def gap(r):
            lt = datetime.strptime(r[0], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone(timedelta(hours=9)))
            return abs((mt - lt).total_seconds())
        best = min(vids, key=gap)
        if gap(best) > 600:   # 게시 직후 기록되므로 정상 매칭은 수 분 이내
            return None  # 최신 게시물이 우리 발행분이 아니다 — 썸네일 폴백
        name = best[1][3:]
        path = os.path.join(ROOT, "out", name)
        if not os.path.exists(path):
            return None
        # 2026-08-14 디렉터: 커버는 훅이 아니라 '결론(반전) 페이지' — 구독(CTA) 직전 씬.
        # 끝에서 CTA+꼬리(~6.5s)를 제외한 마지막 13.5s 창을 스캔해 결론 자막 완성 시점을 잡는다.
        probe = subprocess.run(["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                                "-of", "csv=p=0", path], capture_output=True, text=True)
        dur = float(probe.stdout.strip())
        # 2026-08-16 디렉터 지적("씬 3으로 뽑혔거든?"): 창이 13.5s로 넓어 결론 앞 fact 씬까지 들어왔고,
        # 판정 기준이 '흰 픽셀 최대'라 자막이 더 긴 fact3이 결론을 이겼다.
        # → CTA 직전 7.5s(결론 씬 한 개 분량)만 스캔한다.
        w_end = max(1.0, dur - 6.5)
        w_start = max(0.0, w_end - 7.5)
        w_len = max(1.0, w_end - w_start)
        tmp = tempfile.mkdtemp(prefix="afcover_")
        subprocess.run(["ffmpeg", "-y", "-ss", "%.2f" % w_start, "-t", "%.2f" % w_len,
                        "-i", path, "-vf", "fps=2,scale=270:480",
                        "-loglevel", "error", os.path.join(tmp, "f%03d.jpg")], check=True)
        from PIL import Image
        best_n, best_ink = None, -1
        for fn in sorted(os.listdir(tmp)):
            if not fn.startswith("f"):
                continue
            g = Image.open(os.path.join(tmp, fn)).convert("L")
            band = g.crop((0, int(480 * 0.35), 270, int(480 * 0.65)))
            ink = sum(1 for v in band.getdata() if v >= 225)
            if ink >= best_ink:  # 동률이면 늦은 프레임(단어 하이라이트까지 진행된 상태)
                best_n, best_ink = int(fn[1:4]), ink
        if best_n is None:
            return None
        t = w_start + (best_n - 1) / 2.0 + 0.2
        outp = os.path.join(tmp, "cover.jpg")
        subprocess.run(["ffmpeg", "-y", "-ss", "%.2f" % t, "-i", path, "-frames:v", "1",
                        "-q:v", "2", "-loglevel", "error", outp], check=True)
        return outp if os.path.exists(outp) else None
    except Exception:
        return None  # 어떤 실패든 썸네일 폴백 — 스티커 킷 발송 자체를 막지 않는다


def make_story_image(media, product_name, out_path, sticker_mode=False):
    """스토리용 이미지 v2 (2026-08-13 디렉터: 어두운 블러 배경판 기각 → 허브와 같은 흰 배경 브랜드 톤).
    구성: 워드마크 / 오늘의 추천 + 상품명 / 게시물 커버(라운드+섀도) / 하단 여백(스티커 자리) / 고지."""
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
    import io
    W, H = 1080, 1920
    NAVY, GOLD = (18, 25, 46), (255, 180, 60)
    GRAY, LGRAY = (138, 143, 152), (179, 184, 191)
    # 커버 우선순위: 로컬 영상의 '자막 완성' 프레임 → IG 썸네일 (2026-08-14 디렉터: 썸네일은 자막 한 줄뿐)
    local = local_cover_frame(media)
    if local:
        cover = Image.open(local).convert("RGB")   # convert가 즉시 로드 — 이후 원본 삭제 안전
        import shutil
        shutil.rmtree(os.path.dirname(local), ignore_errors=True)   # 임시 프레임 24장 누적 방지
    else:
        # 릴스는 media_url이 mp4다 — 이미지는 항상 썸네일 우선 (2026-08-13 실사고)
        url = media.get("thumbnail_url") or media.get("media_url")
        raw = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=60).read()
        cover = Image.open(io.BytesIO(raw)).convert("RGB")
    im = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(im)
    def font(sz):
        for p in ["/Library/Fonts/Pretendard-ExtraBold.otf",
                  os.path.expanduser("~/Library/Fonts/Pretendard-ExtraBold.otf"),
                  "/System/Library/Fonts/AppleSDGothicNeo.ttc"]:
            if os.path.exists(p):
                try:
                    return ImageFont.truetype(p, sz)
                except Exception:
                    continue
        return ImageFont.load_default()
    def center(y, t, f, fill):
        d.text(((W - d.textlength(t, font=f)) / 2, y), t, font=f, fill=fill)
    f_mark = font(72)
    w1, w2 = d.textlength("1일 ", font=f_mark), d.textlength("1지식", font=f_mark)
    x0 = (W - w1 - w2) / 2
    d.text((x0, 150), "1일 ", font=f_mark, fill=NAVY)
    d.text((x0 + w1, 150), "1지식", font=f_mark, fill=GOLD)
    d.rounded_rectangle([(W - 140) / 2, 260, (W + 140) / 2, 274], radius=7, fill=GOLD)
    center(340, "오늘의 추천", font(44), GRAY)
    if not sticker_mode:
        name = product_name if len(product_name) <= 18 else product_name[:17] + "…"
        center(420, name, font(56), NAVY)
    # sticker_mode: '오늘의 추천' 아래(y 400~540)를 비워둔다 — 디렉터가 그 자리에 링크 스티커 배치 (2026-08-13)
    card_w = 860
    card = cover.resize((card_w, int(card_w * cover.height / cover.width)))
    if card.height > 1050:
        # 세로 커버(릴스)는 자막 블록이 화면 중앙부(약 40~60%)에 있다 — 그 중심(48%)이 카드 가운데 오도록 크롭 (2026-08-13 디렉터)
        y0 = int(card.height * 0.48 - 525)
        y0 = max(0, min(y0, card.height - 1050))
        card = card.crop((0, y0, card_w, y0 + 1050))
    rad = 36
    mask = Image.new("L", card.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, card.width, card.height], radius=rad, fill=255)
    cx, cy = (W - card_w) // 2, 560
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        [cx + 6, cy + 14, cx + card_w + 6, cy + card.height + 14], radius=rad, fill=(20, 25, 40, 60))
    shadow = shadow.filter(ImageFilter.GaussianBlur(18))
    im.paste(shadow, (0, 0), shadow)
    im.paste(card, (cx, cy), mask)
    if sticker_mode:
        # v3.2 (2026-08-16 디렉터: "링크는 위 스티커를 탭 이거 안 나오게 해줘") —
        # 문구는 전부 뺀다. 상품명도 탭 유도도 링크 스티커가 담당하고,
        # 이미지는 커버 프레임 + 스티커 자리 점선 가이드만 남긴다.
        # 스티커 위치 점선 가이드 (IG 기본 스티커보다 약간 작게 — 스티커가 덮으면 최종 화면엔 안 보임)
        gx0, gy0, gx1, gy1 = (W - 460) / 2, 415, (W + 460) / 2, 525
        dash = 18
        x_ = gx0
        while x_ < gx1:
            d.line([(x_, gy0), (min(x_ + dash, gx1), gy0)], fill=(210, 213, 220), width=3)
            d.line([(x_, gy1), (min(x_ + dash, gx1), gy1)], fill=(210, 213, 220), width=3)
            x_ += dash * 2
        y_ = gy0
        while y_ < gy1:
            d.line([(gx0, y_), (gx0, min(y_ + dash, gy1))], fill=(210, 213, 220), width=3)
            d.line([(gx1, y_), (gx1, min(y_ + dash, gy1))], fill=(210, 213, 220), width=3)
            y_ += dash * 2
        center((gy0 + gy1) / 2 - 14, "여기에 링크 스티커", font(26), LGRAY)
        center(H - 150, "쿠팡 파트너스 활동의 일환으로 수수료를 제공받습니다", font(26), LGRAY)
    else:
        center(H - 260, "구매 링크는 프로필에서", font(46), GOLD)
        center(H - 150, "쿠팡 파트너스 활동의 일환으로 수수료를 제공받습니다", font(26), LGRAY)
    im.save(out_path, quality=93)
    return out_path



def handle_link(text_msg):
    url_m = re.search(r"https://link\.coupang\.com/\S+", text_msg)
    if not url_m:
        return
    url = url_m.group(0)
    name = ""
    for ln in text_msg.splitlines():
        ln = ln.strip()
        if ln and "link.coupang.com" not in ln and "쿠팡을 추천합니다" not in ln:
            name = ln[:60]
            break
    if not name:
        name = "오늘의 추천 상품"
    m = match_media(name)
    if not m:
        tg_send("⚠️ 처리 실패: 최근 게시물 조회 실패")
        return
    # ① 허브 자동 갱신 (프로필 링크 보조 통로)
    s_ = state()
    items = [it for it in s_.get("hub_items", []) if it["url"] != url]
    ep = (m.get("caption") or "").split("\n")[0][:40]
    items.insert(0, {"name": name, "url": url, "date": datetime.now().strftime("%m/%d"), "ep": ep})
    items = items[:5]
    update_hub(items)
    state({"hub_items": items, "last_permalink": m.get("permalink"),
           "last_product": {"name": name, "url": url}, "ts": datetime.now().isoformat()})
    # ①-b 스레드에 쿠팡 링크 답글 (2026-08-16 디렉터: "쿠팡 링크를 넣어야지")
    #    게시(슬롯 시각)와 링크 회신(디렉터가 나중) 사이에 시차가 있어 본문에 못 넣는다 →
    #    그 편의 스레드 글을 찾아 답글로 붙인다. 스레드는 링크가 클릭되는 유일한 통로다.
    #    ⚠️ 쿠팡 링크에는 대가성 문구가 법적 의무 — 같은 글에 함께 붙인다.
    try:
        import upload_threads as _th
        _pid = _th.find_recent_post(ep)
        if _pid:
            _th.reply_text(_pid, "%s\n%s\n\n%s" % (name, url, DISCLOSURE))
            print("[affiliate_bot] 스레드 답글 완료:", ep[:20], flush=True)
        else:
            print("[affiliate_bot] 스레드에서 해당 편을 못 찾음 — 답글 생략", flush=True)
    except Exception as _e:
        print("[affiliate_bot] 스레드 답글 실패(무해):", str(_e)[:150], flush=True)

    # ② 최종 확정 (2026-08-13 오후): 자동 게시 없음, 프로필 유도형 없음 —
    #    스티커 킷(이미지+링크)을 만들어 보내면 디렉터가 스토리+링크 스티커로 게시한다 (클릭 1번 경로 유일 기본)
    try:
        img = os.path.join(ROOT, "out", "story_sticker_ready.jpg")
        make_story_image(m, name, img, sticker_mode=True)
        tg_send_photo(img, "📸 %s — ①저장 ②스토리 올리기 ③점선 자리에 링크 스티커(다음 메시지) — 스티커 문구는 '링크' 대신 상품명으로 ④게시. 11시대에 올리면 접속 피크를 통째로 탑니다" % name)
        tg_send(url)
        state({"pending_story": {"name": name, "kit_ts": time.time(), "story_id": None, "posted_ts": None}})
        tg_send("📋 유튜브 설명란 끝에 붙여넣기용 (링크 클릭 가능):\n\n🛒 %s\n%s\n* 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다" % (name, url))
    except Exception as e:
        print("[affiliate_bot] 이미지 실패:", str(e)[:200], flush=True)
        tg_send("⚠️ 스토리 이미지 생성 실패 — 게시물 커버로 직접 스토리 올려주세요. 링크: %s" % url)


def send_sticker_kit():
    s_ = state()
    p = s_.get("last_product")
    if not p:
        tg_send("최근 제휴 상품 기록이 없습니다.")
        return
    m = match_media(p.get("name", ""))
    if not m:
        tg_send("⚠️ 최근 게시물 조회 실패 — 잠시 후 '스티커'로 다시 시도해주세요. 링크: %s" % p["url"])
        return
    try:
        img = os.path.join(ROOT, "out", "story_sticker_ready.jpg")
        make_story_image(m, p["name"], img, sticker_mode=True)
        tg_send_photo(img, "📸 스티커용 이미지 — ①저장 ②스토리 올리기 ③링크 스티커 ④게시")
        tg_send("스티커용 링크 (복사):\n%s" % p["url"])
    except Exception as e:
        print("[affiliate_bot] 스티커 킷 실패:", str(e)[:200], flush=True)
        tg_send("⚠️ 스티커 이미지 생성 실패 — 게시물 커버로 직접 올려주세요. 링크: %s" % p["url"])


def hub_stats():
    """'허브' 명령 — 방문·클릭 집계를 텔레그램으로 (2026-08-14 디렉터: 나만 볼 수 있게)."""
    c, k = HUB.get("HUB_COUNTER_URL", "").rstrip("/"), HUB.get("HUB_STATS_KEY", "")
    if not c or not k:
        tg_send("허브 카운터가 아직 배포 전입니다 — CLOUDFLARE_API_TOKEN을 keys.env에 넣고 bash bin/deploy_hub_counter.sh 실행")
        return
    d = None
    for attempt in range(3):   # DNS 전파 과도기 플랩 내성 (2026-08-14 첫날 실측)
        try:
            d = http("%s/stats?k=%s" % (c, k))
            break
        except Exception as e:
            err = e
            time.sleep(4)
    if d is None:
        tg_send("⚠️ 집계 서버 연결이 아직 고르지 않습니다(새 주소 전파 중 — 최대 30분). 잠시 후 '허브'를 다시 보내주세요. (%s)" % str(err)[:60])
        return
    today = datetime.now().strftime("%Y-%m-%d")
    lines = ["📊 허브 집계 (디렉터 기기 제외)",
             "방문: 오늘 %d · 누적 %d" % (d.get("view:%s" % today, 0), d.get("view:total", 0))]
    clicks = sorted(((urllib.parse.unquote(key[6:]), v) for key, v in d.items()
                     if key.startswith("click:")), key=lambda x: -x[1])
    if clicks:
        lines.append("상품 클릭 (누적):")
        for name, v in clicks[:10]:
            t = d.get("day:%s:click:%s" % (today, urllib.parse.quote(name[:24])), 0)
            lines.append("· %s — %d회%s" % (name, v, " (오늘 %d)" % t if t else ""))
    else:
        lines.append("상품 클릭: 아직 없음")
    lines.append("(참고: 파트너스 리포트의 링크별 클릭은 스토리 스티커 포함 전체 집계)")
    tg_send("\n".join(lines))


def track_story():
    """스토리 계측 (2026-08-14 전략회의 A2 — 계기판 없이는 어떤 개선도 판정 불가).
    킷 발송 후: ①디렉터 게시 감지(/stories) ②게시 +20h에 도달(reach) 수집 → state.story_stats 누적."""
    st = state()
    p = st.get("pending_story")
    if not p:
        return
    now = time.time()
    try:
        if not p.get("story_id"):
            if now - p["kit_ts"] > 24 * 3600:
                state({"pending_story": None})   # 24h 내 미게시 — 추적 포기
                return
            d = http(f"{G}/{IG['IG_USER_ID']}/stories?fields=id,timestamp&access_token={IG['IG_ACCESS_TOKEN']}")
            for it in d.get("data", []):
                ts = datetime.strptime(it["timestamp"], "%Y-%m-%dT%H:%M:%S%z").timestamp()
                if ts >= p["kit_ts"] - 300:
                    p["story_id"], p["posted_ts"] = it["id"], ts
                    state({"pending_story": p})
                    break
        elif now > p["posted_ts"] + 20 * 3600:
            v = {}
            try:
                ins = http(f"{G}/{p['story_id']}/insights?metric=reach,replies&access_token={IG['IG_ACCESS_TOKEN']}")
                v = {x["name"]: x["values"][0]["value"] for x in ins["data"]}
            except Exception as e:
                v = {"error": str(e)[:60]}
            stats = st.get("story_stats", [])
            stats.append({"date": datetime.fromtimestamp(p["posted_ts"]).strftime("%m/%d %H:%M"),
                          "name": p["name"], "reach": v.get("reach"), "replies": v.get("replies")})
            state({"story_stats": stats[-30:], "pending_story": None})
    except Exception as e:
        print("[affiliate_bot] 스토리 추적 오류:", str(e)[:120], flush=True)


def story_report():
    """'스토리' 명령 — 스토리별 도달 기록. 파트너스 링크별 클릭(디렉터 회신)과 대사해 CTR 계산."""
    stats = state().get("story_stats", [])
    if not stats:
        tg_send("아직 계측된 스토리가 없습니다 (게시 +20시간 후 자동 수집).")
        return
    lines = ["📈 스토리 계측 (게시 +20h 도달 기준)"]
    for x in stats[-10:]:
        lines.append("· %s %s — 도달 %s%s" % (x["date"], x["name"][:16], x.get("reach", "?"),
                                             (" 답장 %s" % x["replies"]) if x.get("replies") else ""))
    lines.append("파트너스 리포트의 링크별 클릭 수를 회신해주시면 CTR로 환산합니다 (예: '베개 3 삼계탕 1')")
    tg_send("\n".join(lines))



def cancel_last():
    s = state()
    items = s.get("hub_items", [])
    if not items:
        tg_send("취소할 항목이 없습니다.")
        return
    dropped = items.pop(0)
    update_hub(items)
    upd = {"hub_items": items}
    lp = s.get("last_product")
    if lp and lp.get("url") == dropped.get("url"):
        upd["last_product"] = None   # 취소된 상품이 '스티커' 명령으로 재발송되는 것 방지 (2026-08-14 감사)
    state(upd)
    tg_send("🗑 허브에서 '%s' 제거했습니다. 스토리는 앱에서 직접 삭제해주세요(24시간 후 자동 소멸)." % dropped["name"])


def main(once=False):
    """once=True면 대기 중인 메시지를 한 번만 처리하고 끝낸다.
    2026-08-16 디렉터 "데일리만 남기자" — 상주 봇을 없애고 슬롯 세션이 이 함수를 호출한다."""
    offset = 0
    if os.path.exists(OFFSET_F):
        try:
            offset = int(open(OFFSET_F).read().strip())
        except ValueError:
            pass
    print("[affiliate_bot] 시작 offset=%d %s" % (offset, datetime.now().isoformat()), flush=True)
    while True:
        try:
            d = http("https://api.telegram.org/bot%s/getUpdates?timeout=%d&offset=%d" % (TG["STUDIO_TG_TOKEN"], 0 if once else 50, offset + 1), timeout=70)
            for u in d.get("result", []):
                offset = max(offset, u["update_id"])
                open(OFFSET_F, "w").write(str(offset))
                if u.get("callback_query"):
                    continue   # 승인 게이트 폐지 (2026-08-16) — 옛 버튼이 눌려도 무시
                m = u.get("message") or {}
                if str(m.get("chat", {}).get("id")) != str(TG["STUDIO_TG_CHAT_ID"]):
                    continue
                text = m.get("text") or ""
                try:
                    if "link.coupang.com" in text:
                        print("[affiliate_bot] 링크 회신 감지:", text[:60], flush=True)
                        handle_link(text)
                    elif text.strip() == "스티커":
                        send_sticker_kit()
                    elif text.strip() in ("취소", "cancel"):
                        cancel_last()
                    elif text.strip() in ("허브", "hub"):
                        hub_stats()
                    elif text.strip() == "스토리":
                        story_report()
                except Exception as e:
                    # 오프셋은 이미 전진 — 조용히 삼키면 회신이 영구 유실된다 (2026-08-14 감사)
                    print("[affiliate_bot] 명령 처리 실패:", str(e)[:200], flush=True)
                    tg_send("⚠️ 처리 실패(%s) — 같은 메시지를 다시 보내주세요" % str(e)[:80])
            track_story()   # 스토리 게시 감지·+20h 도달 수집 (A2 계측)
            try:
                from affiliate_gap import check_and_alert
                check_and_alert(tg_send)     # 제휴 공백 24h 경보 (2026-08-16)
            except Exception:
                pass
        except Exception as e:
            print("[affiliate_bot] 오류:", str(e)[:200], flush=True)
            if once:
                return
            time.sleep(30)
        if once:
            return


if __name__ == "__main__":
    import sys
    main(once="--once" in sys.argv)
