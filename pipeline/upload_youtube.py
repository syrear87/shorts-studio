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

def check_meta(meta):
    """설명 규격 검증 (2026-08-01 실사고: 99자·해시태그 0개로 발송돼 '너무 빈약하다' 지적)."""
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
    banned = [t for t in ("지식", "상식", "1일1지식", "쇼츠", "shorts")
              if ("#" + t) in desc or t in [x.replace(" ", "") for x in meta.get("tags", [])]]
    if banned:
        problems.append("채널 공통 태그 금지 위반: %s (DAILY_PROMPT 규칙 — 8/9~10 위반 3건 게시 실사고)" % ", ".join(banned))
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
        ig_ok = bool(upload_instagram.upload(video, meta))
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
    msg = "%s %s\n\n%s" % (clean_title(meta), _tags, full_description(meta))
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
    body = {
        "snippet": {
            "title": title[:100],
            "description": ("%s\n\n%s" % (title, full_description(meta)))[:4900],
            "tags": _fit_tags(topic_tags(meta, 5)),
            "categoryId": "27",  # 교육
            "defaultLanguage": "ko",
        },
        "status": {
            "privacyStatus": meta.get("privacy", "public"),   # 기본 "공개"
            "selfDeclaredMadeForKids": False,                 # "아니요, 아동용이 아닙니다"
        },
    }
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
