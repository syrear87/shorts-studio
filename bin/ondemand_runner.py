#!/usr/bin/env python3
# 온디맨드 실행 감시자 — launchd가 1분마다 실행.
# Cowork 세션이 logs/.run_request 파일에 작업명을 쓰면 화이트리스트 내에서 실행한다.
import subprocess, sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQ = ROOT / "logs" / ".run_request"
LOCK = ROOT / "logs" / ".ondemand.lock"
LOG = ROOT / "logs" / "ondemand.log"

# 화이트리스트: 요청명 → 명령 (로그인 셸 경유로 PATH 복원)
JOBS = {
    "run_today": 'bash run_today.sh',
    "daily": '/usr/bin/python3 bin/daily_runner.py',
}

def log(msg):
    with open(LOG, "a") as f:
        f.write("%s %s\n" % (datetime.now().strftime("%m-%d %H:%M:%S"), msg))

def main():
    if not REQ.exists():
        return
    if LOCK.exists():
        import time
        if time.time() - LOCK.stat().st_mtime < 110 * 60:
            return  # 실행 중 — 요청 유지, 다음 틱에 재확인
        LOCK.unlink()
    job = REQ.read_text().strip()
    REQ.unlink()
    if job not in JOBS:
        log("무시: 알 수 없는 요청 %r" % job)
        return
    LOCK.write_text(job)
    log("실행 시작: %s" % job)
    try:
        r = subprocess.run(["/bin/zsh", "-l", "-c", JOBS[job]],
                           cwd=str(ROOT), capture_output=True, text=True, timeout=110 * 60)
        log("종료 코드 %d: %s" % (r.returncode, job))
        if r.returncode != 0:
            with open(ROOT / "logs" / ("ondemand-%s-fail.log" % job), "w") as f:
                f.write(r.stdout[-3000:] + "\n" + r.stderr[-3000:])
    except Exception as e:
        log("오류: %s" % e)
    finally:
        LOCK.unlink()

if __name__ == "__main__":
    main()
