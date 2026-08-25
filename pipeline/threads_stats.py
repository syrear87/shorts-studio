#!/usr/bin/env python3
# 스레드 성과 요약 (2026-08-24 디렉터 지시: "매일 결산에 스레드 인사이트 포함")
#
# 사용: .venv/bin/python3 pipeline/threads_stats.py
#   → 계정 7일 지표 + 전일 대비 증감 + 최근 글 상위 성적을 텍스트로 출력(결산 보고에 붙여 쓴다).
#
# 스냅샷을 logs/threads_stats.jsonl에 append해 다음 실행의 증감 기준으로 쓴다.
# ⚠️ 앱에서만 보이는 것: 조회 출처(추천/프로필/검색)·팔로워 인구통계(100팔로워 미만 잠금).
#    API로는 안 내려오므로 결산에 '앱 확인 필요' 항목으로만 남긴다.
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import upload_threads as th

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAP = os.path.join(ROOT, "logs", "threads_stats.jsonl")
ACCOUNT_METRICS = ("views", "likes", "replies", "reposts", "quotes", "followers_count")


def account(tok, me, days=7):
    out = {}
    now = int(time.time())
    for m in ACCOUNT_METRICS:
        try:
            q = "%s/%s/threads_insights?metric=%s&access_token=%s" % (th.API, me, m, tok)
            if m != "followers_count":
                q += "&since=%d&until=%d" % (now - days * 86400, now)
            row = th._get(q)["data"][0]
            v = row.get("total_value", {}).get("value")
            if v is None and row.get("values"):
                v = sum(x.get("value", 0) for x in row["values"])
            out[m] = v or 0
        except Exception:
            out[m] = None
    return out


def posts(tok, me, limit=12):
    d = th._get("%s/%s/threads?fields=id,text,timestamp&limit=%d&access_token=%s"
                % (th.API, me, limit, tok))
    rows = []
    for it in d.get("data", []):
        try:
            ins = th._get("%s/%s/insights?metric=views,likes,replies,reposts,quotes&access_token=%s"
                          % (th.API, it["id"], tok))["data"]
            v = {i["name"]: (i["values"][0]["value"] if i.get("values")
                             else i.get("total_value", {}).get("value", 0)) for i in ins}
        except Exception:
            continue
        rows.append({"ts": it["timestamp"], "views": v.get("views", 0) or 0,
                     "eng": sum((v.get(k, 0) or 0) for k in ("likes", "replies", "reposts", "quotes")),
                     "head": (it.get("text") or "").split("\n")[0][:30]})
    return rows


def last_snap():
    try:
        lines = [l for l in open(SNAP, encoding="utf-8") if l.strip()]
        return json.loads(lines[-1]) if lines else None
    except Exception:
        return None


def main():
    tok = th.token()
    me = th._get("%s/me?fields=id&access_token=%s" % (th.API, tok))["id"]
    acc = account(tok, me)
    rows = posts(tok, me)
    prev = last_snap()

    def delta(key):
        if not prev or prev.get(key) is None or acc.get(key) is None:
            return ""
        d = acc[key] - prev[key]
        return " (%+d)" % d if d else " (=)"

    print("🧵 스레드 (최근 7일 누적)")
    print("- 팔로워 %s명%s" % (acc.get("followers_count"), delta("followers_count")))
    print("- 조회 %s회%s · 좋아요 %s%s · 답글 %s · 퍼감 %s"
          % (acc.get("views"), delta("views"), acc.get("likes"), delta("likes"),
             acc.get("replies"), (acc.get("reposts") or 0) + (acc.get("quotes") or 0)))
    if rows:
        avg = sum(r["views"] for r in rows) / len(rows)
        n750 = sum(1 for r in rows if r["views"] >= 750)
        print("- 최근 %d개 평균 %.0f회 · 750회+ %d개 (보너스 기준 참고)" % (len(rows), avg, n750))
        print("- 상위 3:")
        for r in sorted(rows, key=lambda r: -r["views"])[:3]:
            print("   %s %s회(반응%d) %s" % (r["ts"][5:10], r["views"], r["eng"], r["head"]))
    print("- ⚠️ 조회 출처·팔로워 인구통계는 앱 인사이트에서만 확인 가능")

    snap = dict(acc)
    snap["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    # ⚠️ 전부 None인 스냅샷을 쌓으면 "끊긴 것"이 아니라 "거짓 데이터가 쌓인 것"이 돼
    #    다음날 증감이 조용히 사라지고, 스냅샷 존재 여부로는 탐지되지 않는다 (2026-08-25 감사).
    #    토큰 만료·권한 변경이 이 형태로 나타나므로 실패로 끝내 dm 틱이 성공 도장을 못 찍게 한다.
    if snap.get("followers_count") is None and snap.get("views") is None:
        msg = "⚠️ 스레드 지표 조회 실패(전 항목 None) — 토큰 만료·권한 확인 필요. 스냅샷을 남기지 않음"
        print(msg, flush=True)
        try:
            import subprocess
            subprocess.run(["bash", os.path.join(ROOT, "bin", "tg-send.sh"), msg],
                           check=False, timeout=30)
        except Exception:
            pass
        sys.exit(1)
    with open(SNAP, "a", encoding="utf-8") as f:
        f.write(json.dumps(snap, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
