#!/usr/bin/env python3
# 디렉터 회신 수신 (2026-08-17 신설 — 디렉터: "기획 텔레그램 왔는데 내가 텔레그램으로 얘기하면 그거 반영해줌?")
#
# 그동안은 슬롯 세션이 기획 요약을 보내고 **답장을 기다리지 않고** 진행했다.
# 이제 상주 봇이 디렉터의 일반 텍스트를 logs/director_msgs.jsonl에 기록하고,
# 슬롯 세션이 이 모듈로 그 회신을 받아 반영한다.
#
# 사용: .venv/bin/python3 pipeline/director_reply.py 180
#   → 최대 180초 대기. 회신이 오면 즉시 출력하고 종료(exit 0), 없으면 빈 출력(exit 0).
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(ROOT, "logs", "director_msgs.jsonl")


def _count():
    if not os.path.exists(LOG):
        return 0
    with open(LOG, encoding="utf-8") as f:
        return sum(1 for _ in f)


def wait(seconds=180, poll=5):
    """지금 이후로 들어오는 디렉터 메시지를 기다린다. 반환: 새 메시지 리스트(문자열)."""
    base = _count()
    deadline = time.time() + seconds
    while time.time() < deadline:
        time.sleep(poll)
        if _count() > base:
            with open(LOG, encoding="utf-8") as f:
                rows = [json.loads(l) for l in f if l.strip()]
            return [r["text"] for r in rows[base:]]
    return []


if __name__ == "__main__":
    sec = int(sys.argv[1]) if len(sys.argv) > 1 else 180
    msgs = wait(sec)
    for m in msgs:
        print(m)
