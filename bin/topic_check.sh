#!/bin/bash
# 소재가 최근 N일 안에 이미 나갔는지 검사한다 (2026-08-28 신설).
# 사용: bash bin/topic_check.sh "손톱 쥐 둔갑 넷플릭스 들쥐"
#
# 사고: 넷플릭스 '들쥐' 원작 설화를 8/23(D-5)·8/27(D-1)·8/28(당일) **세 번** 발행했다.
#   topics_used.md에 세 번 다 기록됐는데도 막히지 않았다 — 기록은 남기지만 **읽고 판정하는
#   장치가 없었기 때문**이다. 매번 "예고니까 괜찮다"고 스스로 판단했다.
#   같은 사건은 예고 1편·당일 1편이 상한이고, 그 판정을 사람 재량에 맡기면 새는 게 확인됐다.
cd "$(dirname "$0")/.." || exit 1
LINE="all"
case "$1" in
  --video) LINE="video"; shift ;;
  --card)  LINE="card";  shift ;;
esac
Q="$*"
[ -z "$Q" ] && { echo "사용: bash bin/topic_check.sh [--video|--card] \"소재 핵심어들\""; exit 1; }
.venv/bin/python3 - "$Q" "$LINE" <<'PY'
import datetime, glob, json, os, re, sys
q = sys.argv[1]
# 2026-08-29 플랫폼 분리: 영상은 인스타·유튜브, 카드는 스레드 전용이 됐다.
# 두 라인의 시청자가 갈렸으므로 **교차 중복은 더 이상 문제가 아니다**
# (디렉터: "카드 안 나가니 카드랑 중복 걱정할 건 없으니").
# 같은 라인 안의 재탕만 막는다 — 들쥐 3회·픽셀 3회는 전부 같은 라인 사고였다.
LINE = sys.argv[2] if len(sys.argv) > 2 else "all"
DAYS = 21
cut = datetime.date.today() - datetime.timedelta(days=DAYS)
# 어느 테크 소재에나 나오는 말 — 이것만 겹치는 것은 같은 소재가 아니다
# (2026-08-28: '가격'·'인상'만 겹쳐 빵값 편·S26 FE 편까지 걸렸다)
STOP = {'그리고','하지만','에서','으로','까지','부터','합니다','입니다','있다','없다','이번','오늘',
        '가격','인상','출시','공개','발표','제품','신제품','한국','국내','원','만원','판매',
        '기능','성능','비교','확인','구매','사용','지원','차이','이유','방법','정보',
        # 2026-08-28 감사: '브랜드+범용어' 2개 조합이 무관한 소재를 ⛔ 처리했다.
        # 절차가 "⛔면 폐기"라 오탐 비용이 크다 — 범용어를 더 걷어낸다. 브랜드·제품명은
        # 남긴다(닌텐도+스위치2 같은 진짜 재탕을 잡는 축이다).
        '스마트폰','테크','기기','최신','최근','대비','기준','공식','루머','유출',
        '역대','최초','최고','최대','시리즈','모델','버전','업데이트','올해','내년',
        '이제','지금','다시','계속','때문','경우','정도','수준','전망','예정'}
keys = [w for w in re.split(r'[^0-9A-Za-z가-힣]+', q) if len(w) > 1 and w not in STOP]
hits = []

# ① 영상 이력 (topics_used.md)
path = os.path.join('content', 'topics_used.md')
if LINE in ('all', 'video') and os.path.exists(path):
    for line in open(path, encoding='utf-8'):
        m = re.match(r'\|\s*(\d{4}-\d{2}-\d{2})\s*\|\s*([a-z0-9]+)\s*\|(.*)', line.strip())
        if not m:
            continue
        try:
            d = datetime.date.fromisoformat(m.group(1))
        except ValueError:
            continue
        if d < cut:
            continue
        both = [k for k in keys if k in m.group(3)]
        if len(both) >= 2:
            hits.append((d, '영상 ' + m.group(2), both, m.group(3)[:90]))

# ② **카드 이력 — topics_used.md에는 영상만 기록된다** (2026-08-28 실사고)
#    스위치2 가격 인상이 8/23 카드로 나갔는데 topics_used에 없어서, 8/28 영상이 같은
#    소재를 다시 냈다. 두 라인이 서로를 못 보는 구조였다. 카드 json을 직접 읽어 합친다.
for f in (glob.glob(os.path.join('content', 'cards-*.json')) if LINE in ('all', 'card') else []):
    b = os.path.basename(f)
    try:
        d = datetime.date.fromisoformat('-'.join(b.split('-')[1:4]))
    except Exception:
        continue
    if d < cut:
        continue
    try:
        j = json.load(open(f, encoding='utf-8'))
    except Exception:
        continue
    # 철회된 카드는 이력이 아니다 (2026-09-08): 게시가 취소됐으면 그 소재는 다시 쓸 수 있어야
    # 한다. 카드 이력은 topics_used.md가 아니라 **파일 존재**로 판정하므로, 상태 태그를
    # 고쳐도 안 풀렸다. status 필드를 여기서 본다.
    if str(j.get("status", "")).lower() in ("withdrawn", "철회", "보류", "held"):
        continue
    body = str(j.get('topic') or '') + ' ' + str(j.get('caption') or '')
    both = [k for k in keys if k in body]
    if len(both) >= 2:
        hits.append((d, '카드', both, body.replace(chr(10), ' ')[:90]))
hits.sort()
if hits:
    print('⛔ 최근 %d일 안에 같은 소재가 %d번 나갔다 — 다시 쓰지 마라 [%s 라인]'
          % (DAYS, len(hits), LINE))
    for d, slot, w, b in hits:
        print('   %s %-5s (겹침: %s)' % (d, slot, ', '.join(w[:4])))
        print('      %s' % b.strip())
else:
    print('✅ 최근 %d일 안에 같은 소재 없음 [%s 라인] (대조: %s)'
          % (DAYS, LINE, ', '.join(keys[:6])))
PY
