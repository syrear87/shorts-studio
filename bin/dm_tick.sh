#!/bin/bash
# 10분 틱: 댓글DM 백업 폴링 + 제휴 링크(텔레그램) 폴링 (2026-08-21 — launchd com.shorts-studio.dm)
# 판단이 필요 없는 기계 작업만 여기 묶는다. 실패 알림은 각 스크립트가 텔레그램으로 직접 보낸다.
# launchd PATH는 시스템 기본(/usr/bin:/bin:...)뿐이라 /opt/homebrew/bin의 ffmpeg·ffprobe가 안 잡힌다
# — 로그인 셸 사고 이력과 동일 클래스 (2026-08-23 리뷰. ${PATH:+...}는 PATH 미설정 시 트레일링 콜론=cwd 검색 방지)
export PATH="/opt/homebrew/bin:/usr/local/bin${PATH:+:$PATH}"
cd /Users/kimminsoo/Dev/shorts-studio
# ⏱️ 각 단계에 상한을 건다 — 하나가 멈추면 틱 전체(댓글DM·제휴·janitor·스냅샷)가 영구 정지하고
# launchd는 실행 중인 잡을 재기동하지 않아 최대 24시간 무경보로 죽어 있는다 (2026-08-25 감사).
# perl 기반 워치독: macOS 기본 셸에 timeout(1)이 없다.
_run_capped() {  # _run_capped <초> <명령...>
  local cap="$1"; shift
  # setpgrp로 자식을 새 프로세스 그룹에 두고 그룹 전체를 죽인다(손자까지). 시그널 사망은 128+n으로
  # 보고한다 — $?>>8은 시그널 종료 시 0이라 '성공'으로 오인돼 스냅샷 도장이 잘못 찍혔다 (2026-08-25 재감사).
  perl -e 'my $cap=shift @ARGV; my $p=fork(); if($p==0){ setpgrp(0,0); exec @ARGV or exit 127 } local $SIG{ALRM}=sub{ kill "KILL",-$p; waitpid($p,0); exit 124 }; alarm $cap; waitpid($p,0); my $st=$?; exit($st & 127 ? 128 + ($st & 127) : $st >> 8)' "$cap" "$@"
  local rc=$?
  if [ "$rc" = "124" ]; then
    echo "$(date '+%FT%T') dm_tick: '$*' 가 ${cap}초 초과로 강제 종료됨" >> logs/alert-fail.log
    bash bin/tg-send.sh "⚠️ dm 틱 단계가 ${cap}초를 넘겨 강제 종료됨: $* (틱 정지 방지)" || true
  elif [ "$rc" != "0" ]; then
    # 크래시(rc=1)는 지금까지 로그로만 흘러 **댓글DM·제휴봇이 무증상 영구 정지**할 수 있었다.
    # 경보 폭주를 막으려 같은 명령의 연속 실패는 하루 3회까지만 알린다 (2026-08-25 재감사).
    _fk="logs/.tickfail_$(echo "$1" | tr -c 'a-zA-Z0-9' '_')_$(date +%F)"
    _n=$(( $(cat "$_fk" 2>/dev/null || echo 0) + 1 ))
    echo "$_n" > "$_fk"
    echo "$(date '+%FT%T') dm_tick: '$*' rc=$rc (${_n}회째)" >> logs/alert-fail.log
    if [ "$_n" -le 3 ]; then
      bash bin/tg-send.sh "⚠️ dm 틱 단계 실패(rc=$rc, 오늘 ${_n}회): $*" || true
    fi
  fi
  return $rc
}
# 2026-09-05 중단: 댓글→DM 자동화는 **인스타 댓글**을 폴링하는데, 9/3부터 카드가
# 인스타에 안 나가면서(CARD_TO_IG=False) 유입 경로 자체가 사라졌다. 누적 발송 0건.
# 10분마다 도는 빈 폴링이라 껐다. 카드를 인스타로 되돌리면 이 줄을 살린다.
# _run_capped 300 .venv/bin/python3 pipeline/comment_dm.py
_run_capped 300 .venv/bin/python3 pipeline/affiliate_bot.py --once
# 디스크 위생 — 하루 1회 가드는 janitor.sh 내부가 소유 (2026-08-23 리뷰: 커플링 제거)
_run_capped 300 bash bin/janitor.sh >> logs/janitor.log 2>&1

# 스레드 지표 스냅샷 — 하루 1회, 22시 이후 첫 틱에만 (2026-08-25 디렉터가 결산 크론을 걷어내면서
# 이관: 결산 '판단'은 요청 시 세션이 하고, '수집'은 여기서 매일 자동으로 남긴다. 스냅샷이 끊기면
# threads_stats.py의 전일 대비 증감이 죽는다. logs/threads_stats.jsonl에 append.)
SNAP_STAMP="logs/.threads_snap_date"
if [ "$(date +%H)" -ge 22 ] && [ "$(cat "$SNAP_STAMP" 2>/dev/null)" != "$(date +%F)" ]; then
  if _run_capped 180 .venv/bin/python3 pipeline/threads_stats.py >> logs/threads_snap.log 2>&1; then
    date +%F > "$SNAP_STAMP"
  fi
fi
