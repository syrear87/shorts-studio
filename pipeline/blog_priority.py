#!/usr/bin/env python3
"""발행 순서 결정 — 시의성이 급한 글을 먼저 내보낸다 (2026-08-27 디렉터 지시).

디렉터: "출시일이 임박하거나 출시일인 경우 해당 글이 공개 우선순위가 높아야함"

왜 필요한가: 초안이 40편 넘게 쌓여 하루 5편씩 나가면 뒤쪽 글은 8~9일 뒤에 공개된다.
  '9월 9일 애플 이벤트'처럼 날짜가 박힌 글이 9월 10일에 나가면 아무 가치가 없다.
  반대로 규격 설명처럼 시점을 안 타는 글은 언제 나가도 같다.

판정: 본문에서 날짜를 뽑아 **오늘 기준 남은 일수**로 순위를 매긴다.
  D-0~2  : 최우선 (오늘내일 일)
  D-3~7  : 그다음
  D-8~30 : 그다음
  날짜 없음 : 일반
  이미 지남 : 후순위 (가치가 이미 깎였다)
"""
import datetime
import re

# 2026년 9월 22일 / 9월 9일 / 9월 1일부터 / 10월 출시 / 4분기
_RE_YMD = re.compile(r"(20\d{2})년\s*(\d{1,2})월\s*(\d{1,2})일")
_RE_MD = re.compile(r"(?<!\d)(\d{1,2})월\s*(\d{1,2})일")
_RE_M = re.compile(r"(?<!\d)(\d{1,2})월\s*(?:중|말|초|경)?\s*(?:출시|공개|발표|시작|판매|런칭|도입)")


def _mk(y, m, d, today):
    try:
        return datetime.date(y, m, d)
    except ValueError:
        return None


def dates_in(text, today=None):
    """본문에 등장하는 날짜들. 연도가 없으면 오늘 기준 가장 가까운 해로 읽는다."""
    today = today or datetime.date.today()
    out = []
    for y, m, d in _RE_YMD.findall(text or ""):
        dt = _mk(int(y), int(m), int(d), today)
        if dt:
            out.append(dt)
    for m, d in _RE_MD.findall(text or ""):
        m, d = int(m), int(d)
        if not (1 <= m <= 12 and 1 <= d <= 31):
            continue
        # 연도 없는 '9월 9일' — 올해로 읽되, 이미 5개월 넘게 지났으면 내년으로 본다
        dt = _mk(today.year, m, d, today)
        if dt and (today - dt).days > 150:
            dt = _mk(today.year + 1, m, d, today)
        if dt:
            out.append(dt)
    for m in _RE_M.findall(text or ""):
        m = int(m)
        if 1 <= m <= 12:
            dt = _mk(today.year, m, 1, today)
            if dt and (today - dt).days > 150:
                dt = _mk(today.year + 1, m, 1, today)
            if dt:
                out.append(dt)
    return out


def urgency(text, today=None):
    """(순위키, 남은일수). 순위키가 작을수록 먼저 발행한다."""
    today = today or datetime.date.today()
    ds = dates_in(text, today)
    future = sorted(d for d in ds if d >= today)
    if future:
        left = (future[0] - today).days
        if left <= 2:
            return (0, left)
        if left <= 7:
            return (1, left)
        if left <= 30:
            return (2, left)
        return (3, left)          # 한 달 넘게 남은 예정 — 급하지 않다
    if ds:
        # 날짜가 있는데 전부 지났다 — 시의성이 이미 깎인 글.
        # 부호 주의(2026-08-28 감사): 음수로 주면 오름차순 정렬에서 **가장 오래 지난 글**이
        # 먼저 나간다. 최근에 지난 글이 그나마 덜 낡았으므로 지난 일수 그대로(작을수록 먼저).
        return (5, (today - max(ds)).days)
    return (4, 0)                 # 시점을 안 타는 글


def order(items, key=lambda x: x):
    """[(순위, 남은일수, 항목), ...] 를 우선순위대로 정렬해 돌려준다."""
    scored = []
    for it in items:
        r, left = urgency(key(it))
        scored.append((r, left, it))
    scored.sort(key=lambda x: (x[0], x[1]))
    return scored
