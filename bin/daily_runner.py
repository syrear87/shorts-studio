#!/usr/bin/env python3
# launchd가 평일 08/11/17/20시·주말 09/12/15/18/21시(KST)에 실행 — 헤드리스 스튜디오 세션 기동.
# 락으로 중복 방지, 100분 타임아웃, 로그 저장, 실패·무산출 시 텔레그램 통보.
import os, shutil, subprocess, sys, time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCK = ROOT / "logs" / ".daily.lock"
LOG = ROOT / "logs" / ("daily-%s.log" % datetime.now().strftime("%Y%m%d-%H%M"))
TIMEOUT = 100 * 60
STALE = 110 * 60


def find_claude():
    c = shutil.which("claude")
    if c:
        return c
    home = Path.home()
    for p in ["/opt/homebrew/bin/claude", "/usr/local/bin/claude",
              str(home / ".local/bin/claude"), str(home / ".claude/local/claude"),
              str(home / ".npm-global/bin/claude"), str(home / "bin/claude")]:
        if Path(p).exists():
            return p
    try:
        out = subprocess.run(["/bin/zsh", "-l", "-c", "which claude"],
                             capture_output=True, text=True, timeout=20)
        cand = out.stdout.strip().splitlines()
        if out.returncode == 0 and cand:
            return cand[-1].strip()
    except Exception:
        pass
    return None

def tg(msg):
    try:
        subprocess.run(["bash", str(ROOT / "bin" / "tg-send.sh"), msg], timeout=30)
    except Exception:
        pass

def log_looks_dead(text):
    # claude -p는 인증 만료(401)로 죽어도 종료코드 0 — 2026-07-29 11:00 슬롯이 경보 없이 증발한 원인.
    t = text.strip()
    for marker in ("Failed to authenticate", "authentication_error", "OAuth access token"):
        if marker in t:
            return "인증 오류 감지"
    if len(t) < 200:
        return "출력이 %d자뿐 (세션 즉사 의심)" % len(t)
    return None

def main():
    os.chdir(str(ROOT))
    (ROOT / "logs").mkdir(exist_ok=True)
    if LOCK.exists():
        age = time.time() - LOCK.stat().st_mtime
        if age < STALE:
            tg("⏳ 숏츠 데일리: 이전 세션이 아직 실행 중 — 오늘 기동 건너뜀")
            return
        LOCK.unlink()
    # claude는 node 기반 → launchd의 빈 PATH에서 죽는다(2026-07-29 실사고: env: node not found).
    # 로그인 셸(zsh -l)을 통째로 경유해 사용자 PATH(node·claude 포함)를 복원한다.
    chk = subprocess.run(["/bin/zsh", "-l", "-c", "which claude"], capture_output=True, text=True, timeout=30)
    if chk.returncode != 0 or not chk.stdout.strip():
        tg("⚠️ 숏츠 데일리: 로그인 셸에서도 claude CLI를 찾지 못해 기동 실패")
        sys.exit(1)
    LOCK.write_text(str(os.getpid()))
    start_ts = time.time()
    try:
        with open(LOG, "w") as lf:
            r = subprocess.run(
                ["/bin/zsh", "-l", "-c",
                 'claude -p "$(cat DAILY_PROMPT.md)" --model opus --permission-mode acceptEdits'],
                stdout=lf, stderr=subprocess.STDOUT, timeout=TIMEOUT, cwd=str(ROOT))
        if r.returncode != 0:
            tg("⚠️ 숏츠 데일리 세션 비정상 종료 (코드 %d) — %s 확인" % (r.returncode, LOG.name))
        else:
            try:
                reason = log_looks_dead(LOG.read_text(errors="ignore"))
            except Exception:
                reason = None
            if reason:
                tg("⚠️ 숏츠 데일리: 종료코드는 0인데 %s — %s 확인" % (reason, LOG.name))
            else:
                check_artifacts(start_ts)
    except subprocess.TimeoutExpired:
        tg("⚠️ 숏츠 데일리 세션 타임아웃(100분) — %s 확인" % LOG.name)
    finally:
        LOCK.unlink(missing_ok=True)


def check_artifacts(start_ts):
    """세션의 자기 성공 보고를 산출물 실측으로 대조 (2026-07-29 감사: 자기채점 누수 지적).
    세션 시작 이후 갱신된 out/*.mp4가 없고, 로그에 게시 중단 사유도 없으면 경보."""
    try:
        logtext = LOG.read_text(errors="ignore")
        if any(k in logtext for k in ("게시 중단", "게시 보류", "기각")):
            return  # 의도된 미게시 — 세션이 사유를 보고했음
        new_mp4 = [p for p in (ROOT / "out").glob("*.mp4") if p.stat().st_mtime >= start_ts]
        if not new_mp4:
            tg("⚠️ 숏츠 데일리: 세션은 정상 종료했지만 새 영상 산출물이 없음 — %s 확인" % LOG.name)
        elif "발송 완료" not in logtext and "phase0" not in logtext:
            tg("⚠️ 숏츠 데일리: 영상은 있는데 발송 기록이 로그에 없음 — 게시 단계 누락 의심, %s 확인" % LOG.name)
    except Exception:
        pass


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # 러너 자체가 죽으면 경보자가 죽는 문제 방지 (2026-07-29 감사)
        tg("🔥 숏츠 데일리 러너 자체 오류: %s" % str(e)[:300])
        raise
