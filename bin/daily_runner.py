#!/usr/bin/env python3
# launchd가 매일 07:30 KST에 실행 — 헤드리스 스튜디오 데이 세션 기동.
# 락으로 중복 방지, 100분 타임아웃, 로그 저장, 실패 시 텔레그램 통보.
import os, shutil, subprocess, sys, time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCK = ROOT / "logs" / ".daily.lock"
LOG = ROOT / "logs" / ("daily-%s.log" % datetime.now().strftime("%Y%m%d-%H%M"))
TIMEOUT = 100 * 60
STALE = 110 * 60

def tg(msg):
    try:
        subprocess.run(["bash", str(ROOT / "bin" / "tg-send.sh"), msg], timeout=30)
    except Exception:
        pass

def main():
    os.chdir(str(ROOT))
    (ROOT / "logs").mkdir(exist_ok=True)
    if LOCK.exists():
        age = time.time() - LOCK.stat().st_mtime
        if age < STALE:
            tg("⏳ 숏츠 데일리: 이전 세션이 아직 실행 중 — 오늘 기동 건너뜀")
            return
        LOCK.unlink()
    claude = shutil.which("claude") or str(Path.home() / ".claude/local/claude")
    if not Path(claude).exists() and not shutil.which("claude"):
        tg("⚠️ 숏츠 데일리: claude CLI를 찾지 못해 기동 실패")
        sys.exit(1)
    prompt = (ROOT / "DAILY_PROMPT.md").read_text(encoding="utf-8")
    LOCK.write_text(str(os.getpid()))
    try:
        with open(LOG, "w") as lf:
            r = subprocess.run(
                [claude, "-p", prompt, "--model", "opus", "--permission-mode", "acceptEdits"],
                stdout=lf, stderr=subprocess.STDOUT, timeout=TIMEOUT, cwd=str(ROOT))
        if r.returncode != 0:
            tg("⚠️ 숏츠 데일리 세션 비정상 종료 (코드 %d) — %s 확인" % (r.returncode, LOG.name))
    except subprocess.TimeoutExpired:
        tg("⚠️ 숏츠 데일리 세션 타임아웃(100분) — %s 확인" % LOG.name)
    finally:
        LOCK.unlink(missing_ok=True)

if __name__ == "__main__":
    main()
