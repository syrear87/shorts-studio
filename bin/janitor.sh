#!/bin/bash
# 디스크 위생 (2026-08-23 신설, 같은 날 리뷰 반영 재작성)
# dm_tick.sh가 매 틱 호출하지만 하루 1회 가드(날짜 마커)를 **이 파일이 소유**한다 —
# 호출자와 성공/실패 계약을 나누던 숨은 커플링 제거. 전부 재생성 가능한 산출물만 지운다:
#   - assets/bg_cache: Pexels 배경 캐시. 총 6GB 상한 — 오래된 것부터 삭제(지워도 재다운로드될 뿐).
#   - out/*.mp4·jpg·png: 30일 지난 렌더 산출물(원본은 YT·IG·R2에 있음).
#   - logs/*.log: 60일 지난 로그.
# ⚠️ content/(대본·기록)와 assets/의 cache 외 폴더(실사 확보분)는 건드리지 않는다.
# ⚠️ 영상 렌더 진행 중(.daily.lock)이면 캐시를 건드리지 않고 다음 틱에 재시도 — 렌더가
#    참조 중인 캐시 파일을 지우는 경합 방지 (2026-08-23 리뷰).
set -u
ROOT=/Users/kimminsoo/Dev/shorts-studio
CACHE="$ROOT/assets/bg_cache"
CAP_GB=6
MARK="$ROOT/logs/.janitor_date"
TODAY=$(date +%Y-%m-%d)

[ "$(cat "$MARK" 2>/dev/null)" = "$TODAY" ] && exit 0          # 오늘 이미 돌았다
[ -f "$ROOT/logs/.daily.lock" ] && exit 0                       # 렌더 중 — 마커 없이 종료(다음 틱 재시도)

# bg_cache 상한 초과분 삭제 — stat 일괄 스냅샷(공백 파일명 안전·디렉터리 제외), mtime 오래된 것부터
if [ -d "$CACHE" ]; then
  total_kb=$(du -sk "$CACHE" | cut -f1)
  cap_kb=$((CAP_GB * 1024 * 1024))
  if [ "$total_kb" -gt "$cap_kb" ]; then
    excess_kb=$((total_kb - cap_kb))
    freed=0
    while IFS=' ' read -r _mt sz path; do
      [ "$freed" -ge "$excess_kb" ] && break
      [ -n "${sz:-}" ] || continue
      rm -f "$path" && freed=$((freed + (sz + 1023) / 1024))
    done < <(find "$CACHE" -mindepth 1 -maxdepth 1 -type f -exec stat -f '%m %z %N' {} + 2>/dev/null | sort -n)
    echo "[janitor] $(date '+%F %T') bg_cache ${excess_kb}KB 초과 → ${freed}KB 정리"
  fi
fi

# 30일 지난 렌더 산출물 / 60일 지난 로그
find "$ROOT/out" -type f \( -name "*.mp4" -o -name "*.jpg" -o -name "*.png" \) -mtime +30 -delete 2>/dev/null
find "$ROOT/logs" -type f -name "*.log" -mtime +60 -delete 2>/dev/null

echo "$TODAY" > "$MARK"    # 하루 1회가 불변식 — 부분 실패여도 스탬프(오류는 로그로 남는다)
exit 0
