#!/bin/bash
# 10분 틱: 댓글DM 백업 폴링 + 제휴 링크(텔레그램) 폴링 (2026-08-21 — launchd com.shorts-studio.dm)
# 판단이 필요 없는 기계 작업만 여기 묶는다. 실패 알림은 각 스크립트가 텔레그램으로 직접 보낸다.
cd /Users/kimminsoo/Dev/shorts-studio
.venv/bin/python3 pipeline/comment_dm.py
.venv/bin/python3 pipeline/affiliate_bot.py --once
