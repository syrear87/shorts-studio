#!/usr/bin/env python3
# launchd가 슬롯마다 실행(편성 정본은 RULES.md §편성 정본 — 영상 10:20/13:20/21:00 · 카드 09/12/14/16/20시, KST) — 헤드리스 스튜디오 세션 기동.
# 락으로 중복 방지(모드별 분리), 영상 75분·카드 45분 타임아웃, 로그 저장, 실패·무산출 시 텔레그램 통보.
import os, re, subprocess, sys, time
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
# 2026-09-05 정본 단일화: 공통 규칙은 RULES.md 하나에만 두고, 모드 파일 앞에 붙여 넘긴다.
# 종전에는 같은 절이 두 파일에 복사돼 있었고 9/2 편성 변경이 한쪽에만 반영돼,
# 카드 세션이 사흘 동안 이미 없어진 "영상 5편" 편성을 읽고 있었다.
MODE_FILE = "CARD_PROMPT.md" if CARD_MODE else "DAILY_PROMPT.md"
# ⚠️ 순서가 중요하다 (2026-09-06 09:00 실사고): RULES.md를 앞에 두자 프롬프트가
# "# RULES — 공통 정본…" 문서 헤더로 시작했고, 세션이 이를 **읽어달라는 문서**로 읽어
# "The project context is loaded. What do you need help with?"만 남기고 종료했다.
# 모드 파일은 "너는 ~ 슬롯 세션이다. 이번 실행에서 ~하고 끝난다"로 시작한다 —
# **임무가 첫 줄에 와야 한다.** 공통 규칙은 참조라 뒤에 와도 된다.
PROMPT_FILES = [MODE_FILE, "RULES.md"]
# 임무 한 줄을 러너가 직접 맨 앞에 박는다 — 파일이 무엇으로 시작하든 **첫 줄은 지시**여야 한다.
# 2026-09-06 09:00: 프롬프트가 "# RULES — 공통 정본…"으로 시작하자 세션이 문서 열람 요청으로
# 읽고 "What do you need help with?"만 남기고 종료했다. 파일 첫 줄에 의존하지 않는다.
HEAD_FILE = ROOT / "logs" / ".prompt_head.txt"


def write_head():
    what = ("테크 카드 1건(2~3장 캐러셀)을 만들어 스레드·블로그에 게시"
            if CARD_MODE else "지식 숏폼 1편을 만들어 유튜브·인스타에 게시")
    HEAD_FILE.parent.mkdir(exist_ok=True)
    HEAD_FILE.write_text(
        "너는 숏츠 스튜디오의 %s 슬롯 세션이다. 작업 디렉토리는 ~/Dev/shorts-studio.\n"
        "**지금 이 실행에서 %s하고 마감 리포트를 남기는 것이 이번 슬롯의 임무다.**\n"
        "아래는 그 지시서다 — 읽어달라는 문서가 아니라 **따라야 할 절차**다. "
        "질문하거나 대기하지 말고 착수하라. 무인 실행이라 답할 사람이 없다.\n\n"
        "---\n\n" % ("카드" if CARD_MODE else "영상", what),
        encoding="utf-8")
    return str(HEAD_FILE.relative_to(ROOT))
PROMPT_FILE = MODE_FILE   # (기존 로그·메트릭 호환)


def prompt_sha():
    """넘기는 프롬프트 전체(RULES+모드)의 해시. 한쪽만 바뀌어도 값이 바뀐다."""
    import hashlib as _hl
    h = _hl.sha256()
    for f in PROMPT_FILES:
        h.update((ROOT / f).read_bytes())
    h.update(b"head-v1")
    return h.hexdigest()[:12]
LOCK = ROOT / "logs" / (".card.lock" if CARD_MODE else ".daily.lock")   # ⚠️ .daily.lock의 파일명·내용(PID)은 bin/janitor.sh 렌더 감지와 결합 (2026-08-23)
LOG = ROOT / "logs" / ("daily-%s.log" % datetime.now().strftime("%Y%m%d-%H%M"))
# 영상 75분: v12에서 영상 슬롯 간격이 120분(13:20→15:20)으로 좁아졌다. 실측 소요는 평균 30분·최대 48분이라
# 75분이면 충분하고, 폭주한 세션이 락을 쥔 채 다음 슬롯을 잡아먹는 것을 45분 여유로 막는다 (2026-08-24 v12).
TIMEOUT = (45 if CARD_MODE else 75) * 60
CARD_QUOTA = 5   # 하루 카드 상한 (v12.1 2026-08-24 디렉터: "카드 6번으로 줄이자" — 도달 붕괴 대응 감축).
                 # 가드 유래: 8/24 실사고 — 15시 슬롯이 결번 벌충 3연발로 쿼터를 채웠는데 후속 슬롯이
                 # 그대로 발화해 11장이 나갔다. 세션은 매번 새로 떠서 당일 누계를 모른다 → sent.log 실측.
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
# 인증 실패 판정 마커 — log_looks_dead·check_artifacts·재시도 문안이 같은 기준을 쓰도록 한 곳에 둔다
AUTH_MARKERS = ("failed to authenticate", "authentication_error", "oauth access token")


def log_looks_dead(text):
    """세션 사망 의심 판정. 반환: (판정코드, 사람용 사유) 또는 None(정상)."""
    t = text.strip()
    # 완주 센티널을 최우선 인정하되 **마지막 3개 비어있지 않은 줄** 기준 (2026-08-23 4차:
    # substring 검사는 규칙 '인용'만 한 죽은 세션까지 생존 처리 / 5차: stderr 병합이라 종료 직전
    # node 경고 꼬리가 센티널 뒤에 붙을 수 있어 마지막 1줄 앵커는 반대 방향 오탐 — 3줄로 완충)
    _lines = [l for l in t.splitlines() if l.strip()]
    if any("SLOT-DONE" in l for l in _lines[-3:]):
        return None
    # claude -p는 인증 만료(401)로 죽어도 종료코드 0 — 2026-07-29 11:00 슬롯이 경보 없이 증발한 원인.
    for marker in AUTH_MARKERS:
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

def fresh_mp4(start_ts):
    """start_ts 이후에 만들어진 out/*.mp4. janitor의 -delete와 경합해 파일이 사라져도
    순회를 죽이지 않는다 — 같은 패턴 3곳이 제각각이던 것을 하나로 (2026-08-25 재감사)."""
    out = []
    for p_ in (ROOT / "out").glob("*.mp4"):
        try:
            if p_.stat().st_mtime >= start_ts:
                out.append(p_)
        except OSError:
            continue
    return out


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
            # 카드 세션은 mp4가 없다 — 캐러셀 게시 실측으로 판정 (2026-08-05)
            # 2026-09-02: 카드가 인스타에서 빠지면서 마크가 THCARD:로 바뀌었다.
            # 둘 다 인정한다(CARD_TO_IG를 되돌려도 깨지지 않게).
            return any(("IGCARD:" in ln or "THCARD:" in ln) for ln in recent)
        new_mp4 = {p.name for p in fresh_mp4(start_ts)}
        if not new_mp4:
            return False
        return any(any(n in ln for n in new_mp4) for ln in recent)
    except Exception:
        return False


def cards_sent_today():
    """오늘 이미 게시된 카드 수 (sent.log 실측). 판정 불가 시 -1 — 가드를 열어둔다."""
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        sent = ROOT / "logs" / "sent.log"
        if not sent.exists():
            return 0
        return sum(1 for ln in sent.read_text(errors="ignore").splitlines()
                   if ln.startswith(today) and ("IGCARD:" in ln or "THCARD:" in ln))
    except Exception:
        return -1


def main():
    os.chdir(str(ROOT))
    (ROOT / "logs").mkdir(exist_ok=True)
    # 카드 쿼터 가드 (2026-08-24 v12): 벌충 몰아내기로 쿼터가 이미 찼으면 남은 슬롯은 조용히 결번.
    # 도달이 붕괴 중인 계정에 초과 물량은 순손해다 — 세션을 띄우기 전에 끊는다.
    if CARD_MODE:
        n = cards_sent_today()
        if n >= CARD_QUOTA:
            with open(LOG, "a") as lf:
                lf.write("SLOT-NOOP 카드 쿼터 충족(%d/%d) — 결번\nSLOT-DONE quota-guard\n" % (n, CARD_QUOTA))
            return
    if LOCK.exists():
        # 락 판정 = PID 정체 검사 (2026-08-23 4차 리뷰: mtime STALE은 절전 시 살아있는 세션을 잔재로,
        # 크래시 직후 잔재를 실행 중으로 오판했다 — janitor.sh와 동일 방식으로 통일. PID 재사용은
        # 커맨드에 daily_runner가 있는지로 배제)
        alive, judge_failed = False, False
        try:
            lpid = int(LOCK.read_text().strip())
            out = subprocess.run(["ps", "-p", str(lpid), "-o", "command="],
                                 capture_output=True, text=True, timeout=10)
            cmd = out.stdout or ""
            # 모드까지 대조 — PID 재사용이 반대 모드 러너에 맞아도 오판하지 않게 (2026-08-23 5차)
            my_card = ("--mode card" in cmd)
            alive = "daily_runner" in cmd and my_card == CARD_MODE
        except ValueError:
            pass   # PID 아님 — 잔재
        except Exception:
            judge_failed = True   # ps 실패는 '죽음'과 다르다 — 진행하되 흔적을 남긴다 (5차: fail-open 가시화)
        if alive:
            tg("⏳ 숏츠 데일리: 이전 세션이 아직 실행 중 — 오늘 기동 건너뜀")
            return
        if judge_failed:
            tg("⚠️ 숏츠 데일리: 락 생존 판정 실패(ps 오류) — 잔재로 간주하고 진행. 중복 기동이면 멱등 가드가 게시를 막는다")
        LOCK.unlink(missing_ok=True)   # 죽은 PID의 잔재 락 (죽어가던 세션의 finally와 경합 가능 — 2026-08-25 감사)
    # claude는 node 기반 → launchd의 빈 PATH에서 죽는다(2026-07-29 실사고: env: node not found).
    # 로그인 셸(zsh -l)을 통째로 경유해 사용자 PATH(node·claude 포함)를 복원한다.
    # 락을 먼저 잡는다 — which claude(최대 30초) 동안 락이 비어 janitor가 "렌더 없음"으로
    # 오판하던 공백 구간을 없앤다 (2026-08-25 감사). 실패 시 아래에서 해제한다.
    LOCK.write_text(str(os.getpid()))
    try:
        chk = subprocess.run(["/bin/zsh", "-l", "-c", "which claude"],
                             capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        # 2026-08-28 감사: 여기서 TimeoutExpired가 나면 방금 쓴 락이 해제되지 않은 채
        # 죽어 janitor 개입 전까지 다음 슬롯을 막았다 — 락을 풀고 경보 후 종료한다.
        LOCK.unlink(missing_ok=True)
        tg("⚠️ 숏츠 데일리: which claude 30초 타임아웃 — 기동 실패(락 해제됨)")
        sys.exit(1)
    if chk.returncode != 0 or not chk.stdout.strip():
        LOCK.unlink(missing_ok=True)
        tg("⚠️ 숏츠 데일리: 로그인 셸에서도 claude CLI를 찾지 못해 기동 실패")
        sys.exit(1)
    start_ts = time.time()
    try:
        for attempt in range(len(RETRY_DELAYS) + 1):
            # 2026-08-02 리뷰(OPS-8): "w"→"a" — 재시도가 직전 시도의 에러 증거(529 본문 등)를 덮어쓰지 않게 보존.
            with open(LOG, "a") as lf:
                lf.write("=== attempt %d ===\n" % (attempt + 1))
                lf.flush()
                # 2026-08-22 11:00 실사고: 세션이 "무엇을 도와드릴까요?"만 남기고 종료(빈 프롬프트 의심).
                # 프롬프트 글자수를 기동 직전에 실측 기록해 다음 재발 때 cat 실패인지 모델 즉사인지 가른다.
                # 2026-08-27 계측 패치: 프롬프트 SHA-256 앞 12자를 남긴다. 토큰 절감 패치의
                # 전/후를 로그만 보고 확실히 가르기 위해서다(프롬프트가 바뀌면 해시가 바뀐다).
                try:
                    _ph = prompt_sha()
                except Exception:
                    _ph = "?"
                lf.write("[runner] prompt-sha %s (임무헤더 + %s)\n" % (_ph, " + ".join(PROMPT_FILES)))
                lf.flush()
                # CARD_MODE를 자식(claude 세션)에게도 넘긴다 (2026-09-05):
                # upload_threads.publish_text가 이 값으로 카드 라인 여부를 판정한다 —
                # 영상 세션이 스레드에 텍스트 글을 올린 사고(「나홍진 호프」) 재발 방지.
                # 컨텍스트 팩 (2026-09-06): 착수 전 통독 254,667자를 4천 자로 줄인 한 장.
                # 슬롯 직전에 새로 만든다 — 어제 팩을 읽으면 오늘 소재가 중복된다.
                try:
                    subprocess.run([str(ROOT / ".venv/bin/python3"),
                                    str(ROOT / "bin/context_pack.py")],
                                   timeout=120, check=False, cwd=str(ROOT),
                                   stdout=lf, stderr=subprocess.STDOUT)
                except Exception as _e:
                    lf.write("[runner] context_pack 실패(무해, 세션이 원본을 읽는다): %s\n"
                             % str(_e)[:90])
                lf.flush()
                _env = dict(os.environ, CARD_MODE="1" if CARD_MODE else "0")
                r = subprocess.run(
                    ["/bin/zsh", "-l", "-c",
                     'p="$(cat %s)"; print -r -- "[runner] prompt ${#p}자"; '
                     'claude -p "$p" --model opus --permission-mode acceptEdits'
                     % " ".join([write_head()] + PROMPT_FILES)],
                    stdout=lf, stderr=subprocess.STDOUT, timeout=TIMEOUT, cwd=str(ROOT), env=_env)
            # 판정은 마지막 attempt 구간만 읽는다 — 이전 시도의 마커·본문과 섞임 방지 (2026-08-02 리뷰)
            text = LOG.read_text(errors="ignore").split("=== attempt ")[-1]
            # 2026-08-02 리뷰(OPS-2): 이번 슬롯에서 새 mp4가 이미 나왔으면 렌더+발송을 마쳤을 수 있으므로
            # 재시도 금지(중복 게시 방지) — 아래 rc!=0 분기의 경보만 발송된다. 길이 가드는 보조로 유지.
            new_mp4_made = bool(fresh_mp4(start_ts))   # 경합 안전 (2026-08-25 재감사: 여기서 예외가 튀면 check_artifacts 자체가 안 돈다)
            evidence = sent_evidence(start_ts)   # 발송 실측 있으면 재시도 금지 — 중복 게시 봉쇄 (2026-08-05 점검)
            transient = (r.returncode != 0 and len(text.strip()) <= SAFE_RETRY_MAX_LEN
                         and not new_mp4_made and not evidence
                         and any(m.lower() in text.lower() for m in RETRY_MARKERS))
            # 2026-08-22 11:00 실사고: rc=0인데 인사말만 남기고 종료(즉사) — 마커가 없어 재시도를 안 탔다.
            # 산출물·발송·센티널이 전무한 초단문 종료는 장애로 간주해 재시도로 슬롯을 구한다.
            # 판정 코드로 분기 — 문안 결합 금지. SLOT-NOOP(의도된 무제작)는 재시도 무의미.
            # 2026-09-02 정정: DEAD_AUTH를 재시도에 포함한다. "인증 오류는 재시도해도 소용없다"는
            # 종전 전제가 실측과 어긋났다 — 인증 실패 2건(07-29 11:00, 08-28 07:00)은 로그아웃이
            # 아니라 토큰 갱신의 일시 실패였고, 뒤 슬롯(각 18:00, 09:00)은 손대지 않아도 정상 기동했다.
            # 갱신은 기동마다 새로 시도되므로 재시도가 슬롯을 구한다. 인증 즉사는 로그 ~280B라
            # 토큰 비용도 사실상 없다. 진짜 로그아웃이면 2회 더 실패한 뒤(+10분) 기존 경보로 빠진다.
            if not transient and r.returncode == 0 and not new_mp4_made and not evidence:
                _dead = log_looks_dead(text)
                if _dead and _dead[0] in (DEAD_SHORT, DEAD_AUTH) and "SLOT-NOOP" not in text:
                    transient = True
            if not transient or attempt >= len(RETRY_DELAYS):
                break
            delay = RETRY_DELAYS[attempt]
            # 원인을 문안에 실어 인증 만료(사용자 조치 필요)와 API 장애(대기하면 회복)를 가른다.
            _why = ("인증 토큰 갱신 실패" if any(m in text.lower() for m in AUTH_MARKERS)
                    else "일시적 API 장애")
            tg("🔁 %s: %s로 즉사 — %d분 후 재시도 (%d/%d)"
               % ("지식 카드" if CARD_MODE else "숏츠 데일리", _why,
                  delay // 60, attempt + 1, len(RETRY_DELAYS)))
            LOCK.write_text(str(os.getpid()))   # (mtime 스테일 판정은 폐지됨 — 잔재 재기록일 뿐, PID 동일. 2026-08-23)
            time.sleep(delay)

        if r.returncode != 0:
            # 2026-09-02: 종료코드만 알리면 원인이 안 보여 매번 로그를 열어야 했다.
            # 사용량 한도·인증 만료처럼 **코드 문제가 아닌 것**은 원인과 조치를 함께 띄운다.
            _cause = ""
            _low = text.lower()
            _m = re.search(r"out of (?:extra )?usage[^\n]*?resets ([0-9:apm ]+)", text, re.I)
            if _m:
                _cause = "\n원인: Claude 사용량 한도 소진 (복구 %s) — 코드 문제 아님, 다음 슬롯 자동 재개" % _m.group(1).strip()
            elif "out of extra usage" in _low or "usage limit" in _low:
                _cause = "\n원인: Claude 사용량 한도 소진 — 코드 문제 아님, 한도 복구 후 자동 재개"
            elif "authentication_error" in _low or "401" in text or "please run /login" in _low:
                _cause = "\n원인: Claude 인증 만료 — `claude` 로그인 필요(슬롯이 계속 증발한다)"
            elif "rate limit" in _low or "429" in text:
                _cause = "\n원인: API 레이트 리밋 — 잠시 후 자동 재개"
            tg("⚠️ 숏츠 데일리 세션 비정상 종료 (코드 %d, 재시도 %d회) — %s 확인%s"
               % (r.returncode, attempt, LOG.name, _cause))
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
        # 2026-08-24 실사고: 12시 조건부 슬롯이 "결번 처리 완료"로 정당하게 마감했는데 영문 마커가
        # 없어 '산출물 없음' 허위 경보 — v11.1의 조건부 결번은 정규 종료 형태라 한국어 표현도 인정한다.
        if any(k in logtext for k in ("게시 중단", "게시 보류", "SLOT-NOOP", "이미 제작·발송 완료",
                                      "결번 처리", "결번 확정", "결번으로 종료",
                                      "슬롯 결번")):   # 2026-09-06: CARD_PROMPT §5 결번 템플릿 첫 줄
            # 2026-08-23 4차 리뷰: 인증이 실제로 깨져 'SLOT-NOOP 인증 오류'로 규정대로 마감한 세션은
            # 여기서 조기 return되며 완전 무경보였다 — NOOP 사유에 인증 흔적이 있으면 경보는 남긴다.
            # (5차: 이전 attempt 잔재·단순 언급 오탐을 줄이려 마지막 attempt 구간만 스캔)
            _last = logtext.split("=== attempt ")[-1].lower()
            if any(m in _last for m in ("failed to authenticate", "authentication_error", "oauth access token")):
                tg("⚠️ 숏츠 데일리: 세션이 인증 오류 사유로 무제작 종료 의심 — 토큰 상태 확인 필요 (%s)" % LOG.name)
            return  # 의도된 미게시/무제작 — 세션이 사유를 보고했음
        gate_rejected = "기각" in logtext
        if CARD_MODE:
            # 카드 세션 산출물 판정 (2026-08-05): 캐러셀 게시 실측이 세션 시작 이후 기록됐는가
            # (2026-09-02: IGCARD/THCARD 양쪽 인정 — 카드가 인스타에서 빠졌다)
            sent = ROOT / "logs" / "sent.log"
            ok = sent.exists() and sent.stat().st_mtime >= start_ts and \
                any(("IGCARD:" in ln or "THCARD:" in ln)
                    for ln in sent.read_text(errors="ignore").strip().splitlines()[-5:])
            if not ok:
                tg("⚠️ 지식 카드: 세션은 정상 종료했지만 게시 실측(IGCARD/THCARD)이 없음%s — %s 확인"
                   % (" (로그에 기각 있음 — 자가수정 실패 가능)" if gate_rejected else "", LOG.name))
                return
            # 마감 리포트 필수 항목 (2026-09-07 신설): 게시는 됐는데 리포트가
            # "SLOT-DONE — 카드 게시 완료" 한 줄로 끝나는 일이 반복됐다(9/7 14:00).
            # 리포트가 없으면 중복 검사·팩트체크·가격 근거를 **실제로 했는지 확인할 길이 없다**
            # — 9/4 가격 사고가 그렇게 지나갔다. 게시는 끝났으니 차단이 아니라 경보다.
            _rep = logtext.split("=== attempt ")[-1]   # 이 분기에서 새로 뜬다 —
            # _last는 위 NOOP 분기 안에서만 정의돼 여기선 NameError가 난다(2026-09-07 검증에서 잡음)
            _need = [("소재", "소재"), ("스레드 URL", "threads.com/"),
                     ("팩트체크", "팩트체크"), ("중복 검사", "중복"), ("훅 채점", "훅 채점")]
            _miss = [n for n, k in _need if k not in _rep]
            if _miss:
                tg("⚠️ 지식 카드: 게시는 됐으나 마감 리포트에 %s 없음 — %s\n"
                   "  기록이 없으면 검증도 불가하다(CARD_PROMPT §5 마감 템플릿)"
                   % ("·".join(_miss), LOG.name))
            return
        new_mp4 = fresh_mp4(start_ts)
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
            # 2026-08-25 실사고: 19시 세션이 렌더·QA를 끝내고 "게시 지시를 기다립니다"로 멈췄다.
            # 경보는 정상 발송됐지만 **밤에는 아무도 안 본다** → 슬롯이 통째로 증발했다.
            # 경보만 보내는 대신 여기서 직접 게시를 끝낸다 — 산출물이 있고 게이트를 통과했다는 뜻이므로
            # 남은 건 업로더 호출뿐이다. 실패하면 그때 경보한다.
            note = " (로그엔 발송 문구가 있음 — 자기 보고 불일치)" if ("발송 완료" in logtext or "phase0" in logtext) else ""
            # 게이트가 기각한 편은 절대 자동 게시하지 않는다 — 산출물이 남아 있어도
            # 그건 '게시해도 되는 영상'이 아니다 (2026-08-25 감사: 게이트가 잡을수록 사고 나는 구조)
            if gate_rejected:
                tg("⚠️ 숏츠 데일리: 게이트가 기각한 편이라 자동 게시하지 않는다 — 세션이 자가수정에 "
                   "실패했으니 소재·배경을 고쳐 수동 재렌더가 필요하다 (%s)" % LOG.name)
                return
            newest = max(new_mp4, key=lambda p_: p_.stat().st_mtime)
            meta = ROOT / "content" / (newest.stem + ".meta.json")
            if meta.exists():
                tg("🔧 숏츠 데일리: 영상은 있는데 미게시 — 러너가 자동 게시를 시도합니다 (%s)" % newest.name)
                try:
                    r = subprocess.run(["/bin/zsh", "-l", "-c",
                                        "cd %s && .venv/bin/python3 pipeline/upload_youtube.py %s %s"
                                        % (ROOT, newest, meta)],
                                       capture_output=True, text=True, timeout=900)
                    tail = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()[-3:]
                    if r.returncode == 0:
                        tg("✅ 자동 게시 완료 (%s)\n%s" % (newest.name, "\n".join(tail)))
                    else:
                        tg("⚠️ 자동 게시 실패(rc=%d) — 수동 확인 필요 (%s)\n%s"
                           % (r.returncode, newest.name, "\n".join(tail)))
                except Exception as e:
                    tg("⚠️ 자동 게시 예외 — 수동 확인 필요 (%s): %s" % (newest.name, str(e)[:200]))
            else:
                tg("⚠️ 숏츠 데일리: 영상은 있는데 sent.log 발송 실측 기록이 없음%s — meta 파일도 없어 자동 게시 불가, %s 확인"
                   % (note, LOG.name))
    except Exception as e:
        # 이 함수는 슬롯 증발에 대한 마지막 방어선이다(산출물 실측·경보·자동 게시 구제).
        # 여기서 조용히 삼키면 경보도 구제도 사라지고 러너는 rc=0으로 끝난다 — 침묵은 목적과 정반대다.
        # (2026-08-25 감사: janitor의 -delete와 glob/stat이 경합해 FileNotFoundError가 날 수 있다)
        tg("⚠️ 숏츠 데일리: check_artifacts 자체 실패 — 산출물 검증이 수행되지 않았다 (%s): %s"
           % (LOG.name, str(e)[:200]))


def _venv_run(script, args=(), timeout=900):
    """블로그 계열 작업을 **.venv 파이썬**으로 돌린다 (2026-08-28 실사고).

    사고: launchd plist가 러너를 `/usr/bin/python3`(시스템 파이썬)로 띄운다. 영상·카드
      파이프라인은 내부에서 `.venv/bin/python3`를 따로 호출해 문제가 없었는데, 어제 붙인
      블로그 함수들은 **러너 프로세스 안에서 직접 import**해서 전부 죽었다:
        No module named 'googleapiclient' / 'boto3'
      게다가 except로 삼켜서 슬롯은 정상 완주로 보였고, 로그도 claude용 daily-*.log가 아니라
      launchd.out.log에만 남아 하루 동안 아무도 몰랐다.
    교훈: 러너 본체는 시스템 파이썬이다. **의존성이 필요한 코드는 반드시 .venv로 분리 실행한다.**
    """
    venv = ROOT / ".venv" / "bin" / "python3"
    if not venv.exists():
        print("[daily_runner] .venv 없음 — %s 건너뜀" % script, flush=True)
        return None
    try:
        r = subprocess.run([str(venv), str(ROOT / "pipeline" / script), *map(str, args)],
                           capture_output=True, text=True, timeout=timeout, cwd=str(ROOT))
        out = (r.stdout or "").strip()
        if out:
            print(out, flush=True)
        if r.returncode != 0:
            print("[daily_runner] %s rc=%d %s" % (script, r.returncode,
                                                 (r.stderr or "")[-300:]), flush=True)
        return r.returncode
    except Exception as e:
        print("[daily_runner] %s 실행 실패: %s" % (script, str(e)[:160]), flush=True)
        return None


def refresh_tech_calendar():
    """테크 예정 이벤트 캘린더 갱신 (2026-08-27 디렉터: "소재 선점하는게 젤 중요함!").

    소재 선정 **전에** 최신이어야 의미가 있으므로 main() 앞에서 돈다.
    실패해도 슬롯을 죽이지 않는다 — 캘린더가 낡아도 소재 선정은 진행돼야 한다.
    """
    _venv_run("tech_calendar.py", timeout=180)


def generate_blog_drafts():
    """새 테크 카드를 블로그 초안으로 만든다 (2026-08-27 디렉터: "매일 테크 카드는 쌓이는데").

    발행만 자동이고 생성이 수동이면 초안이 소진되는 순간 블로그가 멈춘다. 공급도 자동이어야
    구조가 스스로 돈다. 실측 공급은 카드 8.0장/일 중 테크 7.7편 — 발행 8편과 균형이 맞는다.
    슬롯마다 최대 3편만 만들어 Gemini 쿼터와 슬롯 시간을 보호한다.
    """
    _venv_run("blog_autogen.py", timeout=600)


def log_slot_metrics(start_ts):
    """슬롯 종료 시 계측 한 줄 (2026-08-27 토큰 패치).

    기존에는 렌더·게이트 횟수를 세션이 리포트에 쓸 때만 남아 슬롯마다 들쭉날쭉했다.
    전/후 비교를 하려면 **모든 슬롯이 같은 형식으로** 남겨야 한다.
    """
    try:
        import hashlib, re as _re
        ph = prompt_sha()
        t = LOG.read_text(errors="ignore")
        # render~/gate~ 카운트는 제거했다 (2026-08-28 감사): claude -p는 최종 응답만
        # 로그에 남겨 'make_short.py' 같은 패턴이 로그에 없다 — 항상 0으로 찍히는
        # 죽은 계측이었다. 산출물 존재(mp4)로 대체한다.
        _re_unused = _re  # (기존 임포트 유지)
        mp4 = "yes" if list(ROOT.glob("out/*.mp4")) else "no"
        print("[metrics] mode=%s prompt-sha=%s attempts=%d elapsed=%.1f분"
              % ("card" if CARD_MODE else "video", ph, t.count("=== attempt "),
                 (time.time() - start_ts) / 60), flush=True)
    except Exception as e:
        print("[metrics] 기록 실패: %s" % str(e)[:100], flush=True)


def publish_blog_slice():
    """블로그 초안을 하루 5편만 공개한다 (2026-08-27 디렉터: "하루 5편씩 발행").

    새 크론을 만들지 않고 여기 붙이는 이유: 러너는 슬롯마다 여러 번 도는데,
    publish_blog_daily가 날짜 스탬프로 하루 1회만 발행하므로 몇 번 불려도 안전하다.
    디렉터가 크론 개수 늘리는 것을 부담스러워한 점도 고려했다(2026-08-25 크론 전면 폐지).

    왜 나눠 올리나: 구글 scaled content abuse 정책 — 편집자 검토 없는 AI 대량 발행은
    2026년 3월 단속에서 트래픽 50~80% 하락을 불렀다. 초안은 검색에 안 잡히니 무해하고,
    조절할 것은 발행 속도뿐이다. 상세는 pipeline/publish_blog_daily.py 주석 참조.
    """
    # 2026-08-28 실사고: _venv_run은 **returncode**를 돌려준다. `if n == 0`으로 tg를 쐈더니
    # 스탬프로 건너뛴 슬롯(rc=0)에서도 매번 "발행 완료" 알림이 나가 하루 8번 오발송됐다.
    # 알림은 실제 발행 편수를 아는 쪽(publish_blog_daily 자신)이 보낸다 — 러너는 실행만 한다.
    _venv_run("publish_blog_daily.py", timeout=420)


if __name__ == "__main__":
    try:
        _t0 = time.time()
        refresh_tech_calendar()   # 소재 선정 전에 캘린더를 최신화한다
        main()
        log_slot_metrics(_t0)
        generate_blog_drafts()
        publish_blog_slice()
    except Exception as e:  # 러너 자체가 죽으면 경보자가 죽는 문제 방지 (2026-07-29 감사)
        tg("🔥 숏츠 데일리 러너 자체 오류: %s" % str(e)[:300])
        raise
