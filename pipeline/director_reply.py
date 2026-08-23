#!/usr/bin/env python3
# 디렉터 회신 수신 (2026-08-17 신설 — 디렉터: "기획 텔레그램 왔는데 내가 텔레그램으로 얘기하면 그거 반영해줌?")
#
# 상주 봇 폐지 후 회신은 launchd 10분 틱(affiliate_bot --once)이 logs/director_msgs.jsonl에 기록한다.
# 슬롯 세션의 Bash 도구는 최대 600초까지만 블로킹할 수 있어(2026-08-23 4차 리뷰) 장시간 대기
# 대신 **2단계(mark → collect)**로 쓴다 — 소비 오프셋을 파일로 영속해 호출 사이 도착분도 잡는다:
#
#   ① 기획 요약 발송 직후:  .venv/bin/python3 pipeline/director_reply.py --mark
#      (지금 파일 끝을 기준점으로 기록하고 즉시 종료)
#   ② 준비 작업(~10분: 후보 검토·배경 선정)을 동기로 수행
#   ③ 렌더 시작 직전:      .venv/bin/python3 pipeline/director_reply.py --collect 120
#      (기준점 이후 도착분을 출력. 회신이 이미 있으면 즉시, 없으면 최대 120초 대기)
#
# 구형 사용법(director_reply.py <초>)도 동작한다 — 호출 시점부터 대기(오프셋 미영속).
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(ROOT, "logs", "director_msgs.jsonl")
OFF = os.path.join(ROOT, "logs", ".director_reply.off")


def _size():
    return os.path.getsize(LOG) if os.path.exists(LOG) else 0


def _consume(base):
    """base 오프셋 이후의 완결 줄(개행으로 닫힌)만 파싱해 (메시지들, 새 오프셋, 꼬리 유무)를 돌려준다.
    바이너리로 읽어 UTF-8 문자 경계 seek 예외를 차단하고, 소비분만큼 오프셋을 전진시켜
    손상 줄 재파싱을 막는다. 파일이 줄었으면(절단·교체) 0으로 리셋 — 재생성된 내용은 전부 새 것이다."""
    size = _size()
    if size < base:
        return [], 0, False
    if size == base:
        return [], base, False
    with open(LOG, "rb") as f:
        f.seek(base)
        chunk = f.read(size - base)
    head, sep, tail = chunk.rpartition(b"\n")
    if not sep:
        return [], base, True   # 완결 줄 없음 — 전부 쓰는 중인 꼬리
    msgs = []
    for l in head.split(b"\n"):
        if not l.strip():
            continue
        try:
            msgs.append(json.loads(l.decode("utf-8", "replace"))["text"])
        except Exception:
            print("[director_reply] 손상 줄 건너뜀: %r" % l[:60], flush=True)
    return msgs, base + len(head) + 1, bool(tail)


def _write_off(v):
    tmp = OFF + ".tmp"
    open(tmp, "w").write(str(v))
    os.replace(tmp, OFF)


MARK_TTL = 90 * 60   # mark가 이보다 오래되면 죽은 세션의 잔재로 보고 폐기 (2026-08-23 5차 리뷰)


def mark():
    """지금 파일 끝을 기준점으로 영속 기록 — collect가 여기부터 소비한다."""
    _write_off(json.dumps({"off": _size(), "ts": time.time()}))


def _wait_from(base, seconds, poll):
    """base부터 소비하며 최대 seconds 대기. (메시지들, 최종 오프셋) 반환.
    메시지를 찾으면 무조건 1폴 유예 후 재소비 — 같은 틱 배치의 후속 지시 회수
    (2026-08-23 4차 리뷰: 꼬리 조건부 유예는 완결 줄 배치를 놓치는 회귀였다)."""
    deadline = time.time() + seconds
    msgs, base, _ = _consume(base)          # 이미 도착분 즉시 회수
    while not msgs and time.time() < deadline:
        time.sleep(poll)
        msgs, base, _ = _consume(base)
    if msgs:
        time.sleep(poll)
        more, base, _ = _consume(base)
        msgs += more
    return msgs, base


def collect(seconds=120, poll=5):
    """mark 기준점 이후 도착분을 소비하고 오프셋을 영속 갱신.
    mark가 없거나 MARK_TTL(90분)보다 오래됐으면(mark 후 죽은 세션의 잔재 — 옛 메시지를
    '방금 회신'으로 재배달하는 사고 방지) 지금부터 대기한다."""
    base = None
    try:
        d = json.loads(open(OFF).read())
        if time.time() - float(d.get("ts", 0)) <= MARK_TTL:
            base = int(d["off"])
        else:
            print("[director_reply] 오래된 mark 폐기(%.0f분 경과) — 지금부터 대기"
                  % ((time.time() - float(d.get("ts", 0))) / 60), flush=True)
    except Exception:
        pass
    if base is None:
        base = _size()
    msgs, base = _wait_from(base, seconds, poll)
    _write_off(json.dumps({"off": base, "ts": time.time()}))
    return msgs


def wait(seconds=180, poll=5):
    """구형 단일 호출 — 지금 이후 도착분만 대기(오프셋 미영속). 새 코드는 mark/collect를 써라."""
    msgs, _ = _wait_from(_size(), seconds, poll)
    return msgs


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--mark":
        mark()
    elif len(sys.argv) > 1 and sys.argv[1] == "--collect":
        sec = int(sys.argv[2]) if len(sys.argv) > 2 else 120
        for m in collect(sec):
            print(m)
    else:
        sec = int(sys.argv[1]) if len(sys.argv) > 1 else 180
        if sec > 590:
            # Bash 도구 상한 600초 — 초과 대기는 출력째 죽는다 (2026-08-23 5차: 660 함정 방지)
            print("[director_reply] %d초는 Bash 상한(600초) 초과 — 590초로 줄임. mark/collect 사용 권장" % sec, flush=True)
            sec = 590
        for m in wait(sec):
            print(m)
