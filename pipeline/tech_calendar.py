#!/usr/bin/env python3
"""테크 예정 이벤트 캘린더 — 소재 선점용 (2026-08-27 신설).

디렉터: "소재 선점하는게 젤 중요함!"

문제: content/CALENDAR.md는 천문·절기·개봉일 중심이고 **9월 이후가 비어 있다.**
  반면 우리가 이미 쓴 글 안에는 예정 이벤트가 다 들어 있었다 —
  9/1 스위치2 인상, 9/3 젠하이저 출시, 9/9 애플 이벤트, 9/22 맥미니 출시.
  즉 정보는 갖고 있는데 **선점에 쓰지 못하고 있었다.**

무엇을 하나: 공개·초안 글에서 미래 날짜를 뽑아 D-day 순으로 캘린더 표를 만든다.
  세션이 매 슬롯 이걸 보면 'D-7 예고 → D-day 본편' 배치를 스스로 할 수 있다.

날짜 파싱은 blog_priority 단일 정본을 쓴다.
"""
import datetime
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
OUT = os.path.join(ROOT, "content", "TECH_CALENDAR.md")
HORIZON = 60          # 며칠 앞까지 볼 것인가


def collect(days=HORIZON):
    """{날짜: [(제목, 상태), ...]} — 블로그 글에서 미래 이벤트를 모은다."""
    from blog_priority import dates_in
    from upload_blogger import _service, resolve_blog_id
    svc = _service(); bid = resolve_blog_id()
    today = datetime.date.today()
    ev = {}
    for status in ("LIVE", "DRAFT"):
        tok = None
        while True:
            kw = {"blogId": bid, "status": status, "fetchBodies": True, "maxResults": 100}
            if tok:
                kw["pageToken"] = tok
            d = svc.posts().list(**kw).execute()
            for p in d.get("items", []):
                title = (p.get("title") or "").strip()
                txt = re.sub(r"<[^>]+>", " ", p.get("content") or "")
                for dt in set(dates_in(txt, today)):
                    if today <= dt <= today + datetime.timedelta(days=days):
                        ev.setdefault(dt, [])
                        if not any(t == title for t, _ in ev[dt]):
                            ev[dt].append((title, "공개" if status == "LIVE" else "초안"))
            tok = d.get("nextPageToken")
            if not tok:
                break
    return ev


def render(ev=None, days=HORIZON):
    ev = ev if ev is not None else collect(days)
    today = datetime.date.today()
    L = ["# 테크 예정 이벤트 — 소재 선점용",
         "",
         "> **왜 있는가 (2026-08-27 디렉터: \"소재 선점하는게 젤 중요함!\")**: 예정 이벤트는",
         "> 이미 공개돼 있다. 남보다 먼저 다루려면 터진 뒤 쫓아가는 게 아니라 **D-7에 예고하고**",
         "> **D-day에 본편**을 내야 한다. 이 표는 우리 블로그 글에서 자동 추출한 것이라,",
         "> 이미 우리가 아는 정보인데 선점에 못 쓰고 있던 것들이다.",
         ">",
         "> **세션 사용법**: 소재 선정 때 이 표를 먼저 보라. D-7~D-1 항목이 있으면 **예고형**을,",
         "> D-0이면 **본편**을 우선 배치한다. 날짜·수치는 QA-사전 규칙대로 재검증할 것.",
         "> 갱신: `.venv/bin/python3 pipeline/tech_calendar.py` (러너가 매일 자동 실행)",
         "",
         "| D | 날짜 | 이벤트 | 우리 상태 |",
         "|---|---|---|---|"]
    for dt in sorted(ev):
        left = (dt - today).days
        mark = "**D-0**" if left == 0 else ("**D%+d**" % left if left <= 7 else "D%+d" % left)
        for i, (title, st) in enumerate(ev[dt][:3]):
            L.append("| %s | %s | %s | %s |" % (mark if i == 0 else "", 
                     dt.strftime("%m/%d") if i == 0 else "", title[:52], st))
    if not ev:
        L.append("| — | — | (추출된 예정 이벤트 없음) | — |")
    L += ["", "_자동 생성: %s_" % datetime.datetime.now().strftime("%Y-%m-%d %H:%M")]
    return "\n".join(L) + "\n"


def main():
    txt = render()
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(txt)
    n = txt.count("\n| ") - 1
    print("테크 캘린더 갱신: %s (%d행)" % (os.path.relpath(OUT, ROOT), max(n, 0)))


if __name__ == "__main__":
    main()
