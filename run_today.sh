#!/bin/bash
# 오늘 영상 원버튼 실행 — 렌더 + 텔레그램 발송. 브리지 세션용.
set -e
cd /Users/kimminsoo/Dev/shorts-studio
mkdir -p logs
{
  .venv/bin/python3 pipeline/make_short.py content/2026-07-28-chickengame.json --out out/2026-07-28-chickengame.mp4
  .venv/bin/python3 pipeline/upload_youtube.py out/2026-07-28-chickengame.mp4 content/2026-07-28-chickengame.meta.json
} > logs/manual-render.log 2>&1
echo "done"
