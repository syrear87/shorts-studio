#!/bin/bash
# 텔레그램으로 영상 파일 발송. 사용법: tg-send-video.sh <video.mp4> "캡션"
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DIR/../telegram.env"

if [[ -z "${STUDIO_TG_TOKEN:-}" ]]; then
  echo "STUDIO_TG_TOKEN 미설정 — 발송 실패" >&2
  exit 3   # 성공 흉내 금지
fi

VIDEO="$1"
CAPTION="${2:0:1000}"
RESP=$(curl -sS -X POST "https://api.telegram.org/bot${STUDIO_TG_TOKEN}/sendVideo" \
  -F "chat_id=${STUDIO_TG_CHAT_ID}" \
  -F "video=@${VIDEO}" \
  -F "caption=${CAPTION}" \
  -F "supports_streaming=true")
if [[ "$RESP" == *'"ok":true'* ]]; then
  echo "영상 발송 완료: $VIDEO"
else
  echo "영상 발송 실패: $RESP" >&2
  exit 1
fi
