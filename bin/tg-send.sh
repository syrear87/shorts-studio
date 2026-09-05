#!/bin/bash
# 스튜디오 → 텔레그램 보고 발송. 사용법: tg-send.sh "메시지"
set -euo pipefail
export LC_ALL=en_US.UTF-8   # launchd C 로케일에서 ${1:0:4000}이 바이트 절단→UTF-8 파손되는 것 예방 (2026-08-02 리뷰)
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[[ -f "$DIR/../telegram.env" ]] || { echo "telegram.env 없음" >&2; exit 3; }   # set -e 무언사(無言死) 방지 (2026-08-02 리뷰)
source "$DIR/../telegram.env"

if [[ -z "${STUDIO_TG_TOKEN:-}" ]]; then
  echo "STUDIO_TG_TOKEN 미설정 — 발송 실패: $1" >&2
  exit 3   # 성공 흉내 금지 (2026-07-29 감사: 미전달이 exit 0으로 은폐되던 문제)
fi

# 4000자 초과는 무언 절단 대신 분할 발송 (2026-08-14 감사 — 잘리는 쪽이 태그·꼬리 정보부다)
MSG="$1"
while [[ -n "$MSG" ]]; do
  TEXT="${MSG:0:3900}"
  MSG="${MSG:3900}"
  RESP=$(curl -sS --max-time 60 -X POST "https://api.telegram.org/bot${STUDIO_TG_TOKEN}/sendMessage" \
    -d "chat_id=${STUDIO_TG_CHAT_ID}" \
    --data-urlencode "text=${TEXT}" \
    -d "disable_web_page_preview=true")
  if [[ "$RESP" == *'"ok":true'* ]]; then
    echo "발송 완료 (${#TEXT}자)"
  else
    echo "발송 실패: $RESP" >&2
    exit 1
  fi
done
