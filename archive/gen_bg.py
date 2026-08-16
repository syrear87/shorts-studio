#!/usr/bin/env python3
# 생성형 배경 (2026-08-16 — 디렉터: 경쟁 채널 '만약에 랩'이 "내용에 딱 맞는 영상"으로
#   구독 181명에 조회 1.2만을 낸다는 관찰에서 도입. 우리 최대 약점이 배경-내용 불일치였다).
#
# 왜 필요한가: 스톡(Pexels)에는 "물이 50cm 찬 도로의 차", "13척이 막아선 해협" 같은
#   장면이 애초에 없다. 검색어를 바꿔도 분위기만 비슷한 무관한 영상이 나온다.
#
# ⚠️ 금지선 (2026-08-16 확정): **지도·도해·개념 시각화만 만든다.**
#   실제 사건을 촬영한 것처럼 보이는 영상은 만들지 않는다 — 우리 자산은 신뢰다.
#   프롬프트에 실존 인물·특정 사건 재현을 넣지 마라.
#
# 사용: python3 pipeline/gen_bg.py "prompt" out/bg_gen/이름.mp4 [--seconds 5]
import json
import os
import sys
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEN_DIR = os.path.join(ROOT, "assets", "bg_gen")
LEDGER = os.path.join(ROOT, "logs", "bg_gen.jsonl")
DAILY_CAP = 3          # 하루 생성 상한 (넘으면 정지 — 요금 폭주 방지)
MODEL = "fal-ai/wan-25-preview/text-to-video"   # 720p $0.10/s로 가장 저렴한 축
BANNED = ("실제", "촬영", "뉴스 영상", "cctv", "CCTV", "실화", "재현", "photo of a real")


def _key():
    for line in open(os.path.join(ROOT, "keys.env"), encoding="utf-8"):
        line = line.strip()
        if line.startswith("FAL_KEY="):
            return line.split("=", 1)[1].strip().strip('"')
    raise RuntimeError("keys.env에 FAL_KEY가 없다")


def _today_count():
    if not os.path.exists(LEDGER):
        return 0
    day = time.strftime("%Y-%m-%d")
    n = 0
    for line in open(LEDGER, encoding="utf-8"):
        try:
            if json.loads(line).get("ts", "").startswith(day):
                n += 1
        except Exception:
            pass
    return n


def _req(url, payload=None, key=None, method=None):
    data = json.dumps(payload).encode() if payload is not None else None
    r = urllib.request.Request(url, data=data, method=method or ("POST" if data else "GET"))
    r.add_header("Authorization", "Key %s" % key)
    r.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(r, timeout=120) as resp:
        return json.load(resp)


def generate(prompt, out_path, seconds=5, resolution="720p", aspect_ratio="9:16", timeout_s=600):
    """프롬프트로 세로 배경 영상을 만들어 out_path에 저장한다. 이미 있으면 재사용."""
    if os.path.exists(out_path):
        print("[gen_bg] 이미 있음 — 재사용:", out_path, flush=True)
        return out_path
    low = prompt.lower()
    for b in BANNED:
        if b.lower() in low:
            raise RuntimeError("프롬프트 거절: 실사 재현 금지어 '%s' — 도해·개념 시각화로 바꿔라" % b)
    n = _today_count()
    if n >= DAILY_CAP:
        raise RuntimeError("오늘 생성 상한(%d) 도달 — 남용 방지. 내일 다시." % DAILY_CAP)
    key = _key()
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    sub = _req("https://queue.fal.run/" + MODEL,
               {"prompt": prompt, "duration": seconds,
                "resolution": resolution, "aspect_ratio": aspect_ratio,
                "enable_prompt_expansion": True}, key)
    sid, surl = sub.get("request_id"), sub.get("status_url")
    print("[gen_bg] 요청 %s — 대기" % sid, flush=True)
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        time.sleep(8)
        st = _req(surl, key=key)
        s = st.get("status")
        if s == "COMPLETED":
            break
        if s in ("FAILED", "ERROR"):
            raise RuntimeError("생성 실패: %s" % str(st)[:250])
    else:
        raise RuntimeError("생성 시간 초과(%ds)" % timeout_s)
    res = _req(sub["response_url"], key=key)
    video_url = (res.get("video") or {}).get("url") or res.get("url")
    if not video_url:
        raise RuntimeError("응답에 영상 URL이 없다: %s" % str(res)[:250])
    urllib.request.urlretrieve(video_url, out_path)
    with open(LEDGER, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "prompt": prompt[:200],
                            "out": os.path.basename(out_path), "seconds": seconds,
                            "est_usd": round(0.10 * seconds, 3)}, ensure_ascii=False) + "\n")
    print("[gen_bg] 완료: %s (약 $%.2f)" % (out_path, 0.10 * seconds), flush=True)
    return out_path


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) < 2:
        sys.exit('사용: gen_bg.py "prompt" out.mp4 [seconds]')
    generate(a[0], a[1], int(a[2]) if len(a) > 2 else 5)
