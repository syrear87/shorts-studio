#!/bin/bash
# 오늘 카드의 브랜드 쏠림을 보여준다 (2026-08-28 신설).
# 소재 선정 전에 이걸 봐서 대기업 쿼터(하루 2장)가 남았는지 확인하라.
cd "$(dirname "$0")/.." || exit 1
.venv/bin/python3 - "${1:-0}" <<'PY'
import datetime, glob, json, os, re, sys, collections
back = int(sys.argv[1]) if len(sys.argv) > 1 else 0
day = datetime.date.today() - datetime.timedelta(days=back)
BIG = {r'애플|아이폰|맥북|맥 미니|에어팟|아이패드|맥세이프|iPhone|Apple|macOS|아이맥|비전프로': '애플',
       r'삼성|갤럭시|엑시노스': '삼성', r'구글|픽셀|Pixel': '구글', r'닌텐도|스위치': '닌텐도'}
rows, cnt = [], collections.Counter()
for f in sorted(glob.glob('content/cards-*.json')):
    b = os.path.basename(f)
    try:
        d = datetime.date.fromisoformat('-'.join(b.split('-')[1:4]))
    except Exception:
        continue
    if d != day:
        continue
    try:
        t = str(json.load(open(f, encoding='utf-8')).get('topic') or '')
    except Exception:
        t = ''
    hit = next((n for p, n in BIG.items() if re.search(p, t)), None)
    cnt[hit or '기타'] += 1
    rows.append((hit or '기타', b[6:-5], t[:52]))
big = sum(v for k, v in cnt.items() if k != '기타')
print('%s 카드 %d장 · 대기업 %d/2장 %s' % (day, len(rows), big,
      '⛔ 쿼터 초과 — 다른 제조사에서 찾아라' if big >= 2 else '✅ 여유 있음'))
for k, n, t in rows:
    print('  [%-4s] %-28s %s' % (k, n, t))
PY
