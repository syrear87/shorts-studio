#!/bin/bash
# 백로그에서 지금 활성화 조건이 맞는 소재를 골라 보여준다 (2026-08-28 신설).
#
# 왜: content/BACKLOG.md에 144줄이 쌓였는데 코드 참조가 0곳이었다. 프롬프트에도
#   "당일 신선 소재가 전멸일 때만 꺼내라"고 돼 있어 사실상 봉인 상태였다.
#   그 사이 소재는 애플·삼성으로 쏠렸다(최근 3일 대기업 64%).
#   백로그 항목은 대부분 **활성화 조건이 붙은 대기 소재**다("로또 캐리오버 뉴스 시",
#   "비만약 관련 뉴스 시"). 조건이 맞았는지는 훑어야 알 수 있는데 훑는 절차가 없었다.
#
# 하는 일: 항목과 활성화 조건을 한 줄씩 뽑아준다. 조건 충족 여부는 세션이 판단한다.
cd "$(dirname "$0")/.." || exit 1
.venv/bin/python3 - <<'PY'
import os, re
p = os.path.join('content', 'BACKLOG.md')
if not os.path.exists(p):
    print('BACKLOG.md 없음'); raise SystemExit
items = []
for line in open(p, encoding='utf-8'):
    s = line.strip()
    if not s.startswith('- **'):
        continue
    title = re.sub(r'^-\s*\*\*(.+?)\*\*.*', r'\1', s)
    cond = ''
    m = re.search(r'활성화[:：]\s*([^.。]+)', s)
    if m:
        cond = m.group(1).strip()
    note = ''
    m2 = re.search(r'조건[:：]\s*([^.。]+)', s)
    if m2:
        note = m2.group(1).strip()
    items.append((title[:46], cond[:52], note[:44]))
if not items:
    print('활성화 조건이 적힌 항목 없음 — BACKLOG 형식을 확인하라')
    raise SystemExit
print('백로그 대기 소재 %d건 — 오늘 조건이 맞는 게 있는지 보라' % len(items))
print()
for t, c, n in items:
    print('· %s' % t)
    if c:
        print('    활성화: %s' % c)
    if n:
        print('    조건  : %s' % n)
PY
