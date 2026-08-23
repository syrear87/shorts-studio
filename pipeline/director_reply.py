#!/usr/bin/env python3
# 디렉터 회신 수신 (2026-08-17 신설 — 디렉터: "기획 텔레그램 왔는데 내가 텔레그램으로 얘기하면 그거 반영해줌?")
#
# 그동안은 슬롯 세션이 기획 요약을 보내고 **답장을 기다리지 않고** 진행했다.
# 이제 상주 봇이 디렉터의 일반 텍스트를 logs/director_msgs.jsonl에 기록하고,
# 슬롯 세션이 이 모듈로 그 회신을 받아 반영한다.
#
# 사용: .venv/bin/python3 pipeline/director_reply.py 660
#   → 최대 660초 대기(회신 기록자가 10분 launchd 틱뿐이라 틱 1회를 보장하는 창).
#     회신이 오면 즉시 출력하고 종료(exit 0), 없으면 빈 출력(exit 0).
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(ROOT, "logs", "director_msgs.jsonl")


def _consume(base):
    """base 오프셋 이후의 완결 줄(개행으로 닫힌)만 파싱해 (메시지들, 새 오프셋, 꼬리 유무)를 돌려준다.
    2026-08-23 2차 리뷰: ①바이너리로 읽어 UTF-8 문자 경계 seek 예외 차단 ②소비한 만큼
    오프셋을 전진시켜 손상 줄 재파싱·재경고 방지 ③꼬리 조각(쓰는 중)은 남겨 다음 폴에.
    3차 리뷰: 파일 축소(절단·교체) 시 오프셋 리셋 — 영구 블라인드 방지."""
    size = os.path.getsize(LOG) if os.path.exists(LOG) else 0
    if size < base:
        return [], size, False   # 파일이 줄었다 — 절단/교체로 보고 현재 끝으로 리셋
    if size == base:
        return [], base, False
    with open(LOG, "rb") as f:
        f.seek(base)
        chunk = f.read(size - base)
    head, sep, tail = chunk.rpartition(b"\n")
    if not sep:
        return [], base, True   # 완결 줄 없음 — 전부 꼬리(쓰는 중)
    msgs = []
    for l in head.split(b"\n"):
        if not l.strip():
            continue
        try:
            msgs.append(json.loads(l.decode("utf-8", "replace"))["text"])
        except Exception:
            print("[director_reply] 손상 줄 건너뜀: %r" % l[:60], flush=True)
    return msgs, base + len(head) + 1, bool(tail)


def wait(seconds=660, poll=5):
    """지금 이후로 들어오는 디렉터 메시지를 기다린다. 반환: 새 메시지 리스트(문자열).
    기본 660초 (2026-08-23 3차 리뷰): 회신 기록자가 launchd 10분 틱뿐이라 180초 창은
    ~70%를 놓쳤다 — 틱 1회가 반드시 지나가는 11분이 실효 하한이다."""
    base = os.path.getsize(LOG) if os.path.exists(LOG) else 0
    deadline = time.time() + seconds
    while time.time() < deadline:
        time.sleep(poll)
        msgs, base, tail = _consume(base)
        if msgs:
            if tail and time.time() < deadline:
                # 꼬리 조각이 실제로 있을 때만 한 폴 유예 — 반환 직후 완결되는 후속 지시 회수
                time.sleep(poll)
                more, base, _ = _consume(base)
                msgs += more
            return msgs
    return []


if __name__ == "__main__":
    sec = int(sys.argv[1]) if len(sys.argv) > 1 else 660
    msgs = wait(sec)
    for m in msgs:
        print(m)
