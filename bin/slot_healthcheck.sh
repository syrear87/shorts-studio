#!/usr/bin/env bash
# 슬롯 로그 한 건을 새 체제 기준으로 점검한다 (2026-09-06 신설).
#
# 왜 있는가: 9/5 밤에 컨텍스트 팩·3렌즈·drain·가격 게이트를 한꺼번에 넣었다.
# 다음 슬롯이 이 체제로 처음 도는데, 로그를 눈으로 훑으면 무엇이 빠졌는지 놓친다.
# "돌긴 돌았다"와 "새 체제대로 돌았다"는 다른 말이다.
#
# 사용: bash bin/slot_healthcheck.sh                 # 가장 최근 슬롯
#       bash bin/slot_healthcheck.sh logs/daily-20260906-1020.log
set -u
cd "$(dirname "$0")/.." || exit 1

LOG="${1:-$(ls -t logs/daily-*.log 2>/dev/null | head -1)}"
[ -z "$LOG" ] || [ ! -f "$LOG" ] && { echo "로그가 없다: ${LOG:-(없음)}"; exit 2; }

echo "=== $LOG ==="
echo "  크기 $(wc -c < "$LOG" | tr -d ' ')B · 수정 $(date -r "$LOG" '+%m-%d %H:%M')"
echo

fail=0
chk() {  # chk <설명> <있어야 하면 1> <패턴>
  local desc="$1" want="$2" pat="$3" n
  # -F 고정문자열: 패턴에 [runner]·[context_pack]처럼 대괄호가 있어 정규식으로 읽으면
  # 문자클래스가 된다(2026-09-06 자체 회귀에서 전부 오판정했다).
  # grep -c는 매치 0일 때도 숫자를 찍고 rc=1을 내므로 `|| echo 0`을 붙이면 "0\n0"이 된다.
  n=$(grep -cF -- "$pat" "$LOG" 2>/dev/null) || n=0
  if [ "$want" = 1 ] && [ "$n" -gt 0 ]; then printf "  ✓ %s\n" "$desc"
  elif [ "$want" = 0 ] && [ "$n" -eq 0 ]; then printf "  ✓ %s\n" "$desc"
  else printf "  ✗ %s  (매치 %s건)\n" "$desc" "$n"; fail=$((fail+1)); fi
}

echo "[기본]"
chk "세션이 마감 마커를 남겼다 (SLOT-DONE)"        1 "SLOT-DONE"
chk "프롬프트가 비지 않았다"                        1 "[runner] prompt "
chk "즉사·한도 경보가 없다"                         0 "usage limit"

echo
echo "[9/5 밤에 넣은 새 체제]"
chk "컨텍스트 팩이 생성됐다"                        1 "[context_pack]"
chk "프롬프트가 RULES + 모드 두 벌로 조립됐다"      1 "RULES.md + "

echo
echo "[산출물]"
if grep -qF "SLOT-NOOP" "$LOG"; then
  echo "  · 결번 슬롯이다 — 사유:"
  grep -oE "SLOT-NOOP[^|]*" "$LOG" | head -2 | sed 's/^/      /'
else
  chk "유튜브 링크가 남았다"                        1 "youtube.com/shorts"
fi

echo
echo "[프롬프트 길이 — 팩 도입 효과]"
grep -oE "\[runner\] prompt [0-9]+자" "$LOG" | tail -1 | sed 's/^/  /'
grep -F "[context_pack]" "$LOG" | tail -1 | sed 's/^/  /'

echo
if [ "$fail" -eq 0 ]; then echo "판정: 이상 없음"; else echo "판정: 확인 필요 $fail건 ↑"; fi
exit "$fail"
