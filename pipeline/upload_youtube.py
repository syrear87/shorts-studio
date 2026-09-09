#!/usr/bin/env python3
# YouTube 업로더 어댑터. config.json의 upload_mode에 따라 동작.
#  - phase0_telegram: API 업로드 금지(미감사 프로젝트 = private 잠금) → 텔레그램으로 완성본 발송
#  - api_public: 감사 통과 후 videos.insert 공개 게시
# 사용: python3 pipeline/upload_youtube.py out/2026-07-29.mp4 content/2026-07-29.meta.json
import datetime, json, os, subprocess, sys  # 2026-08-02 리뷰: sent.log 기록용 datetime 추가

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)

# 디렉터 지정 포맷(2026-07-29): 제목엔 #shorts 금지, 태그는 채널 공통 태그 제외한 소재 태그만
COMMON_TAGS = {"지식", "상식", "1일1지식", "쇼츠"}

def clean_title(meta):
    return meta["title"].replace("#shorts", "").replace("#Shorts", "").strip()

def topic_tags(meta, limit=None):
    tags = [t for t in meta.get("tags", []) if t not in COMMON_TAGS]
    return tags[:limit] if limit else tags

def full_description(meta):
    # 2026-08-05 디렉터: 캡션에서 Pexels 크레딧 제거 — 출처 표기는 채널 정보란으로 이관
    # 2026-08-10 보강: 문구 변형('Pexels 제공 영상 사용')이 새어나간 실사고 — 'Pexels' 포함 줄 전체 제거
    # (기존 meta에 이미 박혀 있는 크레딧 줄은 여기서 걸러낸다)
    lines = [l for l in meta["description"].splitlines() if "Pexels" not in l and "pexels" not in l]
    return "\n".join(lines).strip()

def body_without_tags(meta):
    """설명 본문에서 해시태그 줄 제거 — 태그는 제목 줄이 담당 (2026-08-16 포맷 개정.
    2026-08-23 감사: phase0·api_public 중복 구현을 헬퍼로 통일 — 포맷 변경 시 한 곳만 고친다)."""
    return "\n".join(l for l in full_description(meta).splitlines()
                     if not l.strip().startswith("#"))

def check_meta(meta):
    """설명 규격 검증 (2026-08-01 실사고: 99자·해시태그 0개로 발송돼 '너무 빈약하다' 지적).

    ⚠️ meta를 제자리에서 수정할 수 있다 — 채널 공통 태그는 차단 대신 자동 제거한다(2026-08-27).
    """
    import re as _re0
    desc = meta.get("description", "")
    problems = []
    # 2026-08-02 리뷰 [A17]: 제목만 무검증이던 비대칭 해소 (retitle.py와 동일 기준)
    #                        — title 키 부재 시 clean_title의 무보고 KeyError도 여기서 차단
    title = meta.get("title", "").strip()
    if not (5 <= len(title) <= 100):
        problems.append("제목 %d자 (허용 5~100자)" % len(title))
    ct = clean_title(meta).strip() if title else ""
    if title and not (5 <= len(ct) <= 100):
        problems.append("정리 후 제목 %d자 ('#shorts' 제거 후에도 5~100자여야 함)" % len(ct))
    # 채널 공통 태그는 **차단하지 말고 자동으로 걷어낸다** (2026-08-27 개정).
    #   판단이 필요 없는 기계 작업인데 차단하면 세션이 재시도하느라 슬롯이 지연되고
    #   토큰을 쓴다. 실제로 8/22·8/25·8/27 세 번 반복돼 매번 재시도가 발생했다.
    #   제거하고 경고만 남긴다 — 8/9~10 실사고(3건 게시)는 '제거'로도 똑같이 막힌다.
    banned = [t for t in ("지식", "상식", "1일1지식", "쇼츠", "shorts")
              if ("#" + t) in desc or t in [x.replace(" ", "") for x in meta.get("tags", [])]]
    if banned:
        for _b in banned:
            desc = _re0.sub(r"#%s(?![가-힣A-Za-z0-9])" % _re0.escape(_b), "", desc)
        desc = _re0.sub(r"[ \t]{2,}", " ", desc)
        meta["description"] = desc
        meta["tags"] = [x for x in meta.get("tags", [])
                        if x.replace(" ", "") not in ("지식", "상식", "1일1지식", "쇼츠", "shorts")]
        print("채널 공통 태그 자동 제거: %s (게시는 계속)" % ", ".join(banned), flush=True)
        subprocess.run(["bash", os.path.join(ROOT, "bin", "tg-send.sh"),
                        "ℹ️ 채널 공통 태그 자동 제거 후 게시: %s — 대본 단계에서 넣지 않도록 주의"
                        % ", ".join(banned)], check=False)
    if "<" in title or ">" in title:
        problems.append("제목에 금지문자 <·> 포함")
    if desc.count("#") < 5:
        problems.append("해시태그 %d개 (5개 필요, 설명 맨 끝에)" % desc.count("#"))
    if len(desc) < 300:
        problems.append("설명 %d자 (최소 300자 — 영상에 못 넣은 정보를 채울 것)" % len(desc))
    if "·" not in desc:
        problems.append("핵심 사실 불릿(·) 없음")
    if "출처" not in desc:
        problems.append("출처 줄 없음")
    # 🔍 제목의 금액이 '한정어 없이' 홀로 서 있지 않은가 (2026-08-26 실사고 — 시청자 팩트 지적)
    #   수능 문항 편: 설명란은 "교사 2명에게 3년간 총 4억"으로 정확했는데 제목은
    #   "수학 문제를 4억에 샀는데"로 압축돼 **문제 1개 값**으로 읽혔다.
    #   ⚠️ 수치가 설명란에 '있는지'만 보면 이 사고는 안 잡힌다(4억은 양쪽에 다 있었다).
    #      설명란에서 그 금액 주변에 기간·인원 한정어가 붙어 있는데 제목엔 없을 때가 위험하다.
    import re as _re
    _dnorm, _tnorm = desc.replace(" ", ""), title.replace(" ", "")
    # 누적·기간·복수 대상을 뜻하는 한정어. 설명란이 이런 조건을 달고 있는데 제목엔 없으면,
    # 제목만 읽는 사람에겐 '단건 금액'으로 보인다 — 그게 이번 실사고다.
    _QUAL = r"(?:\d+\s*(?:년간|개월간|일간|주간|명|곳|차례)|\d+년\s*\d+월부터|총\s*\d|누적|합계|매년|해마다)"
    if _re.search(r"\d+(?:[.,]\d+)?\s*(?:억|만원|천만원|조)", title):
        _quals = _re.findall(_QUAL, _dnorm)
        if _quals and not _re.search(_QUAL, _tnorm):
            problems.append(
                "제목에 금액이 있는데 한정어가 없다 — 설명란은 '%s' 같은 누적·기간 조건을 달고 있다. "
                "제목만 보면 단건 금액으로 오해된다(2026-08-26 실사고: '수학 문제를 4억에 샀는데' → "
                "실제는 3년간 교사 여러 명 합계). 기간·인원·'총'을 제목에 넣어라"
                % "·".join(dict.fromkeys(_quals))[:40])
    if problems:
        subprocess.run(["bash", os.path.join(ROOT, "bin", "tg-send.sh"),
                        "⛔ 게시 차단(설명 규격): %s" % ", ".join(problems)], check=False)
        sys.exit("설명 규격 미달: " + ", ".join(problems))
    print("설명 규격 통과: %d자, 해시태그 %d개" % (len(desc), desc.count("#")))


def preflight(video):
    """게시 전 기계 검증 — QA 자기채점 보완 (2026-07-29 감사: 코드 게이트 0개 지적)."""
    # 2026-08-02 리뷰 [A17]: 게이트 오류(ffprobe 실패·경로 오타)가 무보고 traceback으로
    #                        죽던 것을 ⛔ 보고 후 종료로 — 게이트 실패와 동일한 가시성 확보
    try:
        out = subprocess.run(["ffprobe", "-v", "quiet", "-show_entries", "format=duration:stream=width,height",
                              "-of", "json", video], capture_output=True, text=True)
        if out.returncode != 0:
            raise RuntimeError("ffprobe rc=%d: %s" % (out.returncode, (out.stderr or "").strip()[:200]))
        info = json.loads(out.stdout)
        dur = float(info["format"]["duration"])
        streams = [s for s in info.get("streams", []) if s.get("width")]
        w, h = (streams[0]["width"], streams[0]["height"]) if streams else (0, 0)
    except Exception as e:
        subprocess.run(["bash", os.path.join(ROOT, "bin", "tg-send.sh"),
                        "⛔ preflight 검사 불능: %s" % str(e)[:300]], check=False)
        sys.exit("preflight 검사 불능: %s" % e)
    problems = []
    if not (20 <= dur <= 55):   # 2026-08-02 디렉터 확정: 렌더러 게이트와 동일 수치로 통일
        problems.append("길이 %.1fs (허용 20~55s)" % dur)
    if (w, h) != (1080, 1920):
        problems.append("해상도 %dx%d (요구 1080x1920)" % (w, h))
    if problems:
        subprocess.run(["bash", os.path.join(ROOT, "bin", "tg-send.sh"),
                        "⛔ 게시 차단(preflight): %s — %s" % (os.path.basename(video), ", ".join(problems))], check=False)
        sys.exit("preflight 실패: " + ", ".join(problems))
    print("preflight 통과: %.1fs, %dx%d" % (dur, w, h))


def phase0(video, meta):
    # 0) 인스타 릴스 자동 게시 (2026-08-05 디렉터 승인 — 오디세이 편으로 실전 검증 완료)
    #    실패해도 슬롯을 죽이지 않는다: 경고 + 기존 수동 안내로 폴백
    ig_ok = False
    try:
        import upload_instagram
        # "already-published"(멱등 가드)는 성공이 아니다 — 2026-08-17 허위 보고 실사고 재현 조건
        _r = upload_instagram.upload(video, meta)
        ig_ok = bool(_r) and _r != "already-published"
    except Exception as e:
        subprocess.run(["bash", os.path.join(ROOT, "bin", "tg-send.sh"),
                        "⚠️ 인스타 자동 게시 실패(%s) — 아래 영상을 수동 업로드해주세요" % str(e)[:200]],
                       timeout=90)
    # 1) 영상 파일 텔레그램 발송 — 캡션 없이 영상만 (2026-08-05 디렉터: 안내 문구 전부 제거)
    size_mb = os.path.getsize(video) / 1e6
    # 2026-08-02 리뷰 [A1]: 네트워크 스톨 시 러너 100분 타임아웃까지 슬롯이 통째로 잠기는 것 방지
    if size_mb < 49:
        subprocess.run(["bash", os.path.join(ROOT, "bin", "tg-send-video.sh"), video, ""],
                       check=True, timeout=360)
    else:
        subprocess.run(["bash", os.path.join(ROOT, "bin", "tg-send.sh"),
                        "⚠️ 영상이 %dMB로 텔레그램 한도 초과 — 파일: %s" % (size_mb, os.path.abspath(video))],
                       check=True, timeout=90)
    # 2) 유튜브 설명란: 머리말 없이 '제목(#Shorts 없음)+본문+태그 줄' (2026-08-05 디렉터 포맷 확정)
    # 2026-08-16 디렉터 포맷 개정: 해시태그는 제목 줄 끝에, 하단 '태그:' 줄은 폐지 — 인스타 캡션과 동형
    _tags = " ".join("#" + t.lstrip("#") for t in topic_tags(meta))
    # 본문 맨 아래 해시태그 줄은 지운다 — 제목 줄로 이미 올렸으니 중복이다
    # (2026-08-16 디렉터: "제목에 태그 이미 있으니까 마지막에 태그는 안 써도 된다고요")
    _body = body_without_tags(meta).rstrip()
    msg = "%s %s\n\n%s" % (clean_title(meta), _tags, _body)
    subprocess.run(["bash", os.path.join(ROOT, "bin", "tg-send.sh"), msg], check=True, timeout=90)
    # IG 캡션 별도 메시지는 폐지 (2026-08-05 디렉터: 실패 시에도 경고 한 줄이면 충분 —
    # 유튜브용으로 발송된 영상+캡션으로 수동 업로드 가능)
    print("phase0: IG 자동 게시=%s, 텔레그램 발송 완료" % ("성공" if ig_ok else "실패(경고 발송)"))

def _fit_tags(tags):
    """YT snippet.tags 총량 ~500자 제한(공백 포함 태그는 따옴표까지 계산) — 초과분은 뒤에서 잘라낸다."""
    out, total = [], 0
    for t in tags:
        cost = len(t) + (2 if " " in t else 0) + 1
        if total + cost > 450:
            break
        out.append(t)
        total += cost
    return out


def _title_with_tags(title, tags, limit=100):
    """제목 뒤에 해시태그를 붙이되 100자를 넘기지 않는다. 넘치면 태그를 뒤에서 하나씩 뺀다."""
    tags = [("#" + t.lstrip("#")) for t in tags]
    while tags:
        cand = "%s %s" % (title, " ".join(tags))
        if len(cand) <= limit:
            return cand
        tags.pop()
    return title[:limit]


def hook_full_ms(video, scan_s=5.0, fps=5):
    """훅 자막이 **다 뜬** 시점(ms)을 찾는다 (2026-08-17 디렉터: "훅 자막 다 나온 장면으로 셋팅").
    수동으로 정한 ig_thumb_ms는 편마다 어긋났다 — 장마 편(700ms)은 첫 줄만 떠 있었다.
    방법: 앞 5초를 훑어 중앙 자막 밴드(세로 35~72%)의 흰 픽셀이 최대인 시점을 고른다.
    두 줄이 다 뜬 순간이 흰 픽셀이 가장 많다. 동률이면 이른 쪽(자막이 사라지기 전)."""
    import subprocess, tempfile, os as _os
    from PIL import Image
    tmp = tempfile.mkdtemp(prefix="hookscan_")
    try:
        subprocess.run(["ffmpeg", "-y", "-t", "%.2f" % scan_s, "-i", video,
                        "-vf", "fps=%d,scale=270:480" % fps, "-loglevel", "error",
                        _os.path.join(tmp, "f%03d.jpg")], check=True)
        best_ms, best_ink = None, -1
        for fn in sorted(_os.listdir(tmp)):
            if not fn.startswith("f"):
                continue
            n = int(fn[1:4])
            g = Image.open(_os.path.join(tmp, fn)).convert("L")
            band = g.crop((0, int(480 * 0.35), 270, int(480 * 0.72)))
            ink = sum(1 for v in band.getdata() if v >= 225)
            if ink > best_ink:
                best_ms, best_ink = int((n - 1) * 1000 / fps), ink
        return best_ms if best_ms is not None else 1000
    finally:
        import shutil as _sh
        _sh.rmtree(tmp, ignore_errors=True)   # 2026-08-23 감사: hookscan_* 고아 디렉터리 9개 잔존 실측


def wait_processed(yt, vid, timeout=180, interval=30):
    """유튜브가 영상 처리를 마칠 때까지 기다린다 (2026-08-28 실사고).

    사고: 업로드 **직후** 썸네일을 설정하면 API가 200을 돌려주지만 **실제로는 적용되지 않는다.**
      영상이 아직 processing 상태라 무시되는데, 에러가 아니라서 로그에는 "미리보기 설정 완료"가
      남는다 — 그래서 실패 기록이 하나도 없었는데 썸네일만 비어 있었다.
      디렉터 실측: "시골 돈주는거랑 AI사주 썸네일 없어서 사주만 내가 썸네일 지정해놓음".
      같은 코드로 처리 완료 뒤에 부르면 즉시 성공한다(당일 재현 확인).

    타임아웃이면 그냥 진행한다 — 기다리다 슬롯을 죽이는 것보다 낫고, 최악이어도 종전과 같다.

    간격을 10초→30초로 늘렸다 (2026-09-10): 유튜브 쿼터가 '호출 횟수' 기준 하루 100회로
    바뀌어 이 폴링만 최대 18회를 먹었다. 30초면 최대 6회이고, 실측 처리 시간은 대개
    한두 번 안에 끝나므로 체감 차이가 없다.
    """
    import time as _t
    for _ in range(max(1, timeout // interval)):
        try:
            r = yt.videos().list(part="status,processingDetails", id=vid).execute()
            items = r.get("items") or []
            if items:
                st = (items[0].get("status") or {}).get("uploadStatus")
                pr = (items[0].get("processingDetails") or {}).get("processingStatus")
                if st == "processed" or pr == "succeeded":
                    return True
        except Exception:
            pass
        _t.sleep(interval)
    print("[thumb] 처리 완료 대기 타임아웃 — 그대로 진행", flush=True)
    return False


def set_thumbnail(yt, vid, video, meta):
    """훅 자막이 다 뜬 프레임을 유튜브 미리보기로 올린다.
    시점은 자동 탐색(hook_full_ms)하고, meta에 ig_thumb_ms가 있으면 그것을 우선한다 —
    디렉터가 특정 시점을 지정한 편은 그 뜻을 존중한다.
    실패해도 게시는 유지한다(커스텀 미리보기는 채널 인증이 필요할 수 있다).

    **처리 완료를 먼저 기다린다** — 처리 중에 설정하면 조용히 무시된다(wait_processed 주석)."""
    import subprocess, tempfile, os as _os
    wait_processed(yt, vid)
    ms = int(meta["ig_thumb_ms"]) if meta.get("ig_thumb_ms") else hook_full_ms(video)
    tmp_dir = tempfile.mkdtemp(prefix="ytthumb_")
    try:
        tmp = _os.path.join(tmp_dir, "thumb.jpg")
        subprocess.run(["ffmpeg", "-y", "-ss", "%.2f" % (ms / 1000.0), "-i", video,
                        "-frames:v", "1", "-q:v", "2", "-loglevel", "error", tmp], check=True)
        from googleapiclient.http import MediaFileUpload
        yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(tmp, mimetype="image/jpeg")).execute()
        # 되읽기 검증은 제거했다 (2026-08-28 감사): HD 업로드는 **자동 생성 썸네일에도
        # maxres·standard 키가 항상 있어서** "maxres 없음 → 재시도" 판정이 절대 발화하지
        # 않는 죽은 코드였다. 실효 대책은 위의 wait_processed(처리 완료 후 설정)뿐이다 —
        # API가 커스텀/자동 여부를 구분해 주지 않으므로 되읽기로는 확인할 수 없다.
        print("미리보기 설정 완료 (%dms 지점)" % ms, flush=True)
    finally:
        import shutil as _sh
        _sh.rmtree(tmp_dir, ignore_errors=True)   # 2026-08-23 감사: ytthumb_* 고아 디렉터리 26개 잔존 실측


def api_public(video, meta):
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    from google_creds import load_creds
    # 2026-08-02 리뷰 [A13]: 토큰 로드→refresh→원자 저장(chmod 600) 공용 헬퍼로 통일
    creds = load_creds()
    yt = build("youtube", "v3", credentials=creds)
    # 디렉터 지정 매핑(2026-07-29): 제목=#shorts 없는 제목 / 설명=제목+본문 / 태그=소재 태그 5개
    #                             / 아동용 아님 / 공개
    title = clean_title(meta)
    _want = _title_with_tags(title, topic_tags(meta))   # 아래 body와 멱등 가드가 함께 쓴다
    body = {
        "snippet": {
            # 제목 = 본제목 + 해시태그 5개 (유튜브 제목 상한 100자 — 넘치면 태그부터 잘라낸다)
            "title": _want,
            # 2026-08-17 디렉터: "캡션과 제목을 분리한다" —
            #   제목 줄(+해시태그)은 title 필드가 이미 담당하므로 설명에 반복하지 않는다.
            #   설명에는 본문만 넣고, 본문 하단의 해시태그 줄도 제거한다(제목에 이미 있다).
            "description": body_without_tags(meta).strip()[:4900],
            "tags": _fit_tags(topic_tags(meta, 5)),
            "categoryId": "27",  # 교육
            "defaultLanguage": "ko",
        },
        "status": {
            "privacyStatus": meta.get("privacy", "public"),   # 기본 "공개"
            "selfDeclaredMadeForKids": False,                 # "아니요, 아동용이 아닙니다"
        },
    }
    # 🛡️ 멱등 가드 (2026-08-25 신설) — IG에는 있는데 YT에만 없었다.
    #   업로드 순서가 [YT 업로드 → 썸네일 → sent.log 기록]이라, 그 사이에 세션이 죽으면
    #   러너의 자동 게시(check_artifacts)가 같은 영상을 두 번 올린다. 최근 업로드 제목과 대조해 막는다.
    #   의도적 재게시가 필요하면 환경변수 YT_FORCE=1 로 우회한다(오늘 추석 편 같은 배경 교체 재게시).
    if not os.environ.get("YT_FORCE"):
        try:
            _ch = yt.channels().list(part="contentDetails", mine=True).execute()["items"][0]
            _up = _ch["contentDetails"]["relatedPlaylists"]["uploads"]
            _recent = yt.playlistItems().list(part="snippet", playlistId=_up, maxResults=10).execute()
            for _it in _recent.get("items", []):
                if _it["snippet"]["title"].strip() == _want.strip():
                    _vid = _it["snippet"]["resourceId"]["videoId"]
                    print("이미 게시됨(같은 제목) — 건너뜀: https://youtube.com/shorts/%s" % _vid, flush=True)
                    # sent.log를 남기지 않으면 러너 check_artifacts가 계속 '미게시'로 읽어
                    # 자동 복구가 매 슬롯 uploader를 재호출한다 (2026-08-25 감사)
                    os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)
                    with open(os.path.join(ROOT, "logs", "sent.log"), "a", encoding="utf-8") as _sf:
                        _sf.write("%s %s\n" % (datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                                                os.path.basename(video)))
                    return _vid
        except Exception as _ge:
            # 멱등 가드가 꺼진 채 업로드하면 러너 자동 복구와 겹쳐 같은 영상이 2회 공개 게시된다.
            # 가드의 목적상 fail-CLOSED가 맞다 — 중단하고 알린다 (2026-08-25 재감사).
            subprocess.run(["bash", os.path.join(ROOT, "bin", "tg-send.sh"),
                            "⛔ 유튜브 중복 검사 실패로 업로드 중단(중복 게시 방지): %s" % str(_ge)[:150]],
                           check=False)
            sys.exit("중복 검사 실패 — 업로드 중단: %s" % str(_ge)[:150])

    media = MediaFileUpload(video, chunksize=8 * 1024 * 1024, resumable=True, mimetype="video/mp4")
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    resp = None
    while resp is None:
        # 2026-08-02 리뷰 [A10]: 일시 5xx로 청크 하나가 죽으면 업로드 전체가 즉사하던 것
        #                        — googleapiclient 지수 백오프 재시도 위임
        status, resp = req.next_chunk(num_retries=5)
        if status:
            print("업로드 %d%%" % int(status.progress() * 100), flush=True)
    vid = resp["id"]
    url = "https://youtube.com/shorts/" + vid
    print("업로드 완료:", url)
    try:
        set_thumbnail(yt, vid, video, meta)
    except Exception as _te:
        print("미리보기 설정 실패(게시는 정상):", str(_te)[:200], flush=True)
    # 2026-08-02 리뷰 [A6]: 게시 실증 기록 — 러너 check_artifacts가 sent.log로 발송을 검증
    #                       (형식 고정: date +%FT%T + 공백 + basename, tg-send-video.sh와 동일)
    os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)
    with open(os.path.join(ROOT, "logs", "sent.log"), "a", encoding="utf-8") as f:
        f.write("%s %s\n" % (datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                             os.path.basename(video)))
    subprocess.run(["bash", os.path.join(ROOT, "bin", "tg-send.sh"),
                    "✅ 오늘의 숏츠 게시 완료\n%s\n%s" % (title, url)], check=False)
    return vid

def main():
    if len(sys.argv) < 3:
        sys.exit("사용: upload_youtube.py <video.mp4> <meta.json>")
    video, meta_p = sys.argv[1], sys.argv[2]
    meta = load(meta_p)
    check_meta(meta)
    preflight(video)
    cfg = load(os.path.join(ROOT, "config.json"))
    mode = cfg.get("upload_mode", "phase0_telegram")
    if mode == "api_public":
        # 2026-08-02 리뷰 [A10]: 업로드 실패가 ⛔ 보고 없이 traceback 종료되던 비대칭 해소
        #                        — 인스타 경로(아래)와 동일 패턴
        try:
            api_public(video, meta)
        except Exception as e:
            subprocess.run(["bash", os.path.join(ROOT, "bin", "tg-send.sh"),
                            "⛔ 유튜브 업로드 실패: %s" % str(e)[:300]], check=False)
            raise
    else:
        phase0(video, meta)
    # 인스타 릴스: 디렉터 결정(2026-07-29) — phase0 기간엔 인간 검수를 우회하므로 끔.
    # 유튜브 감사 통과로 api_public 전환 시에만 함께 자동 게시.
    if cfg.get("instagram") == "on" and mode == "api_public":
        try:
            import upload_instagram
            upload_instagram.upload(video, meta)
        except Exception as e:
            print("릴스 업로드 실패: %s" % e)
            subprocess.run(["bash", os.path.join(ROOT, "bin", "tg-send.sh"),
                            "⚠️ 인스타 릴스 자동 업로드 실패 — 수동 업로드 필요\n%s" % str(e)[:300]], check=False)

if __name__ == "__main__":
    main()
