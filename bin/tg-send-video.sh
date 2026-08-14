#!/bin/bash
# 텔레그램으로 영상 파일 발송. 사용법: tg-send-video.sh <video.mp4> "캡션"
set -euo pipefail
export LC_ALL=en_US.UTF-8   # launchd C 로케일에서 ${2:0:1000}이 바이트 절단→UTF-8 파손되는 것 예방 (2026-08-02 리뷰)
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[[ -f "$DIR/../telegram.env" ]] || { echo "telegram.env 없음" >&2; exit 3; }   # set -e 무언사 방지 (tg-send.sh와 동일 가드)
source "$DIR/../telegram.env"

if [[ -z "${STUDIO_TG_TOKEN:-}" ]]; then
  echo "STUDIO_TG_TOKEN 미설정 — 발송 실패" >&2
  exit 3   # 성공 흉내 금지
fi

VIDEO="$1"
CAPTION="${2:0:1000}"
RESP=$(curl -sS --max-time 300 -X POST "https://api.telegram.org/bot${STUDIO_TG_TOKEN}/sendVideo" \
  -F "chat_id=${STUDIO_TG_CHAT_ID}" \
  -F "video=@${VIDEO}" \
  -F "caption=${CAPTION}" \
  -F "supports_streaming=true")
if [[ "$RESP" == *'"ok":true'* ]]; then
  # 2026-08-02 리뷰(OPS-3): 게시 실측 근거 — 러너 check_artifacts가 이 파일(logs/sent.log)로 발송 여부를 판정한다.
  mkdir -p "$DIR/../logs"
  echo "$(date +%FT%T) $(basename "$VIDEO")" >> "$DIR/../logs/sent.log"
  echo "영상 발송 완료: $VIDEO"
else
  echo "영상 발송 실패: $RESP" >&2
  exit 1
fi
