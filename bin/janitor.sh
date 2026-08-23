#!/bin/bash
# 디스크 위생 (2026-08-23 디렉터 "코드 정리·최적화" 지시로 신설)
# dm_tick.sh가 하루 1회 호출한다(날짜 마커 가드). 전부 재생성 가능한 산출물만 지운다:
#   - assets/bg_cache: Pexels 배경 캐시. 총 6GB 상한 — 초과분을 오래된 것부터 삭제(지워도 재다운로드될 뿐).
#   - out/*.mp4·*.jpg: 게시 후 30일 지난 산출물(원본은 YT·IG·R2에 있음).
#   - logs/daily-*.log 등 60일 지난 로그.
# ⚠️ content/(대본·기록)와 assets/의 cache 외 폴더(실사 확보분)는 건드리지 않는다.
set -u
ROOT=/Users/kimminsoo/Dev/shorts-studio
CACHE="$ROOT/assets/bg_cache"
CAP_GB=6

# bg_cache 상한 초과분 삭제 (오래된 mtime부터)
if [ -d "$CACHE" ]; then
  total_kb=$(du -sk "$CACHE" | awk '{print $1}')
  cap_kb=$((CAP_GB * 1024 * 1024))
  if [ "$total_kb" -gt "$cap_kb" ]; then
    excess_kb=$((total_kb - cap_kb))
    freed=0
    # macOS find: -t 정렬은 ls로 — 파일명에 공백 없다는 전제(캐시 키는 해시·슬러그)
    for f in $(ls -tr "$CACHE"); do
      [ "$freed" -ge "$excess_kb" ] && break
      sz=$(du -sk "$CACHE/$f" | awk '{print $1}')
      rm -f "$CACHE/$f" && freed=$((freed + sz))
    done
    echo "[janitor] bg_cache ${excess_kb}KB 초과 → ${freed}KB 정리"
  fi
fi

# 30일 지난 렌더 산출물
find "$ROOT/out" -type f \( -name "*.mp4" -o -name "*.jpg" -o -name "*.png" \) -mtime +30 -delete 2>/dev/null

# 60일 지난 로그
find "$ROOT/logs" -type f -name "*.log" -mtime +60 -delete 2>/dev/null
exit 0
