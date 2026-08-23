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


def _consume(base):
    """base 오프셋 이후의 완결 줄(개행으로 닫힌)만 파싱해 (메시지들, 새 오프셋)을 돌려준다.
    2026-08-23 2차 리뷰: ①바이너리로 읽어 UTF-8 문자 경계 seek 예외 차단 ②소비한 만큼
    오프셋을 전진시켜 손상 줄 재파싱·재경고 방지 ③꼬리 조각(쓰는 중)은 남겨 다음 폴에."""
    size = os.path.getsize(LOG) if os.path.exists(LOG) else 0
    if size <= base:
        return [], base
    with open(LOG, "rb") as f:
        f.seek(base)
        chunk = f.read(size - base)
    head, nl, _tail = chunk.rpartition(b"\n")
    if not nl:
        return [], base   # 완결 줄 없음
    msgs = []
    for l in head.split(b"\n"):
        if not l.strip():
            continue
        try:
            msgs.append(json.loads(l.decode("utf-8", "replace"))["text"])
        except Exception:
            print("[director_reply] 손상 줄 건너뜀: %r" % l[:60], flush=True)
    return msgs, base + len(head) + 1


def wait(seconds=180, poll=5):
    """지금 이후로 들어오는 디렉터 메시지를 기다린다. 반환: 새 메시지 리스트(문자열).
    2026-08-23 감사: 5초마다 파일 전체 재독 → 시작 오프셋 이후 증가분만 소비한다."""
    base = os.path.getsize(LOG) if os.path.exists(LOG) else 0
    deadline = time.time() + seconds
    while time.time() < deadline:
        time.sleep(poll)
        msgs, base = _consume(base)
        if msgs:
            # 꼬리 조각이 남아 있으면 한 폴만 더 기다려 함께 회수 (반환 직후 완결되는 두 번째 지시 유실 방지)
            time.sleep(poll)
            more, base = _consume(base)
            return msgs + more
    return []


if __name__ == "__main__":
    sec = int(sys.argv[1]) if len(sys.argv) > 1 else 180
    msgs = wait(sec)
    for m in msgs:
        print(m)
