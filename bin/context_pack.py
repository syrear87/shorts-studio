#!/usr/bin/env python3
"""슬롯 세션이 착수 전에 읽을 것을 한 장으로 줄인다.

왜 있는가 (2026-09-06, 어벤져스 실행안 항목 12):
  DAILY_PROMPT Ⅳ절이 매 슬롯 6개 파일 통독을 지시했다 — 실측 **254,667자**다
  (CALENDAR 103,019 · topics_used 56,733 · DECISIONS 43,574 · PERFORMANCE 34,920 ·
  PROTOCOL 9,735 · REJECTED 6,686). 프롬프트 자체가 9만 자인데 그 세 배를 더 읽는다.
  그런데 세션이 실제로 쓰는 건 **최근 소재(중복 회피) · 금지 목록 · 임박한 이벤트 ·
  최근 성과** 넷뿐이다. 나머지는 과거 기록이라 그때그때 필요한 것만 열면 된다.

원칙:
  **금지 목록은 절대 자르지 않는다.** 다른 절은 최근분만 담고 잘렸음을 명시한다 —
  "다 담았다"고 착각하게 만드는 요약이 통독보다 위험하다. 자른 것은 자랐다고 쓴다.

러너가 슬롯 시작 직전에 실행해 logs/context_pack.md에 쓴다. 세션은 그 한 파일만 읽는다.
"""
import datetime
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "logs", "context_pack.md")
BUDGET = 4000


def _read(rel):
    p = os.path.join(ROOT, rel)
    try:
        with open(p, encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


def rejected():
    """영구 금지 목록 — **전건**. 여기가 잘리면 기각 소재가 다시 나간다."""
    rows = []
    for line in _read("content/REJECTED.md").splitlines():
        if not line.startswith("|") or line.startswith("|---") or "기각일" in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) >= 3:
            name = re.sub(r"\*\*", "", cells[0])
            rows.append("- %s — %s" % (name, cells[2][:34]))
    return rows


def recent_topics(days=21):
    """최근 사용 소재 — 중복 발행을 막는 유일한 근거다."""
    cut = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    rows = []
    for line in _read("content/topics_used.md").splitlines():
        if not line.startswith("|") or line.startswith("|---") or "날짜" in line[:12]:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 3:
            continue
        d = cells[0].replace(".", "-")[:10]
        if not re.match(r"\d{4}-\d{2}-\d{2}", d) or d < cut:
            continue
        rows.append("- %s %s %s" % (d[5:], cells[1][:6], re.sub(r"\*\*", "", cells[2])[:44]))
    return rows[::-1]


def _dates_in(line, today):
    """캘린더의 날짜 표기를 전부 뽑는다.

    이 파일은 `9/7`·`9/15~16`·`9/19~10/4` 꼴로 적혀 있다(ISO가 아니다).
    ISO만 찾다가 D-10 절이 통째로 비었던 적이 있어(2026-09-06) 두 형식을 다 본다.
    """
    out = []
    for m in re.finditer(r"(\d{4})-(\d{2})-(\d{2})", line):
        try:
            out.append(datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
        except ValueError:
            pass
    for m in re.finditer(r"(?<![\d/])(\d{1,2})/(\d{1,2})(?![\d/])", line):
        mo, dy = int(m.group(1)), int(m.group(2))
        if not (1 <= mo <= 12 and 1 <= dy <= 31):
            continue
        for yr in (today.year, today.year + 1):
            try:
                d = datetime.date(yr, mo, dy)
            except ValueError:
                continue
            if d >= today - datetime.timedelta(days=2):
                out.append(d)
                break
    return out


def calendar_soon(days=10):
    """D-10 이내 이벤트만 — 미래는 캘린더에 공개돼 있다."""
    today = datetime.date.today()
    end = today + datetime.timedelta(days=days)
    rows = []
    for line in _read("content/CALENDAR.md").splitlines():
        if not line.strip().startswith(("|", "-", "*")) or line.startswith("|---"):
            continue
        ds = [d for d in _dates_in(line, today) if today <= d <= end]
        if not ds:
            continue
        txt = re.sub(r"[|*]+", " ", line).strip()
        txt = re.sub(r"\s{2,}", " ", txt)
        rows.append(((min(ds) - today).days, "- D-%d %s" % ((min(ds) - today).days, txt[:74])))
    rows.sort(key=lambda x: x[0])          # 문자열 정렬이면 D-10이 D-2보다 앞선다
    return [r for _, r in rows[:14]]


def perf():
    """연령 고정 장부 요약 — '오늘 조회수'로 판단하지 않게."""
    import subprocess
    try:
        r = subprocess.run([os.path.join(ROOT, ".venv", "bin", "python3"),
                            os.path.join(ROOT, "pipeline", "ledger.py"), "--report", "72"],
                           capture_output=True, text=True, timeout=60, cwd=ROOT)
        return [l for l in r.stdout.splitlines() if l.strip()][:9]
    except Exception:
        return []


def decisions(n=6):
    heads = [l.strip("# ").strip() for l in _read("DECISIONS.md").splitlines()
             if l.startswith("## ")]
    return ["- " + h[:76] for h in heads[-n:]]


def last_report():
    fs = sorted(glob.glob(os.path.join(ROOT, "reports", "*.md")))
    if not fs:
        return []
    name = os.path.basename(fs[-1])
    head = [l.strip() for l in _read("reports/" + name).splitlines() if l.strip()][:4]
    return ["- 직전 리포트 `reports/%s`" % name] + ["  " + h[:80] for h in head[1:]]


def build():
    today = datetime.date.today().isoformat()
    parts = []
    parts.append("# 컨텍스트 팩 — %s 생성 (러너 자동)\n" % datetime.datetime.now()
                 .strftime("%Y-%m-%d %H:%M"))
    parts.append("> **이 파일이 착수 전 통독을 대신한다.** 종전 Ⅳ절은 6개 파일 254,667자를\n"
                 "> 읽으라고 했는데, 실제로 쓰는 건 아래 넷뿐이다. **원본이 필요하면 그때 그\n"
                 "> 파일만 열어라** — 통째로 읽지 마라.\n")

    rej = rejected()
    parts.append("## 🚫 영구 금지 — 전건 (재도전 절대 금지)\n")
    parts.append("\n".join(rej) if rej else "- (없음)")
    parts.append("\n> 각도를 바꿔도, 같은 사건의 다른 측면이어도 금지다. "
                 "사유 전문은 `content/REJECTED.md`.\n")

    top = recent_topics()
    parts.append("## 📌 최근 21일 사용 소재 — 중복 금지 대조용\n")
    parts.append("\n".join(top) if top else "- (없음)")
    parts.append("")

    cal = calendar_soon()
    if cal:
        parts.append("## 📅 D-10 이내 이벤트 (예고형 후보)\n")
        parts.append("\n".join(cal))
        parts.append("\n> 전체는 `content/CALENDAR.md`.\n")

    p = perf()
    if p:
        parts.append("## 📊 72시간 시점 성과 (연령 고정 장부)\n")
        parts.append("\n".join("  " + x for x in p))
        parts.append("")

    d = decisions()
    if d:
        parts.append("## 🧭 최근 결정 (제목만 — 본문은 `DECISIONS.md`)\n")
        parts.append("\n".join(d))
        parts.append("")

    r = last_report()
    if r:
        parts.append("## 📄 직전 리포트\n")
        parts.append("\n".join(r))
        parts.append("")

    out = "\n".join(parts)

    # 예산 초과 시 **최근 소재**부터 줄인다. 금지 목록은 건드리지 않는다.
    if len(out) > BUDGET and top:
        keep = len(top)
        while len(out) > BUDGET and keep > 12:
            keep -= 4
            trimmed = top[:keep] + ["- …이하 %d건 생략 — 전체는 `content/topics_used.md`"
                                    % (len(top) - keep)]
            out = out.replace("\n".join(top), "\n".join(trimmed))
            top = trimmed
    return out, len(rej)


def main():
    out, n_rej = build()
    if n_rej == 0:
        print("[context_pack] ⚠ 금지 목록이 비었다 — REJECTED.md 형식이 바뀌었나?", flush=True)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(out)
    print("[context_pack] %s — %d자 (금지 %d건)" % (OUT, len(out), n_rej), flush=True)
    if "--show" in sys.argv:
        print()
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
