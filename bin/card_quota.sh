#!/usr/bin/env bash
# 오늘 카드 유형별 배정 현황 (2026-09-06 신설).
# 왜: 배합 원칙(①따라하기1 ②타이밍경고2 ③한계붕괴1 ④소유욕1)·[구매가능]2·공유형2·
# AI놀이1·루머≤1·대기업≤2를 지키라고 하면서 **오늘 몇 장이 어느 유형인지 볼 방법이 없었다.**
# 집계할 수 없는 쿼터는 지킬 수 없는 규칙이다.
set -u
cd "$(dirname "$0")/.." || exit 1
DAY=$(date +%Y-%m-%d)
files=$(ls content/cards-"$DAY"-*.json 2>/dev/null)
n=$(printf '%s\n' "$files" | grep -c . )
echo "=== $DAY 카드 $n/5장 ==="
[ "$n" -eq 0 ] && { echo "  (아직 없음 — 오늘 첫 장)"; echo; echo "목표: ①따라하기1 ②타이밍경고2 ③한계붕괴1 ④소유욕1 / [구매가능]≥2 · 공유형2 · AI놀이≤1 · 루머≤1 · 대기업≤2"; exit 0; }
for f in $files; do
  t=$(sed -n 's/.*"topic"[[:space:]]*:[[:space:]]*"\(.*\)".*/\1/p' "$f" | head -1)
  printf "  · %s\n" "${t:0:96}"
done
echo
count(){ printf '%s\n' "$files" | xargs -I{} sh -c 'grep -o "\[[^]]*\]" "$1" | head -20' _ {} 2>/dev/null | grep -c "$1" || true; }
for tag in 구매가능 공유형 타이밍경고형 한계붕괴형 AI놀이 신제품 루머 펀딩 레트로 소유욕형; do
  c=$(grep -ho '"topic"[^,]*' $files 2>/dev/null | grep -c "\[$tag\]\|·$tag\]\|\[$tag·" || true)
  [ "$c" -gt 0 ] && printf "  %-12s %d장\n" "$tag" "$c"
done
echo
echo "남은 %d장 배정 시 확인: ④소유욕형 1장 배정됐나 · [구매가능] 2장 채웠나 · 대기업 2장 넘지 않았나" 
echo "  (대기업 상세: bash bin/brand_mix.sh)"
