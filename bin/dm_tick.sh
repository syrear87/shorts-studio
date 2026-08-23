#!/bin/bash
# 10분 틱: 댓글DM 백업 폴링 + 제휴 링크(텔레그램) 폴링 (2026-08-21 — launchd com.shorts-studio.dm)
# 판단이 필요 없는 기계 작업만 여기 묶는다. 실패 알림은 각 스크립트가 텔레그램으로 직접 보낸다.
# launchd는 PATH가 비어 있다(ffmpeg·ffprobe가 /opt/homebrew/bin) — 로그인 셸 사고 이력과 동일 클래스 (2026-08-23 리뷰)
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
cd /Users/kimminsoo/Dev/shorts-studio
.venv/bin/python3 pipeline/comment_dm.py
.venv/bin/python3 pipeline/affiliate_bot.py --once
# 디스크 위생 — 하루 1회 가드는 janitor.sh 내부가 소유 (2026-08-23 리뷰: 커플링 제거)
bash bin/janitor.sh >> logs/janitor.log 2>&1
