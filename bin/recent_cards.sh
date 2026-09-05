#!/bin/bash
# 최근 N일 카드의 '파일명 + topic'만 출력한다 (2026-08-27).
#
# ① 토큰: 카드 JSON을 통째로 열면 98,276자가 쌓인다. 쿨다운 판정에 필요한
#    제품명·훅 각도·태그는 전부 topic 한 줄에 있어 3,462자로 같은 판정이 된다.
# ③ **기본 14일 (2026-08-28 실사고)**: 7일이면 8일 전 소재가 범위 밖이라 그대로 재탕된다.
#    「카메라 에어팟 데모 영상 유출」이 8/20·8/28 두 번 나갔다 — 같은 사건 같은 각도였고
#    쿨다운을 **하루 차이로** 통과했다. 제품별 재등장 간격 실측(2026-08-28): 갤럭시 7회 중 6회,
#    아이폰 7회 중 6회가 10일 이내였다. 7일 기준은 사실상 작동하지 않았다.
# ② **개수가 아니라 날짜로 자른다 (실사고)**: 기존 규칙은 `head -42`(6장×7일)였는데
#    실제로는 8/21 이후에만 58장이 나와 42개로 자르면 8/22까지밖에 안 닿았다.
#    그 결과 8/21 픽셀11이 검사 범위 밖(56번째)이 되어 **8/27에 같은 소재를 또 냈다**
#    — 8/21에 쿨다운 규칙이 생긴 바로 그 사고(픽셀11 이틀 연속)가 6일 만에 재발했다.
#    카드 생산량은 날마다 다르므로 개수 기준은 언제든 다시 뚫린다.
cd "$(dirname "$0")/.." || exit 1
DAYS="${1:-14}"   # 2026-08-28: 7일은 짧다 — 8/20 카메라 에어팟이 범위 밖이라 8/28에 재탕됐다
.venv/bin/python3 - "$DAYS" <<'PY'
import datetime, glob, json, os, sys
days = int(sys.argv[1]) if len(sys.argv) > 1 else 7
cut = datetime.date.today() - datetime.timedelta(days=days)
fs = [f for f in glob.glob("content/cards-*.json")
      if datetime.date.fromtimestamp(os.path.getmtime(f)) >= cut]
fs.sort(key=os.path.getmtime, reverse=True)
print("# 최근 %d일 카드 %d장 (날짜 기준 — 개수로 자르지 않는다)" % (days, len(fs)))
for f in fs:
    try:
        t = json.load(open(f, encoding="utf-8")).get("topic") or ""
    except Exception:
        t = "(읽기 실패)"
    print("%s | %s" % (os.path.basename(f)[6:-5], str(t)[:70]))
PY
