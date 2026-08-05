#!/usr/bin/env python3
# 야간 워치독 — launchd가 매일 22:30에 실행 (2026-07-29 감사: 미기동 슬롯 무증상 사각 해소).
# 오늘 기대 슬롯 수(평일 4 / 주말 5)와 logs/daily-YYYYMMDD-*.log 개수를 대조해 결과를 텔레그램으로 보고.
# 매일 반드시 1건을 발송한다 — 이 메시지 자체가 "스케줄러+경보 채널 생존" 하트비트다 (안 오면 그게 신호).
import glob, os, subprocess, sys
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 2026-08-05 디렉터 편성(확정): 매일 동일 — 카드 09/13/17 + 영상 11/15/19 (주말 구분 폐지)
WEEKDAY_SLOTS = ["09", "11", "13", "15", "17", "19"]
WEEKEND_SLOTS = ["09", "11", "13", "15", "17", "19"]


def main():
    now = datetime.now()
    # 2026-08-02 리뷰(OPS-9): 수면 벌충 실행이 자정을 넘기면 '오늘 0/N 누락' 허위 경보 + 전날 하트비트 영구 누락
    # → 정오 이전 실행이면 전날을 평가 대상으로 삼고, 메시지에 평가 대상 날짜를 명시한다.
    target = now - timedelta(days=1) if now.hour < 12 else now
    slots = WEEKEND_SLOTS if target.weekday() >= 5 else WEEKDAY_SLOTS
    day = target.strftime("%Y%m%d")
    label = target.strftime("%m/%d")
    logs = sorted(glob.glob(os.path.join(ROOT, "logs", "daily-%s-*.log" % day)))
    # 2026-08-02 리뷰(OPS-10): 앞 2자리 정확 일치는 벌충/지연 기동(예: 07시 슬롯이 0800에 기동)을
    # '누락+예정 외' 이중 오보로 만든다 → 로그 시각을 ±90분 이내 가장 가까운 슬롯에 매핑하고,
    # 정각에서 10분 넘게 어긋난 매핑은 '(지연 기동)'으로 표기한다.
    hit = {}      # 슬롯(hh) → 정각 대비 오차(분, 절댓값 최소인 로그 기준)
    extra = []    # 어느 슬롯에도 ±90분 안에 못 붙는 실행
    for p in logs:
        hhmm = os.path.basename(p).split("-")[2].split(".")[0]   # daily-YYYYMMDD-HHMM.log
        t = int(hhmm[:2]) * 60 + int(hhmm[2:4])
        near = min(slots, key=lambda h: abs(t - int(h) * 60))
        diff = t - int(near) * 60
        if abs(diff) <= 90:
            if near not in hit or abs(diff) < abs(hit[near]):
                hit[near] = diff
        else:
            extra.append("%s:%s" % (hhmm[:2], hhmm[2:4]))
    missed = [h + "시" for h in slots if h not in hit]
    delayed = [h + "시" for h in slots if h in hit and abs(hit[h]) > 10]

    if missed:
        msg = "🕘 워치독(%s 평가): %d/%d 슬롯 실행 — 누락: %s" % (label, len(slots) - len(missed), len(slots), ", ".join(missed))
        if delayed:
            msg += " / 지연 기동: %s" % ", ".join(delayed)
        if extra:
            msg += " (예정 외 실행: %s)" % ", ".join(extra)
        msg += "\nMac 절전/스케줄 미로드 여부를 확인하세요."
    else:
        msg = "🕘 워치독(%s 평가): %d/%d 슬롯 모두 기동 ✅" % (label, len(slots), len(slots))
        if delayed:
            msg += " (지연 기동: %s)" % ", ".join(delayed)
        if extra:
            msg += " (예정 외 실행: %s)" % ", ".join(extra)
    removed = cleanup_out(now)
    if removed:
        msg += "\n🧹 보관 만료 정리: %s" % removed
    r = subprocess.run(["bash", os.path.join(ROOT, "bin", "tg-send.sh"), msg], timeout=30)
    if r.returncode != 0:
        # 경보 채널 자체가 죽음 — 로컬 파일에라도 남긴다
        with open(os.path.join(ROOT, "logs", "watchdog-fail.log"), "a") as f:
            f.write("%s 텔레그램 발송 실패(rc=%d): %s\n" % (now.isoformat(), r.returncode, msg))
        sys.exit(1)


def cleanup_out(now):
    """보관 정책 (2026-08-02 디렉터 승인): 게시 원본 mp4는 14일, 배경 후보 미리보기는 7일 뒤 삭제.
    유튜브에 이미 올라간 원본의 로컬 사본이므로 비가역 아님 — 채널이 원본 보관소다."""
    import time
    removed = []
    ts = time.time()
    for pattern, days in (("out/*.mp4", 14), ("out/bg_candidates/*", 7)):
        for p in glob.glob(os.path.join(ROOT, pattern)):
            try:
                if ts - os.path.getmtime(p) > days * 86400:
                    os.remove(p)
                    removed.append(os.path.basename(p))
            except OSError:
                pass
    if not removed:
        return ""
    return "%d개 삭제 (%s%s)" % (len(removed), ", ".join(removed[:3]),
                               " 외" if len(removed) > 3 else "")


if __name__ == "__main__":
    main()
