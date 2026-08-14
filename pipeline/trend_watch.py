#!/usr/bin/env python3
# 서치부 상시 감시 데몬 (2026-08-13 밤 디렉터: "서치 직원 3명이 계속 정보를 물어오게")
#   45분마다 scan_trends 소스를 순찰해 '처음 보는' 화제만 텔레그램으로 보고한다.
#   직원A=실시간(구글·유튜브·네이버랭킹) / 직원B=커뮤니티(디시·오유·네이트판) / 직원C=미래(아침 브리핑 담당, 여기 아님)
#   스팸 방지: seen 기억(7일), 발송은 최소 2시간 간격, 23시~07시 침묵.
# 실행: nohup .venv/bin/python3 pipeline/trend_watch.py >> logs/trend_watch.log 2>&1 &
import json
import os
import sys
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
import scan_trends as st

SEEN_F = os.path.join(ROOT, "logs", "trend_seen.json")
INTERVAL = 45 * 60
MIN_GAP = 2 * 3600
QUIET = range(23, 24), range(0, 7)


def load_seen():
    # 2026-08-14 감사: 파손 JSON이 pm2 autorestart와 맞물려 무한 크래시 루프가 되지 않게 가드
    try:
        d = json.load(open(SEEN_F, encoding="utf-8"))
        cutoff = time.time() - 7 * 86400
        return {k: v for k, v in d.items() if v > cutoff}
    except Exception:
        return {}


def save_seen(seen):
    tmp = SEEN_F + ".tmp"
    json.dump(seen, open(tmp, "w", encoding="utf-8"))
    os.replace(tmp, SEEN_F)   # 원자적 교체 — 기록 중 크래시로 JSON 파손 방지


def tg(text):
    import urllib.parse, urllib.request
    tgc = st.__dict__  # scan_trends엔 tg가 없다 — 직접
    kv = {}
    for line in open(os.path.join(ROOT, "telegram.env"), encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            kv[k.strip()] = v.strip().strip('"')
    data = urllib.parse.urlencode({"chat_id": kv["STUDIO_TG_CHAT_ID"], "text": text,
                                   "disable_web_page_preview": "true"}).encode()
    urllib.request.urlopen(
        urllib.request.Request("https://api.telegram.org/bot%s/sendMessage" % kv["STUDIO_TG_TOKEN"], data=data),
        timeout=60)


def sweep():
    """전 소스 순찰 → (레인, 제목) 목록"""
    out = []
    lanes = [
        ("A·구글", st.google_trends, lambda r: [t for t, _ in r]),
        ("A·유튜브", st.youtube_trending, lambda r: ["%s (%s)" % (t, ch) for t, ch, _ in r[:8]]),
        ("A·랭킹뉴스", st.naver_ranking_news, lambda r: r),
        ("B·네이트판", st.nate_pann, lambda r: r),
        ("B·디시", st.dcinside_best, lambda r: r),
        ("B·오유", st.todayhumor_best, lambda r: r),
    ]
    for lane, fn, fmt in lanes:
        try:
            for t in fmt(fn()):
                out.append((lane, t.strip()))
        except Exception as e:
            print("[trend_watch] %s 실패: %s" % (lane, str(e)[:80]), flush=True)
    return out


def main():
    print("[trend_watch] 서치부 출근 %s" % datetime.now().isoformat(), flush=True)
    seen = load_seen()
    # 첫 순찰은 기준선 구축만 (전부 seen 처리, 발송 없음)
    for lane, t in sweep():
        seen.setdefault(lane + "|" + t, time.time())
    save_seen(seen)
    last_sent = 0
    while True:
        time.sleep(INTERVAL)
        h = datetime.now().hour
        if h >= 23 or h < 7:
            continue
        seen = load_seen()
        fresh = []
        for lane, t in sweep():
            k = lane + "|" + t
            if k not in seen:
                seen[k] = time.time()
                fresh.append((lane, t))
        save_seen(seen)
        if fresh:
            # 침묵 수집 모드 (2026-08-13 밤): 텔레그램 발송은 서치 직원 세션의 몫 — 여기선 파일로만 쌓는다
            with open(os.path.join(ROOT, "logs", "trend_fresh.jsonl"), "a", encoding="utf-8") as f:
                for lane, t in fresh:
                    f.write(json.dumps({"ts": datetime.now().isoformat(), "lane": lane, "title": t}, ensure_ascii=False) + "\n")
            print("[trend_watch] 신규 %d건 수집" % len(fresh), flush=True)


if __name__ == "__main__":
    main()
