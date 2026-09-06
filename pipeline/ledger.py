#!/usr/bin/env python3
"""연령 고정 성과 장부 — 게시 후 24h/72h/168h 시점의 지표를 한 번씩만 기록한다.

왜 필요한가 (2026-09-05 어벤져스 회의 권고 #2):
  지금까지 성과를 "오늘 조회수"로 비교해 왔는데, 게시 직후 편과 사흘 지난 편이 섞여
  같은 날 같은 지표가 문서마다 달랐다(8/29 릴스 중앙값이 161 vs 456). 편성·형식을
  바꾼 판단이 전부 이 흔들리는 잣대 위에 있었다.
  **연령을 고정해야 비교가 성립한다.** 모든 게시물의 '72시간 시점 조회'를 모으면
  그때 비로소 "3편 체제가 나은가", "카드 희석이 원인인가"를 검정할 수 있다.

동작:
  dm_tick(10분 틱)이 이 스크립트를 부른다. 각 게시물이 24h/72h/168h 경계를 **처음
  지나는 틱**에서만 API를 1회 치고 logs/ledger.jsonl에 append한다. 이미 기록한
  (플랫폼, id, 연령)은 건너뛴다 — 틱마다 전수 조회하지 않는다.

읽는 법:
  .venv/bin/python3 pipeline/ledger.py --report 12   # 12h 시점 (초기 곡선)
  .venv/bin/python3 pipeline/ledger.py --report 72   # 72h 시점 중앙값·n
"""
import json
import os
import sys
import time
import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
LEDGER = os.path.join(ROOT, "logs", "ledger.jsonl")

# 기록할 연령(시간). 경계를 지난 뒤 GRACE 안에 잡히면 그 연령으로 친다.
# 6h·12h를 넣은 이유 (2026-09-06): 24h가 첫 기록이라 **초기 곡선을 볼 수 없었다.**
# 그래서 게시 3~8시간 된 글을 하루 지난 글과 조회수로 비교하는 오판이 났다 —
# 오늘 카드 3장이 303~378인데 어제 카드가 638~773이라 "도달이 떨어졌다"고 읽었다.
# 실제로는 시간당 조회가 오늘 40~102회/h, 어제 9~31회/h로 오늘이 3배 빨랐다.
# 초기 구간이 기록돼 있어야 같은 연령끼리 볼 수 있다.
AGES = (6, 12, 24, 72, 168)
GRACE_H = 4          # 틱이 밀리거나 API가 죽어도 4시간 안에 잡으면 유효
                     # (6h·12h 간격이 좁아져 6시간 유예는 구간이 겹친다)
LOOKBACK = 40        # 각 플랫폼에서 훑을 최근 게시물 수


def _load_done():
    """이미 기록한 (platform, id, age) 집합."""
    done = set()
    if not os.path.exists(LEDGER):
        return done
    with open(LEDGER, encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
                done.add((r["platform"], str(r["id"]), r["age_h"]))
            except Exception:
                continue
    return done


def _append(rec):
    with open(LEDGER, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _due_age(published_iso, now_ts):
    """이 게시물이 지금 어떤 연령으로 기록될 차례인가. 없으면 None."""
    try:
        dt = datetime.datetime.fromisoformat(published_iso.replace("Z", "+00:00"))
    except Exception:
        return None
    hours = (now_ts - dt.timestamp()) / 3600.0
    for a in AGES:
        if a <= hours < a + GRACE_H:
            return a
    return None


def collect_threads(done, now_ts):
    import upload_threads as t
    out = []
    tok = t.token()
    me = t._get("%s/me?fields=id&access_token=%s" % (t.API, tok))["id"]
    r = t._get("%s/%s/threads?fields=id,text,timestamp,media_type&limit=%d&access_token=%s"
               % (t.API, me, LOOKBACK, tok))
    for p in r.get("data", []):
        age = _due_age(p.get("timestamp", ""), now_ts)
        if age is None or ("threads", p["id"], age) in done:
            continue
        try:
            ins = t._get("%s/%s/insights?metric=views,likes,replies,reposts&access_token=%s"
                         % (t.API, p["id"], tok))
            m = {x["name"]: (x.get("values") or [{}])[0].get("value", 0) for x in ins.get("data", [])}
        except Exception as e:
            print("[ledger] threads %s 지표 실패: %s" % (p["id"], str(e)[:60]), flush=True)
            continue
        out.append({
            "platform": "threads", "id": p["id"], "age_h": age,
            "published": p.get("timestamp"), "recorded": _now_iso(now_ts),
            "kind": p.get("media_type"),
            "views": m.get("views", 0), "likes": m.get("likes", 0),
            "replies": m.get("replies", 0), "reposts": m.get("reposts", 0),
            "title": (p.get("text") or "").split("\n")[0][:60],
        })
    return out


def collect_instagram(done, now_ts):
    from upload_instagram import load_keys, api
    kv = load_keys()
    tok = kv["IG_ACCESS_TOKEN"]
    out = []
    r = api("GET", "/me/media", {"fields": "id,caption,media_type,timestamp,like_count,comments_count",
                                 "limit": str(LOOKBACK), "access_token": tok})
    for m in r.get("data", []):
        age = _due_age(m.get("timestamp", ""), now_ts)
        if age is None or ("instagram", m["id"], age) in done:
            continue
        try:
            ins = api("GET", "/%s/insights" % m["id"],
                      {"metric": "views,reach,shares,saved", "access_token": tok})
            d = {x["name"]: x["values"][0]["value"] for x in ins.get("data", [])}
        except Exception as e:
            print("[ledger] ig %s 지표 실패: %s" % (m["id"], str(e)[:60]), flush=True)
            continue
        out.append({
            "platform": "instagram", "id": m["id"], "age_h": age,
            "published": m.get("timestamp"), "recorded": _now_iso(now_ts),
            "kind": m.get("media_type"),
            "views": d.get("views", 0), "reach": d.get("reach", 0),
            "shares": d.get("shares", 0), "saved": d.get("saved", 0),
            "likes": m.get("like_count", 0), "comments": m.get("comments_count", 0),
            "title": (m.get("caption") or "").split("\n")[0][:60],
        })
    return out


def collect_youtube(done, now_ts):
    from googleapiclient.discovery import build
    from google_creds import load_creds
    yt = build("youtube", "v3", credentials=load_creds())
    ch = yt.channels().list(part="contentDetails", mine=True).execute()["items"][0]
    up = ch["contentDetails"]["relatedPlaylists"]["uploads"]
    pl = yt.playlistItems().list(part="contentDetails", playlistId=up,
                                 maxResults=min(LOOKBACK, 50)).execute()
    ids = [i["contentDetails"]["videoId"] for i in pl.get("items", [])]
    out = []
    for i in range(0, len(ids), 50):
        vs = yt.videos().list(part="statistics,snippet", id=",".join(ids[i:i + 50])).execute()
        for v in vs.get("items", []):
            sn, st = v["snippet"], v["statistics"]
            age = _due_age(sn.get("publishedAt", ""), now_ts)
            if age is None or ("youtube", v["id"], age) in done:
                continue
            out.append({
                "platform": "youtube", "id": v["id"], "age_h": age,
                "published": sn.get("publishedAt"), "recorded": _now_iso(now_ts),
                "kind": "VIDEO",
                "views": int(st.get("viewCount", 0)), "likes": int(st.get("likeCount", 0)),
                "comments": int(st.get("commentCount", 0)),
                "title": sn.get("title", "")[:60],
            })
    return out


def _now_iso(ts):
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%dT%H:%M:%S")


def run():
    now_ts = time.time()
    done = _load_done()
    total = 0
    for name, fn in (("threads", collect_threads), ("instagram", collect_instagram),
                     ("youtube", collect_youtube)):
        try:
            for rec in fn(done, now_ts):
                _append(rec)
                total += 1
                print("[ledger] %s %dh %s (%s회)" % (rec["platform"], rec["age_h"],
                                                    rec["title"][:32], rec["views"]), flush=True)
        except Exception as e:
            # 한 플랫폼이 죽어도 나머지는 기록한다 — 장부의 구멍이 판정을 막는다
            print("[ledger] %s 수집 실패(무해, 다음 틱 재시도): %s" % (name, str(e)[:90]), flush=True)
    if total:
        print("[ledger] %d건 기록" % total, flush=True)
    return total


def report(age=72, days=30):
    """연령 고정 지표 요약 — 플랫폼·유형별 중앙값과 n."""
    import collections
    if not os.path.exists(LEDGER):
        print("장부가 비어 있다 — 첫 기록은 게시 24시간 뒤부터 쌓인다")
        return
    cut = (datetime.datetime.now() - datetime.timedelta(days=days)).strftime("%Y-%m-%d")
    rows = collections.defaultdict(list)
    with open(LEDGER, encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("age_h") != age or (r.get("published") or "")[:10] < cut:
                continue
            rows[(r["platform"], r.get("kind") or "?")].append(r)
    if not rows:
        print("%dh 시점 기록이 아직 없다 (최근 %d일)" % (age, days))
        return
    print("=== %dh 시점 성과 (최근 %d일) ===" % (age, days))
    print("  %-10s %-16s %4s %8s %8s %8s" % ("플랫폼", "유형", "n", "중앙값", "평균", "최고"))
    for (plat, kind), rs in sorted(rows.items()):
        vs = sorted(r["views"] for r in rs)
        med = vs[len(vs) // 2]
        print("  %-10s %-16s %4d %8d %8d %8d"
              % (plat, kind[:16], len(vs), med, sum(vs) // len(vs), vs[-1]))
    print()
    print("  ※ 중앙값·n을 함께 보라. 평균은 이상치 1건에 끌려간다")
    print("    (2026-09-05 실사고: '스레드 12개 평균 1,492'의 64%가 글 1건이었다)")


if __name__ == "__main__":
    if "--report" in sys.argv:
        i = sys.argv.index("--report")
        a = int(sys.argv[i + 1]) if len(sys.argv) > i + 1 and sys.argv[i + 1].isdigit() else 72
        report(age=a)
    else:
        run()
