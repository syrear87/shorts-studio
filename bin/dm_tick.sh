#!/bin/bash
# 10분 틱: 댓글DM 백업 폴링 + 제휴 링크(텔레그램) 폴링 (2026-08-21 — launchd com.shorts-studio.dm)
# 판단이 필요 없는 기계 작업만 여기 묶는다. 실패 알림은 각 스크립트가 텔레그램으로 직접 보낸다.
# launchd PATH는 시스템 기본(/usr/bin:/bin:...)뿐이라 /opt/homebrew/bin의 ffmpeg·ffprobe가 안 잡힌다
# — 로그인 셸 사고 이력과 동일 클래스 (2026-08-23 리뷰. ${PATH:+...}는 PATH 미설정 시 트레일링 콜론=cwd 검색 방지)
export PATH="/opt/homebrew/bin:/usr/local/bin${PATH:+:$PATH}"
cd /Users/kimminsoo/Dev/shorts-studio
.venv/bin/python3 pipeline/comment_dm.py
.venv/bin/python3 pipeline/affiliate_bot.py --once
# 디스크 위생 — 하루 1회 가드는 janitor.sh 내부가 소유 (2026-08-23 리뷰: 커플링 제거)
bash bin/janitor.sh >> logs/janitor.log 2>&1

# 스레드 지표 스냅샷 — 하루 1회, 22시 이후 첫 틱에만 (2026-08-25 디렉터가 결산 크론을 걷어내면서
# 이관: 결산 '판단'은 요청 시 세션이 하고, '수집'은 여기서 매일 자동으로 남긴다. 스냅샷이 끊기면
# threads_stats.py의 전일 대비 증감이 죽는다. logs/threads_stats.jsonl에 append.)
SNAP_STAMP="logs/.threads_snap_date"
if [ "$(date +%H)" -ge 22 ] && [ "$(cat "$SNAP_STAMP" 2>/dev/null)" != "$(date +%F)" ]; then
  if .venv/bin/python3 pipeline/threads_stats.py >> logs/threads_snap.log 2>&1; then
    date +%F > "$SNAP_STAMP"
  fi
fi
