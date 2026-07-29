#!/bin/bash
# 스튜디오 → 텔레그램 보고 발송. 사용법: tg-send.sh "메시지"
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DIR/../telegram.env"

if [[ -z "${STUDIO_TG_TOKEN:-}" ]]; then
  echo "STUDIO_TG_TOKEN 미설정 — 발송 실패: $1" >&2
  exit 3   # 성공 흉내 금지 (2026-07-29 감사: 미전달이 exit 0으로 은폐되던 문제)
fi

TEXT="${1:0:4000}"
RESP=$(curl -sS -X POST "https://api.telegram.org/bot${STUDIO_TG_TOKEN}/sendMessage" \
  -d "chat_id=${STUDIO_TG_CHAT_ID}" \
  --data-urlencode "text=${TEXT}" \
  -d "disable_web_page_preview=true")
if [[ "$RESP" == *'"ok":true'* ]]; then
  echo "발송 완료 (${#TEXT}자)"
else
  echo "발송 실패: $RESP" >&2
  exit 1
fi
