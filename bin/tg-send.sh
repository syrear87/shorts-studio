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

# 🔕 오류·업로드 실패만 보낸다 (2026-10-20 디렉터: "이제 텔레그램으로 뭐 보내지 말고, 오류났거나
#    업로드 실패시만 그런 에러만 보내도록"). 게시 완료·중간보고·블로그 공개·재시도 안내 같은
#    정상 소식은 보내지 않고 logs/tg-suppressed.log에만 남긴다. 판정은 **첫 줄**로 한다 —
#    정상 리포트 본문에 '실패 없음' 같은 낱말이 섞여도 오발송하지 않게.
#    통과: 첫 줄이 ⚠️🔥🔴⛔❌🚨 로 시작하거나 오류 낱말(실패·오류·에러·타임아웃·만료·로그아웃·
#          미완주·비정상·증발·미게시·중단)을 담을 때.
#    예외 차단: "게시는 됐으나"(리포트 형식 경고 — 게시는 정상), 🔁(자동 재시도 중 — 최종 실패 시
#          따로 경보가 간다), 🔧(러너 자동 복구 시도 — 결과가 실패면 따로 경보가 간다).
#    강제 발송: TG_FORCE=1 bash tg-send.sh "..."
FIRST="$(printf '%s' "$1" | head -n 1)"
_send=0
if [[ "$FIRST" =~ ^(⚠️|⚠|🔥|🔴|⛔|❌|🚨) ]] || [[ "$FIRST" =~ (실패|오류|에러|타임아웃|만료|로그아웃|미완주|비정상|증발|미게시|중단) ]]; then
  _send=1
fi
if [[ "$FIRST" == *"게시는 됐으나"* ]] || [[ "$FIRST" =~ ^(🔁|🔧) ]]; then
  _send=0
fi
if [[ "${TG_FORCE:-0}" == "1" ]]; then _send=1; fi
if [[ "$_send" != "1" ]]; then
  mkdir -p "$DIR/../logs"
  printf '%s\t%s\n' "$(date +%FT%T)" "$(printf '%s' "$1" | tr '\n' ' ' | cut -c1-300)" >> "$DIR/../logs/tg-suppressed.log"
  echo "발송 생략(오류 아님) — logs/tg-suppressed.log"
  exit 0
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
