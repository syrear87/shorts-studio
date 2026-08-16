#!/usr/bin/env python3
# 제휴 공백 감시 (2026-08-16 신설 — 디렉터 "파트너스 유입이 아예 없는데?"
#   실사고: 8/14 12:18 이후 48시간 제휴 활동 0인데 아무도 몰랐다)
# affiliate_state.json의 마지막 갱신이 N시간을 넘으면 경보. pm2 studio-affiliate 루프가 호출한다.
import json, os, time, urllib.parse, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAP_HOURS = 24
FLAG = os.path.join(ROOT, "logs", "affiliate_gap_alerted.txt")


def check_and_alert(tg_send):
    try:
        st = json.load(open(os.path.join(ROOT, "logs", "affiliate_state.json"), encoding="utf-8"))
        ts = st.get("ts")
        if not ts:
            return
        import datetime
        last = datetime.datetime.fromisoformat(ts).timestamp()
        gap = (time.time() - last) / 3600
        if gap < GAP_HOURS:
            if os.path.exists(FLAG):
                os.remove(FLAG)   # 활동 재개 → 다음 공백 때 다시 울리게
            return
        # 하루 1회만
        today = time.strftime("%Y-%m-%d")
        if os.path.exists(FLAG) and open(FLAG).read().strip() == today:
            return
        open(FLAG, "w").write(today)
        tg_send("💤 제휴 공백 %d시간 — 마지막 활동 %s\n"
                "오늘 슬롯에서 제휴 후보를 뽑아 보내드리겠습니다. "
                "(광복절처럼 역사·인물 특별편이 연속되면 제휴 슬롯이 통째로 비니 주의)" % (int(gap), ts[:16]))
    except Exception as e:
        print("[affiliate_gap] 확인 실패:", str(e)[:120], flush=True)
