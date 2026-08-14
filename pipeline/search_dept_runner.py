#!/usr/bin/env python3
# 서치부 스케줄러 — 매일 05시(막내 2호 캘린더 스카우트), 10/14/20시(선임)에 claude -p 기동 (2026-08-13)
# 실행: pm2 start (studio-searchdept). stdout은 pm2 로그로 감.
# 2026-08-14 감사 보강: ①실행 이력을 파일로 영속(재시작 시 같은 슬롯 중복 기동 방지)
#   ②기동 창을 정시~59분으로 확장(재시작·슬립이 앞 30분을 덮어도 벌충)
#   ③지나간 슬롯 미기동 감지 → 텔레그램 경보 ④실패 경보(같은 날 오전 추가분 유지)
import json
import os
import subprocess
import time
import urllib.parse
import urllib.request
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_F = os.path.join(ROOT, "logs", "search_dept_state.json")
HOURS = (10, 14, 20)
SCOUT_HOUR = 5   # 막내 2호 (캘린더 스카우트)


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


def load_state():
    try:
        d = json.load(open(STATE_F, encoding="utf-8"))
        return set(d.get("ran", [])), set(d.get("alerted", []))
    except Exception:
        return set(), set()


def save_state(ran, alerted):
    tmp = STATE_F + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"ran": sorted(ran), "alerted": sorted(alerted)}, f, ensure_ascii=False)
    os.replace(tmp, STATE_F)   # 원자적 교체 — 기록 중 크래시로 JSON 파손 방지


def launch(prompt_file, log_path, timeout_min, label):
    env = dict(os.environ)
    env.pop("CLAUDECODE", None)
    env.pop("CLAUDE_CODE_ENTRYPOINT", None)
    try:
        with open(log_path, "w") as lf:
            subprocess.run(["/bin/zsh", "-l", "-c",
                            'claude -p "$(cat %s)" --model opus --permission-mode acceptEdits' % prompt_file],
                           stdout=lf, stderr=subprocess.STDOUT, timeout=timeout_min * 60, cwd=ROOT, env=env)
    except Exception as e:
        print("[search_dept] %s 오류: %s" % (label, str(e)[:150]), flush=True)
        tg_alert("⚠️ 서치부 %s 실패: %s" % (label, str(e)[:120]))


ran, alerted = load_state()
print("[search_dept] 스케줄러 시작 %s (이력 %d건 로드)" % (datetime.now().isoformat(), len(ran)), flush=True)
while True:
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    key = "%s-%02d" % (today, now.hour)
    if now.hour == SCOUT_HOUR and key not in ran:
        ran.add(key)
        save_state(ran, alerted)
        print("[search_dept] 막내 2호 출근", now.isoformat(), flush=True)
        launch("CALENDAR_SCOUT_PROMPT.md",
               os.path.join(ROOT, "logs", "calendar_scout-%s.log" % now.strftime("%Y%m%d")),
               45, "막내 2호(캘린더 스카우트)")
    elif now.hour in HOURS and key not in ran:
        ran.add(key)
        save_state(ran, alerted)
        print("[search_dept] 선임 출근", now.isoformat(), flush=True)
        launch("SEARCH_DEPT_PROMPT.md",
               os.path.join(ROOT, "logs", "search_dept-%s.log" % now.strftime("%Y%m%d-%H")),
               35, "선임(%d시)" % now.hour)
    # 지나간 슬롯 미기동 감지 (슬립·중단이 슬롯 시간을 통째로 덮은 경우 — 벌충 대신 경보만, 늦은 픽은 가치가 낮다)
    for h in (SCOUT_HOUR,) + HOURS:
        past = "%s-%02d" % (today, h)
        if h < now.hour and past not in ran and past not in alerted:
            alerted.add(past)
            save_state(ran, alerted)
            tg_alert("⚠️ 서치부 %d시 슬롯 미기동 감지 (%s) — Mac 절전/pm2 중단 여부 확인" % (h, today))
    # 이력 정리: 최근 이틀치만 유지
    if len(ran) > 16:
        keep = set(sorted({k[:10] for k in ran})[-2:])
        ran = {k for k in ran if k[:10] in keep}
        alerted = {k for k in alerted if k[:10] in keep}
        save_state(ran, alerted)
    time.sleep(300)
