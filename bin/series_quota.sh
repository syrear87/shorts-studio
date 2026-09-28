#!/usr/bin/env bash
# 오늘 영상 계열 배분 현황 (2026-09-06 신설).
# 왜: 계열 쿼터가 "이 표가 정본"이라고 선언돼 있는데 **오늘 어느 계열이 남았는지 볼
# 방법이 없었다.** 9/6에 공유성 2편·애국정체성 0편으로 쿼터가 깨졌는데 세 슬롯 모두
# 리포트에 아무 표시가 없었다 — 집계할 수 없는 쿼터는 지킬 수 없다(card_quota.sh와 같은 이유).
set -u
cd "$(dirname "$0")/.." || exit 1
DAY=$(date +%Y%m%d)
echo "=== $(date +%Y-%m-%d) 영상 계열 배분 ==="
echo "  정본: 애국·정체성/국내사건 1 · 공유성(천문·절기·이벤트·시행일) 1 · 스포츠결과/재난기상(실시간)/시사사건 1"
echo "  ⛔ 생활정보·실용은 영상 계열이 아니다 (2026-09-28 — topic_gate.py가 렌더에서 기각)"
echo
n=0
for f in logs/daily-"$DAY"-{1020,1320,2100}.log; do
  [ -f "$f" ] || continue
  slot=$(basename "$f" .log | sed "s/daily-$DAY-//")
  # 대본 JSON의 series 필드가 정본이다 (2026-09-07). 로그 파싱은 형식이 슬롯마다 달라
  # 오집계했다 — 13:20 공유성 편이 앞 슬롯 요약 때문에 "애국·정체성"으로도 잡혔다.
  case "$slot" in 1020) sfx=am2;; 1320) sfx=noon;; 2100) sfx=night;; *) sfx="";; esac
  js="content/$(date +%Y-%m-%d)-$sfx.json"
  line=""
  if [ -n "$sfx" ] && [ -f "$js" ]; then
    line=$(sed -n 's/.*"series"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$js" | head -1)
  fi
  [ -z "$line" ] && line="(대본에 series 없음)"
  topic=$(grep -h "소재" "$f" | head -1 | sed 's/.*소재[^가-힣A-Za-z0-9]*//' | cut -c1-46)
  if grep -qE "SLOT-DONE" "$f"; then
    n=$((n+1)); printf "  %s  %-22s %s\n" "$slot" "${line:-(계열 미기재)}" "$topic"
  else
    printf "  %s  (결번/미완)\n" "$slot"
  fi
done
echo
echo "  게시 $n/3편"
echo "  ⚠️ 계열이 겹쳤으면 남은 슬롯에서 빈 계열을 채워라. 마지막 슬롯인데 못 채우면"
echo "     리포트에 「계열 쿼터: 미충족(사유)」를 적어라 — 조용히 넘기지 마라."
