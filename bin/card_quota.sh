#!/usr/bin/env bash
# 오늘 카드 유형별 배정 현황 (2026-09-06 신설).
# 왜: 배합 원칙(①따라하기1 ②타이밍경고2 ③한계붕괴1 ④소유욕1)·[구매가능]2·공유형2·
# AI놀이1·루머≤1·대기업≤2를 지키라면서 **오늘 몇 장이 어느 유형인지 볼 방법이 없었다.**
# 집계할 수 없는 쿼터는 지킬 수 없는 규칙이다.
set -u
cd "$(dirname "$0")/.." || exit 1
DAY=$(date +%Y-%m-%d)
mapfile -t FILES < <(ls content/cards-"$DAY"-*.json 2>/dev/null) 2>/dev/null || FILES=($(ls content/cards-"$DAY"-*.json 2>/dev/null))
N=${#FILES[@]}
ALL=$N
echo "=== $DAY 카드 (원본 $ALL건) ==="
if [ "$N" -eq 0 ]; then
  echo "  (아직 없음 — 오늘 첫 장)"
else
  for f in "${FILES[@]}"; do
    # 철회된 카드는 세지 않는다 (2026-09-08) — 삭제된 게시가 쿼터를 잡아먹으면
    # 남은 슬롯이 억지로 결번된다.
    st=$(sed -n 's/.*"status"[[:space:]]*:[[:space:]]*"\([a-z]*\)".*/\1/p' "$f" | head -1)
    if [ "$st" = "withdrawn" ]; then
      t=$(sed -n 's/.*"topic"[[:space:]]*:[[:space:]]*"\(.*\)",*$/\1/p' "$f" | head -1)
      printf "  ~ %s  ← 철회(집계 제외)\n" "${t:0:70}"
      N=$((N-1)); continue
    fi
    t=$(sed -n 's/.*"topic"[[:space:]]*:[[:space:]]*"\(.*\)",*$/\1/p' "$f" | head -1)
    printf "  · %s\n" "${t:0:100}"
  done
  echo
  echo "  === 유효 카드 $N/5장 ==="
  echo "  [유형 태그]"
  for tag in 소유욕형 구매가능 공유형 타이밍경고형 한계붕괴형 AI놀이 따라하기 신제품 루머 펀딩 레트로; do
    c=0
    for f in "${FILES[@]}"; do
      sed -n 's/.*"status"[[:space:]]*:[[:space:]]*"\([a-z]*\)".*/\1/p' "$f" | head -1 | grep -q withdrawn && continue
      grep -q "\[$tag\]\|\[$tag·\|·$tag\]\|·$tag·" "$f" && c=$((c+1))
    done
    [ "$c" -gt 0 ] && printf "    %-12s %d장\n" "$tag" "$c"
  done
fi
echo
printf "  남은 %d장 배정 시 확인:\n" $((5 - N))
echo "    · ④소유욕형 1장 들어갔나 (없으면 다음 장에서)"
echo "    · [구매가능] 2장 채웠나 — 없으면 억지로 채우지 말고 리포트에 사유"
echo "    · 대기업 신제품 2장 넘지 않았나 (bash bin/brand_mix.sh)"
echo "    · 국내 미출시 소재면 §1-c 3종(총액·국내 대안·출시 전망)"
