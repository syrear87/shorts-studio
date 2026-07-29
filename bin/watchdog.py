#!/usr/bin/env python3
# 야간 워치독 — launchd가 매일 22:30에 실행 (2026-07-29 감사: 미기동 슬롯 무증상 사각 해소).
# 오늘 기대 슬롯 수(평일 4 / 주말 5)와 logs/daily-YYYYMMDD-*.log 개수를 대조해 결과를 텔레그램으로 보고.
# 매일 반드시 1건을 발송한다 — 이 메시지 자체가 "스케줄러+경보 채널 생존" 하트비트다 (안 오면 그게 신호).
import glob, os, subprocess, sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEEKDAY_SLOTS = ["08", "11", "17", "20"]
WEEKEND_SLOTS = ["09", "12", "15", "18", "21"]


def main():
    now = datetime.now()
    slots = WEEKEND_SLOTS if now.weekday() >= 5 else WEEKDAY_SLOTS
    day = now.strftime("%Y%m%d")
    logs = sorted(glob.glob(os.path.join(ROOT, "logs", "daily-%s-*.log" % day)))
    ran_hours = sorted({os.path.basename(p).split("-")[2][:2] for p in logs})
    missed = [h + "시" for h in slots if h not in ran_hours]
    extra = [h + "시" for h in ran_hours if h not in slots]

    if missed:
        msg = "🕘 워치독: 오늘 %d/%d 슬롯 실행 — 누락: %s" % (len(slots) - len(missed), len(slots), ", ".join(missed))
        if extra:
            msg += " (예정 외 실행: %s)" % ", ".join(extra)
        msg += "\nMac 절전/스케줄 미로드 여부를 확인하세요."
    else:
        msg = "🕘 워치독: 오늘 %d/%d 슬롯 모두 기동 ✅" % (len(slots), len(slots))
        if extra:
            msg += " (예정 외 실행: %s)" % ", ".join(extra)
    r = subprocess.run(["bash", os.path.join(ROOT, "bin", "tg-send.sh"), msg], timeout=30)
    if r.returncode != 0:
        # 경보 채널 자체가 죽음 — 로컬 파일에라도 남긴다
        with open(os.path.join(ROOT, "logs", "watchdog-fail.log"), "a") as f:
            f.write("%s 텔레그램 발송 실패(rc=%d): %s\n" % (now.isoformat(), r.returncode, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
