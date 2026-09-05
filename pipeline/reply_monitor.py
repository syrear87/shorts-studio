#!/usr/bin/env python3
"""스레드 답글 수집·반박 감지 — 시스템이 남의 말을 읽을 수 있게 한다.

왜 필요한가 (2026-09-05 어벤져스 회의 권고 #3):
  9/4 SSD 카드에 답글 25건이 달렸고 그중 10건이 반박이었는데, 시스템은 그 사실을
  **알 수 없었다.** 디렉터가 "민심이 안 좋다"고 말해줄 때까지 아무도 몰랐다.
  정정이 늦은 게 아니라 무인지였다. 답글을 읽지 못하면 사고가 났는지도 모른다.

동작:
  dm_tick(10분 틱)이 부른다. 최근 72시간 글의 답글을 모아 logs/threads_replies.jsonl에
  append하고, 새 답글 중 반박·불만 신호가 임계를 넘으면 텔레그램으로 한 번 알린다.
  자동 회신은 하지 않는다 — 판단은 세션·디렉터의 몫이다(회신 금지 방침).

읽는 법:
  .venv/bin/python3 pipeline/reply_monitor.py --report      # 최근 반박률·미확인 글
"""
import json
import os
import re
import subprocess
import sys
import time
import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
STORE = os.path.join(ROOT, "logs", "threads_replies.jsonl")
ALERTED = os.path.join(ROOT, "logs", ".reply_alerted")

WINDOW_H = 72          # 답글은 게시 후 사흘이면 대개 끝난다
ALERT_MIN = 3          # 한 글에 반박이 이만큼 쌓이면 알린다
ALERT_RATIO = 0.35     # 또는 답글의 이 비율 이상이 반박이면

# 반박·불만 신호. 우리 채널 실제 답글에서 뽑았다(9/4 SSD 25건, 카메라·광장시장 편).
NEGATIVE = (
    "아니", "틀렸", "틀린", "잘못", "오류", "사실이 아", "말이 안", "말도 안",
    "비교가", "비교 자체", "어디서", "어디가", "누가", "왜 이렇게",
    "어그로", "바이럴", "광고", "협찬", "낚시", "선동", "거지",
    "모르고", "알고 만들", "제대로", "확인은", "검색만", "AI가", "ai로",
    "아닌데", "인데요", "아닙니다", "아니라", "그건 아", "이게 맞",
    "?" * 2, "ㅉㅉ", "ㅋㅋㅋㅋ",
    # 되묻는 반박 — 단정 대신 의문으로 치는 형태가 실제로는 가장 흔했다(9/5 실측 3건 미탐)
    "한다고?", "하다고?", "산다고?", "된다고?", "맞다고?", "라고?",
    "하기엔", "라고 하기", "치고는", "치곤",
    "는요?", "은요?", "인가요?", "아닌가", "않나요", "않았나",
)
# 되묻기 판정: '~은/는?' 꼴로 끝나면 우리 주장의 빠진 부분을 지적하는 것이다
#   예) "클라우드 연동은?" — 우리가 안 다룬 축을 되묻는 전형
_ASK_BACK = re.compile(r"[가-힣]{2,}(은|는|랑|이랑|와|과)\?")
# 누락 지적: "…는 얘기가 없네", "…는 안 나오네" — 우리가 빠뜨린 항목을 짚는 형태
#   예) "센서크기는 얘기가 없넹" (9/5 카메라 편, 실제로 우리 카드에 센서가 없었다)
_MISSING = re.compile(r"(얘기|말|언급|설명|내용)[이가은는]?\s*(없|안|빠)"
                      r"|(없네|없넹|없음|없다|안 나오|안나오|빠졌)")
# 오탐 방지 — 우호적 맥락에서 흔한 표현
FRIENDLY = ("감사", "고마", "좋네", "좋아요", "유익", "잘 봤", "잘봤", "터져라", "화이팅", "응원")


def _load_seen():
    seen = set()
    if not os.path.exists(STORE):
        return seen
    with open(STORE, encoding="utf-8") as f:
        for line in f:
            try:
                seen.add(json.loads(line)["reply_id"])
            except Exception:
                continue
    return seen


def _is_negative(text):
    t = (text or "").strip()
    if any(k in t for k in FRIENDLY):
        return False
    if any(k in t for k in NEGATIVE):
        return True
    return bool(_ASK_BACK.search(t) or _MISSING.search(t))


def _tg(msg):
    try:
        subprocess.run(["bash", os.path.join(ROOT, "bin", "tg-send.sh"), msg],
                       timeout=30, check=False)
    except Exception:
        pass


def collect():
    import upload_threads as t
    now = time.time()
    seen = _load_seen()
    tok = t.token()
    me = t._get("%s/me?fields=id,username&access_token=%s" % (t.API, tok))
    my_id, my_name = me["id"], me.get("username")
    posts = t._get("%s/%s/threads?fields=id,text,timestamp&limit=25&access_token=%s"
                   % (t.API, my_id, tok)).get("data", [])
    new_total, flagged = 0, []
    for p in posts:
        try:
            dt = datetime.datetime.fromisoformat((p.get("timestamp") or "").replace("Z", "+00:00"))
        except Exception:
            continue
        if (now - dt.timestamp()) / 3600 > WINDOW_H:
            continue
        try:
            rep = t._get("%s/%s/replies?fields=id,text,username,timestamp&access_token=%s"
                         % (t.API, p["id"], tok)).get("data", [])
        except Exception as e:
            print("[replies] %s 조회 실패: %s" % (p["id"], str(e)[:60]), flush=True)
            continue
        neg, tot = 0, 0
        for x in rep:
            if x.get("username") == my_name:      # 우리 답글(정정·링크)은 제외
                continue
            tot += 1
            is_neg = _is_negative(x.get("text"))
            neg += is_neg
            if x["id"] in seen:
                continue
            with open(STORE, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "reply_id": x["id"], "post_id": p["id"],
                    "post_title": (p.get("text") or "").split("\n")[0][:60],
                    "username": x.get("username"), "text": (x.get("text") or "")[:400],
                    "timestamp": x.get("timestamp"), "negative": bool(is_neg),
                    "recorded": datetime.datetime.fromtimestamp(now).strftime("%Y-%m-%dT%H:%M:%S"),
                }, ensure_ascii=False) + "\n")
            new_total += 1
        if tot and (neg >= ALERT_MIN or neg / tot >= ALERT_RATIO) and neg >= 2:
            flagged.append((p["id"], (p.get("text") or "").split("\n")[0][:44], neg, tot))
    return new_total, flagged


def alert(flagged):
    """글당 한 번만 알린다 — 틱마다 같은 경보를 반복하지 않는다."""
    done = set()
    if os.path.exists(ALERTED):
        done = set(open(ALERTED, encoding="utf-8").read().split())
    fresh = [f for f in flagged if f[0] not in done]
    if not fresh:
        return 0
    lines = ["⚠️ 스레드 반박 답글 감지 — 사실 확인이 필요할 수 있습니다", ""]
    for pid, title, neg, tot in fresh:
        lines.append("· %s" % title)
        lines.append("  반박 %d / 답글 %d" % (neg, tot))
    lines.append("")
    lines.append("원문: .venv/bin/python3 pipeline/reply_monitor.py --report")
    _tg("\n".join(lines))
    with open(ALERTED, "a", encoding="utf-8") as f:
        for pid, *_ in fresh:
            f.write(pid + "\n")
    return len(fresh)


def report(days=7):
    if not os.path.exists(STORE):
        print("수집된 답글이 없다")
        return
    import collections
    cut = (datetime.datetime.now() - datetime.timedelta(days=days)).strftime("%Y-%m-%d")
    by = collections.defaultdict(list)
    for line in open(STORE, encoding="utf-8"):
        try:
            r = json.loads(line)
        except Exception:
            continue
        if (r.get("timestamp") or "")[:10] < cut:
            continue
        by[r["post_title"]].append(r)
    if not by:
        print("최근 %d일 답글 없음" % days)
        return
    tot = sum(len(v) for v in by.values())
    neg = sum(1 for v in by.values() for r in v if r.get("negative"))
    print("=== 최근 %d일 스레드 답글 — %d건 중 반박 %d건 (%.0f%%) ===" % (days, tot, neg, neg / tot * 100))
    print()
    for title, rs in sorted(by.items(), key=lambda x: -sum(1 for r in x[1] if r.get("negative"))):
        n = sum(1 for r in rs if r.get("negative"))
        print("■ %s — 답글 %d (반박 %d)" % (title, len(rs), n))
        for r in rs:
            mark = "🔴" if r.get("negative") else "  "
            print("   %s @%-16s %s" % (mark, r.get("username"), (r.get("text") or "").replace("\n", " ")[:96]))
        print()
    print("※ 반박률 목표 15% 미만 (2026-09-05 어벤져스 판정 기준). 9/4 SSD 편은 40%였다.")


if __name__ == "__main__":
    if "--report" in sys.argv:
        report()
    else:
        n, flagged = collect()
        sent = alert(flagged)
        if n or sent:
            print("[replies] 새 답글 %d건 · 경보 %d건" % (n, sent), flush=True)
