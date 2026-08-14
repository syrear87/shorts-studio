#!/usr/bin/env python3
# 서치부 스케줄러 — 매일 10/14/20시에 서치 직원 세션(claude -p) 기동 (2026-08-13)
# 실행: nohup .venv/bin/python3 pipeline/search_dept_runner.py >> logs/search_dept.log 2>&1 &
import os, subprocess, time, urllib.parse, urllib.request
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def tg_alert(msg):
    """실패는 조용히 묻히면 안 된다 (2026-08-14 점검: 2호 25분 타임아웃이 무보고로 묻힘)."""
    try:
        kv = {}
        for line in open(os.path.join(ROOT, "telegram.env"), encoding="utf-8"):
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                kv[k.strip()] = v.strip().strip('"')
        urllib.request.urlopen(
            "https://api.telegram.org/bot%s/sendMessage" % kv["STUDIO_TG_TOKEN"],
            urllib.parse.urlencode({"chat_id": kv["STUDIO_TG_CHAT_ID"], "text": msg}).encode(), timeout=30)
    except Exception:
        pass

HOURS = (10, 14, 20)
SCOUT_HOUR = 5   # 막내 2호 (캘린더 스카우트)
ran = set()

print("[search_dept] 스케줄러 시작", datetime.now().isoformat(), flush=True)
while True:
    now = datetime.now()
    key = (now.date(), now.hour)
    if now.hour == SCOUT_HOUR and key not in ran and now.minute < 30:
        ran.add(key)
        print("[search_dept] 막내 2호 출근", now.isoformat(), flush=True)
        env = dict(os.environ)
        env.pop("CLAUDECODE", None)
        env.pop("CLAUDE_CODE_ENTRYPOINT", None)
        try:
            with open(os.path.join(ROOT, "logs", "calendar_scout-%s.log" % now.strftime("%Y%m%d")), "w") as lf:
                subprocess.run(["/bin/zsh", "-l", "-c",
                                'claude -p "$(cat CALENDAR_SCOUT_PROMPT.md)" --model opus --permission-mode acceptEdits'],
                               stdout=lf, stderr=subprocess.STDOUT, timeout=45 * 60, cwd=ROOT, env=env)
        except Exception as e:
            print("[search_dept] 2호 오류:", str(e)[:150], flush=True)
            tg_alert("⚠️ 막내 2호(캘린더 스카우트) 실패: %s" % str(e)[:120])
    if now.hour in HOURS and key not in ran and now.minute < 30:
        ran.add(key)
        print("[search_dept] 직원 출근", now.isoformat(), flush=True)
        env = dict(os.environ)
        env.pop("CLAUDECODE", None)
        env.pop("CLAUDE_CODE_ENTRYPOINT", None)
        try:
            with open(os.path.join(ROOT, "logs", "search_dept-%s.log" % now.strftime("%Y%m%d-%H")), "w") as lf:
                subprocess.run(["/bin/zsh", "-l", "-c",
                                'claude -p "$(cat SEARCH_DEPT_PROMPT.md)" --model opus --permission-mode acceptEdits'],
                               stdout=lf, stderr=subprocess.STDOUT, timeout=35 * 60, cwd=ROOT, env=env)
        except Exception as e:
            print("[search_dept] 오류:", str(e)[:150], flush=True)
            tg_alert("⚠️ 서치부 선임(%d시) 실패: %s" % (now.hour, str(e)[:120]))
    # 자정에 ran 정리
    if len(ran) > 10:
        ran = {k for k in ran if k[0] == now.date()}
    time.sleep(300)
