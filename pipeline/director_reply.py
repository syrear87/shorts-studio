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


def wait(seconds=180, poll=5):
    """지금 이후로 들어오는 디렉터 메시지를 기다린다. 반환: 새 메시지 리스트(문자열).
    2026-08-23 감사: 5초마다 파일 전체 재독 → 시작 시점 크기를 기억하고 크기 변화만 감시,
    증가분(f.seek)만 파싱한다. jsonl이 무기한 성장해도 폴링 비용이 커지지 않는다."""
    base_size = os.path.getsize(LOG) if os.path.exists(LOG) else 0
    deadline = time.time() + seconds
    while time.time() < deadline:
        time.sleep(poll)
        size = os.path.getsize(LOG) if os.path.exists(LOG) else 0
        if size > base_size:
            with open(LOG, encoding="utf-8") as f:
                f.seek(base_size)
                return [json.loads(l)["text"] for l in f if l.strip()]
    return []


if __name__ == "__main__":
    sec = int(sys.argv[1]) if len(sys.argv) > 1 else 180
    msgs = wait(sec)
    for m in msgs:
        print(m)
