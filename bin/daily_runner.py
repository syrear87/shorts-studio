#!/usr/bin/env python3
# launchd가 슬롯마다 실행(편성 v11.1 — 영상 07/12/18시 · 카드 09~17시 매시, KST) — 헤드리스 스튜디오 세션 기동.
# 락으로 중복 방지(모드별 분리), 영상 100분·카드 45분 타임아웃, 로그 저장, 실패·무산출 시 텔레그램 통보.
import os, subprocess, sys, time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# 모드는 plist가 넘기는 --mode 인자가 정본 (2026-08-05 점검: 절전 벌충 지연 기동 시
# 시각 판정은 카드↔영상이 뒤바뀜) — 인자 부재 시에만 시각 폴백.
# 카드 세션은 짧게(45분) 잘라 다음 슬롯과 겹치지 않게 하고, 락도 분리한다.
if "--mode" in sys.argv:
    CARD_MODE = sys.argv[sys.argv.index("--mode") + 1] == "card"
else:
    CARD_MODE = False   # 편성 v8 (2026-08-14): 카드 폐지 — 전 슬롯 영상. --mode card는 수동 호출용으로만 남긴다
PROMPT_FILE = "CARD_PROMPT.md" if CARD_MODE else "DAILY_PROMPT.md"
LOCK = ROOT / "logs" / (".card.lock" if CARD_MODE else ".daily.lock")   # ⚠️ .daily.lock의 파일명·내용(PID)은 bin/janitor.sh 렌더 감지와 결합 (2026-08-23)
LOG = ROOT / "logs" / ("daily-%s.log" % datetime.now().strftime("%Y%m%d-%H%M"))
TIMEOUT = (45 if CARD_MODE else 100) * 60
# (STALE mtime 판정은 2026-08-23 4차 리뷰로 폐지 — 절전 시 살아있는 세션 오판. 락 판정은 PID 정체 검사로 통일)
# 일시적 API 장애(529 과부하·429 한도·연결 오류)는 몇 분이면 풀린다 → 재시도로 슬롯을 구한다.
# 2026-07-30 17:00 실사고: 529 Overloaded로 즉사, 재시도가 없어 슬롯 하나가 통째로 증발.
RETRY_MARKERS = ("529", "overloaded", "rate_limit", "429", "Connection error",
                 "ECONNRESET", "ETIMEDOUT", "socket hang up", "500 Internal")
RETRY_DELAYS = (180, 420)     # 3분 → 7분 (최대 2회 재시도)
SAFE_RETRY_MAX_LEN = 800      # 이보다 로그가 길면 세션이 실제 작업을 했을 수 있으므로 재시도 금지(중복 게시 방지)


def tg(msg):
    # 2026-08-02 리뷰(OPS-1): 경보 발송 실패를 침묵시키지 않는다 — watchdog.py와 동일하게 로컬 파일에 기록.
    try:
        r = subprocess.run(["bash", str(ROOT / "bin" / "tg-send.sh"), msg], timeout=30)
        if r.returncode != 0:
            _alert_fail("rc=%d" % r.returncode, msg)
    except Exception as e:
        _alert_fail("예외 %s" % e, msg)

def _alert_fail(why, msg):
    # 경보 채널 자체가 죽음 — 로컬 파일에라도 남긴다 (watchdog.py:34와 동일 패턴, 2026-08-02 리뷰)
    try:
        with open(ROOT / "logs" / "alert-fail.log", "a") as f:
            f.write("%s 텔레그램 발송 실패(%s): %s\n" % (datetime.now().isoformat(), why, msg))
    except Exception:
        pass

# log_looks_dead 판정 코드 — 호출자는 이 상수로 분기한다 (2026-08-23 리뷰: 경보 문안 부분문자열
# 매칭이 문구 수정 한 번에 재시도 로직을 끄던 결합 제거)
DEAD_AUTH, DEAD_SHORT, DEAD_NO_SENTINEL = "auth", "short", "no_sentinel"


def log_looks_dead(text):
    """세션 사망 의심 판정. 반환: (판정코드, 사람용 사유) 또는 None(정상)."""
    t = text.strip()
    # 완주 센티널을 최우선 인정하되 **마지막 비어있지 않은 줄** 기준 (2026-08-23 4차 리뷰:
    # substring 검사는 규칙을 '인용'만 하고 죽은 세션까지 생존 처리했다. 규약상 센티널은 마지막 줄이다)
    _lines = [l for l in t.splitlines() if l.strip()]
    if _lines and "SLOT-DONE" in _lines[-1]:
        return None
    # claude -p는 인증 만료(401)로 죽어도 종료코드 0 — 2026-07-29 11:00 슬롯이 경보 없이 증발한 원인.
    for marker in ("failed to authenticate", "authentication_error", "oauth access token"):
        if marker in t.lower():   # 2026-08-02 리뷰: 재시도 판정과 동일하게 소문자 비교로 통일
            return (DEAD_AUTH, "인증 오류 감지")
    # 2026-08-02 리뷰(OPS-4): 마감 센티널(SLOT-DONE)의 존재가 완주의 1차 근거다.
    # 센티널이 있으면 길이는 보지 않는다 — 첫 야간 슬롯 실사고: 규칙대로 간결하게
    # 마감한 82자 응답(센티널 포함)을 길이 검사가 '즉사'로 오판해 허위 경보 발송.
    # ⚠️ SLOT-NOOP은 여기서 인정하지 않는다 (2026-08-23 2차 리뷰 회귀 정정): DAILY_PROMPT상
    # 정당한 NOOP도 마지막 줄 SLOT-DONE이 의무다 — NOOP만 찍고 마감 전에 죽은 반쪽 세션은 경보 대상.
    if len(t) < 200:
        return (DEAD_SHORT, "출력 %d자 + 센티널 부재 (세션 즉사 의심)" % len(t))
    return (DEAD_NO_SENTINEL, "마감 센티널(SLOT-DONE) 부재 (세션 미완주 의심)")

def sent_evidence(start_ts):
    """이 세션 구간에 만들어진 mp4가 sent.log 실측 발송 기록으로 남았는가.
    2026-08-05 실사고(디렉터 승인 수정): 완주한 세션이 'SLOT-DONE' 리터럴 대신 "슬롯 완료"로
    마감 → 허위 미완주 경보. 센티널은 1차 판정으로 유지하되, 부재 시 실측으로 구제한다."""
    try:
        sent = ROOT / "logs" / "sent.log"
        if not (sent.exists() and sent.stat().st_mtime >= start_ts):
            return False
        recent = sent.read_text(errors="ignore").strip().splitlines()[-5:]
        if CARD_MODE:
            # 카드 세션은 mp4가 없다 — 캐러셀 게시 실측(IGCARD:)으로 판정 (2026-08-05)
            return any("IGCARD:" in ln for ln in recent)
        new_mp4 = {p.name for p in (ROOT / "out").glob("*.mp4") if p.stat().st_mtime >= start_ts}
        if not new_mp4:
            return False
        return any(any(n in ln for n in new_mp4) for ln in recent)
    except Exception:
        return False


def main():
    os.chdir(str(ROOT))
    (ROOT / "logs").mkdir(exist_ok=True)
    if LOCK.exists():
        # 락 판정 = PID 정체 검사 (2026-08-23 4차 리뷰: mtime STALE은 절전 시 살아있는 세션을 잔재로,
        # 크래시 직후 잔재를 실행 중으로 오판했다 — janitor.sh와 동일 방식으로 통일. PID 재사용은
        # 커맨드에 daily_runner가 있는지로 배제)
        alive = False
        try:
            lpid = int(LOCK.read_text().strip())
            out = subprocess.run(["ps", "-p", str(lpid), "-o", "command="],
                                 capture_output=True, text=True, timeout=10)
            alive = "daily_runner" in (out.stdout or "")
        except Exception:
            alive = False
        if alive:
            tg("⏳ 숏츠 데일리: 이전 세션이 아직 실행 중 — 오늘 기동 건너뜀")
            return
        LOCK.unlink()   # 죽은 PID의 잔재 락
    # claude는 node 기반 → launchd의 빈 PATH에서 죽는다(2026-07-29 실사고: env: node not found).
    # 로그인 셸(zsh -l)을 통째로 경유해 사용자 PATH(node·claude 포함)를 복원한다.
    chk = subprocess.run(["/bin/zsh", "-l", "-c", "which claude"], capture_output=True, text=True, timeout=30)
    if chk.returncode != 0 or not chk.stdout.strip():
        tg("⚠️ 숏츠 데일리: 로그인 셸에서도 claude CLI를 찾지 못해 기동 실패")
        sys.exit(1)
    LOCK.write_text(str(os.getpid()))
    start_ts = time.time()
    try:
        for attempt in range(len(RETRY_DELAYS) + 1):
            # 2026-08-02 리뷰(OPS-8): "w"→"a" — 재시도가 직전 시도의 에러 증거(529 본문 등)를 덮어쓰지 않게 보존.
            with open(LOG, "a") as lf:
                lf.write("=== attempt %d ===\n" % (attempt + 1))
                lf.flush()
                # 2026-08-22 11:00 실사고: 세션이 "무엇을 도와드릴까요?"만 남기고 종료(빈 프롬프트 의심).
                # 프롬프트 글자수를 기동 직전에 실측 기록해 다음 재발 때 cat 실패인지 모델 즉사인지 가른다.
                r = subprocess.run(
                    ["/bin/zsh", "-l", "-c",
                     'p="$(cat %s)"; print -r -- "[runner] prompt ${#p}자"; '
                     'claude -p "$p" --model opus --permission-mode acceptEdits' % PROMPT_FILE],
                    stdout=lf, stderr=subprocess.STDOUT, timeout=TIMEOUT, cwd=str(ROOT))
            # 판정은 마지막 attempt 구간만 읽는다 — 이전 시도의 마커·본문과 섞임 방지 (2026-08-02 리뷰)
            text = LOG.read_text(errors="ignore").split("=== attempt ")[-1]
            # 2026-08-02 리뷰(OPS-2): 이번 슬롯에서 새 mp4가 이미 나왔으면 렌더+발송을 마쳤을 수 있으므로
            # 재시도 금지(중복 게시 방지) — 아래 rc!=0 분기의 경보만 발송된다. 길이 가드는 보조로 유지.
            new_mp4_made = any(p.stat().st_mtime >= start_ts for p in (ROOT / "out").glob("*.mp4"))
            evidence = sent_evidence(start_ts)   # 발송 실측 있으면 재시도 금지 — 중복 게시 봉쇄 (2026-08-05 점검)
            transient = (r.returncode != 0 and len(text.strip()) <= SAFE_RETRY_MAX_LEN
                         and not new_mp4_made and not evidence
                         and any(m.lower() in text.lower() for m in RETRY_MARKERS))
            # 2026-08-22 11:00 실사고: rc=0인데 인사말만 남기고 종료(즉사) — 마커가 없어 재시도를 안 탔다.
            # 산출물·발송·센티널이 전무한 초단문 종료는 장애로 간주해 재시도로 슬롯을 구한다.
            # 판정 코드(DEAD_SHORT)로 분기 — 문안 결합 금지. SLOT-NOOP(의도된 무제작)는 재시도 무의미.
            # 인증 오류(DEAD_AUTH)는 재시도해도 소용없어 제외 — 경보 경로가 잡는다.
            if not transient and r.returncode == 0 and not new_mp4_made and not evidence:
                _dead = log_looks_dead(text)
                if _dead and _dead[0] == DEAD_SHORT and "SLOT-NOOP" not in text:
                    transient = True
            if not transient or attempt >= len(RETRY_DELAYS):
                break
            delay = RETRY_DELAYS[attempt]
            tg("🔁 숏츠 데일리: 일시적 API 장애로 즉사 — %d분 후 재시도 (%d/%d)"
               % (delay // 60, attempt + 1, len(RETRY_DELAYS)))
            LOCK.write_text(str(os.getpid()))   # 스테일 판정 방지용 갱신
            time.sleep(delay)

        if r.returncode != 0:
            tg("⚠️ 숏츠 데일리 세션 비정상 종료 (코드 %d, 재시도 %d회) — %s 확인"
               % (r.returncode, attempt, LOG.name))
        else:
            reason = log_looks_dead(text)
            if reason and sent_evidence(start_ts):
                # 센티널 누락이지만 발송 실측 존재 — 완주 인정, 형식 위반 주의만 (2026-08-05 디렉터 승인)
                # 2026-08-21 디렉터: '조치 불필요' 정보성 알림은 텔레그램 소음 — 로그로만 남긴다
                print("[runner] 센티널 누락, 실측 완주 확인 — 조치 불필요", flush=True)
                check_artifacts(start_ts)
            elif reason:
                tg("⚠️ 숏츠 데일리: 종료코드는 0인데 %s — %s 확인" % (reason[1], LOG.name))
            else:
                check_artifacts(start_ts)
    except subprocess.TimeoutExpired:
        tg("⚠️ %s 세션 타임아웃(%d분) — %s 확인" % ("지식 카드" if CARD_MODE else "숏츠 데일리", TIMEOUT // 60, LOG.name))
    finally:
        LOCK.unlink(missing_ok=True)


def check_artifacts(start_ts):
    """세션의 자기 성공 보고를 산출물 실측으로 대조 (2026-07-29 감사: 자기채점 누수 지적).
    세션 시작 이후 갱신된 out/*.mp4가 없고, 로그에 게시 중단 사유도 없으면 경보.
    2026-08-02 리뷰(OPS-3): 발송 판정을 로그 문구(모델의 자기 보고)에서 logs/sent.log 실측으로 교체 —
    tg-send-video.sh·upload_youtube.py가 성공 시에만 "시각 파일명" 한 줄을 append한다."""
    try:
        logtext = LOG.read_text(errors="ignore")
        # 2026-08-03 실사고: 슬롯이 앞선 세션에 의해 이미 채워져 세션이 정당하게 무제작 종료했는데
        # '산출물 없음' 경보 발송 → SLOT-NOOP 마커(의도된 무제작)를 정상 종료로 인정
        # 2026-08-14 감사: '기각'은 의도 마커가 아니다 — 렌더 기각 후 자가수정 실패로 무산출 종료해도
        # '의도된 미게시'로 오분류돼 슬롯 공실이 무경보로 지나갔다. 기각은 아래에서 별도 경보한다.
        if any(k in logtext for k in ("게시 중단", "게시 보류", "SLOT-NOOP", "이미 제작·발송 완료")):
            # 2026-08-23 4차 리뷰: 인증이 실제로 깨져 'SLOT-NOOP 인증 오류'로 규정대로 마감한 세션은
            # 여기서 조기 return되며 완전 무경보였다 — NOOP 사유에 인증 흔적이 있으면 경보는 남긴다.
            if any(m in logtext.lower() for m in ("failed to authenticate", "authentication_error", "oauth access token")):
                tg("⚠️ 숏츠 데일리: 세션이 인증 오류 사유로 무제작 종료 — 토큰 상태 확인 필요 (%s)" % LOG.name)
            return  # 의도된 미게시/무제작 — 세션이 사유를 보고했음
        gate_rejected = "기각" in logtext
        if CARD_MODE:
            # 카드 세션 산출물 판정 (2026-08-05): 캐러셀 게시 실측(IGCARD:)이 세션 시작 이후 기록됐는가
            sent = ROOT / "logs" / "sent.log"
            ok = sent.exists() and sent.stat().st_mtime >= start_ts and \
                any("IGCARD:" in ln for ln in sent.read_text(errors="ignore").strip().splitlines()[-5:])
            if not ok:
                tg("⚠️ 지식 카드: 세션은 정상 종료했지만 캐러셀 게시 실측(IGCARD)이 없음%s — %s 확인"
                   % (" (로그에 기각 있음 — 자가수정 실패 가능)" if gate_rejected else "", LOG.name))
            return
        new_mp4 = [p for p in (ROOT / "out").glob("*.mp4") if p.stat().st_mtime >= start_ts]
        if not new_mp4:
            tg("⚠️ 숏츠 데일리: 세션은 정상 종료했지만 새 영상 산출물이 없음%s — %s 확인"
               % (" (렌더 기각 후 자가수정 실패로 보임)" if gate_rejected else "", LOG.name))
            return
        sent = ROOT / "logs" / "sent.log"
        sent_ok = sent.exists() and sent.stat().st_mtime >= start_ts
        if sent_ok:
            lines = sent.read_text(errors="ignore").strip().splitlines()[-5:]
            # 카드·영상 세션 병행으로 교차 기록될 수 있어 최근 5행에서 탐색 (2026-08-05 점검)
            sent_ok = bool(lines) and any(any(p.name in ln for ln in lines) for p in new_mp4)
        if not sent_ok:
            # 기존 문자열 검사는 보조로 강등 — 경보 문면의 진단 정보로만 쓴다
            note = " (로그엔 발송 문구가 있음 — 자기 보고 불일치)" if ("발송 완료" in logtext or "phase0" in logtext) else ""
            tg("⚠️ 숏츠 데일리: 영상은 있는데 sent.log 발송 실측 기록이 없음%s — 게시 단계 누락 의심, %s 확인"
               % (note, LOG.name))
    except Exception:
        pass


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # 러너 자체가 죽으면 경보자가 죽는 문제 방지 (2026-07-29 감사)
        tg("🔥 숏츠 데일리 러너 자체 오류: %s" % str(e)[:300])
        raise
