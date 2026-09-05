#!/usr/bin/env python3
# 인스타그램 릴스 자동 업로더 (Instagram API with Instagram Login).
#  - keys.env에 IG_ACCESS_TOKEN, IG_USER_ID 필요 (본인 프로페셔널 계정, 앱 심사 불필요)
#  - 흐름: R2 공개 URL 업로드 → 컨테이너 생성(video_url) → 상태 폴링 → 게시 (이 계정은 rupload 거부 — R2 경유가 정본)
#  - 캡션 = 제목 + 본문 (유튜브 설명과 동일 포맷, 디렉터 지정 2026-07-29)
#  - 장기 토큰(60일)은 마지막 갱신 7일 경과 시 자동 갱신해 keys.env를 업데이트
# 사용: python3 pipeline/upload_instagram.py out/영상.mp4 content/영상.meta.json
import json
import re, os, subprocess, sys, time  # 2026-08-02 리뷰 [A18]: 미사용 re 제거
import urllib.request, urllib.parse, urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEYS = os.path.join(ROOT, "keys.env")
STATE = os.path.join(ROOT, "logs", ".ig_token_refreshed")   # 새 토큰 투입 시 touch logs/.ig_token_refreshed 병행 (2026-08-02 리뷰 [A18])
GRAPH = "https://graph.instagram.com/v23.0"

# ── 플랫폼 분리 편성 (2026-08-29 디렉터 지시) ─────────────────────────────
#   "차라리 스레드는 영상 안 올리고 카드만 가고, 인스타/유튭은 영상만 가고 어때"
#
# 실측이 정확히 이 방향이다:
#   스레드(8/24~ 각 30건) — 카드 평균 1,252회·반응 156  vs  영상 평균 498회·반응 37
#                            → 카드가 조회 2.5배·반응 4.2배
#   인스타(8/29)         — 릴스 중앙값 161회  vs  카드 중앙값 74회 → 릴스가 2.2배
# 두 플랫폼의 선호가 정반대라, 각자 잘 받는 것만 보낸다. 부수 효과로 게시 빈도가
# 양쪽 다 하루 12편 → 6편으로 절반이 되어, 인스타 도달 급락(8/25 706 → 8/29 161)의
# 유력 원인인 과다 게시도 함께 걷힌다.
#
# 되돌리려면 이 두 값만 True로 바꾸면 된다.
# ── 쿠팡 파트너스 매체 등록 게이트 (2026-09-05) ─────────────────────────
# 파트너스 규정: **등록하지 않은 채널에서의 광고활동은 부정행위**이며 수익금 지급 중단·
# 임의탈퇴 대상이다. 현재 활동매체 등록은 YouTube(@daily1know)·Instagram(syusyu_channel)
# 2건뿐이고(DECISIONS.md S-007), 카드가 나가는 **스레드(@daily_1_pick)와 블로그
# (daily1pick.blogspot.com)는 미등록**이다. 등록 전까지 스레드 자동 부착을 멈춘다.
# 디렉터가 앱에서 직접 다는 것도 같은 규정을 받으므로, 등록이 먼저다.
# 2026-09-05 디렉터가 파트너스 활동매체에 스레드·블로그를 등록 완료 → 게이트 해제.
AFFILIATE_MEDIA_REGISTERED = True

VIDEO_TO_THREADS = False   # 영상을 스레드에도 올릴 것인가 (현재: 인스타·유튜브 전용)
CARD_TO_IG = False         # 카드를 인스타에도 올릴 것인가
# 2026-09-02 최종 (디렉터: "빼라고 그러니깐"):
#   8/30에 메타 보너스(사진·슬라이드 조회만 집계) 때문에 카드를 인스타로 되돌렸으나,
#   실측 결과 그 근거가 무너졌다 — 카드 인스타 중앙값 113회 × 5장 × 30일 = 월 16,950회로
#   보너스 요건(월 100만 회)의 **1.7%**다. 60배가 모자라 도달 가능성이 없다.
#   게다가 9/2 두 축 전략에서 카드 축은 '스레드 + 블로그'라 인스타가 애초에 없었다.
#   반응 낮은 게시물(릴스 213회의 절반)이 하루 5개씩 쌓이는 계정 부담도 덜어낸다.
   # 버전 고정 — 무버전 호출은 Meta 버전 폐기 시 무예고 파손 (2026-08-02 리뷰 [A18])
REFRESH_AFTER = 7 * 86400          # 7일마다 토큰 갱신
MAX_THREADS = 500                  # 스레드 본문 상한 (2026-08-16)
POLL_INTERVAL, POLL_MAX = 10, 30   # 처리 대기 최대 5분


def load_keys():
    kv = {}
    if os.path.exists(KEYS):
        for line in open(KEYS, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                kv[k.strip()] = v.strip()
    return kv


def tg(msg):
    try:
        subprocess.run(["bash", os.path.join(ROOT, "bin", "tg-send.sh"), msg], timeout=30)
    except Exception:
        pass


def api(method, path, params=None, data=None):
    # DRY_RUN=1 이면 쓰기(POST/DELETE)를 실제로 보내지 않는다 (2026-09-05 — threads 쪽과 동일한 안전선)
    if method.upper() != "GET" and os.environ.get("DRY_RUN") in ("1", "true", "True"):
        print("[ig][DRY_RUN] %s %s" % (method, path), flush=True)
        return {"id": "dryrun", "status_code": "FINISHED", "permalink": "dryrun"}
    url = GRAPH + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    body = None
    if data is not None:
        body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, method=method, headers={})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError("IG API %s %s → %d: %s" % (method, path, e.code, e.read().decode()[:500]))


def refresh_token_if_due(token):
    try:
        age = time.time() - os.path.getmtime(STATE)
    except OSError:
        age = REFRESH_AFTER + 1
    if age < REFRESH_AFTER:
        return token
    try:
        resp = api("GET", "/refresh_access_token",
                   params={"grant_type": "ig_refresh_token", "access_token": token})
        new = resp.get("access_token")
        if new and new != token:
            from keyfile import locked
            # ⚠️ with로 감싼다 — 수동 __enter__/__exit__은 중간에 예외가 나면 __exit__이
            #    호출되지 않아 같은 프로세스의 이후 갱신이 자기 락에 막힌다 (2026-08-25 자체 점검).
            with locked():   # 읽기~교체 전체를 직렬화 (스레드 토큰 갱신과의 lost update 경쟁)
                # 원자적 재작성 (임시파일→rename) + re.sub 이스케이프 함정 회피 (2026-07-29 감사)
                lines = open(KEYS, encoding="utf-8").read().splitlines(keepends=True)
                out_lines, replaced = [], False
                for line in lines:
                    if line.strip().startswith("IG_ACCESS_TOKEN="):
                        out_lines.append("IG_ACCESS_TOKEN=%s\n" % new)
                        replaced = True
                    else:
                        out_lines.append(line)
                if not replaced:
                    out_lines.append("IG_ACCESS_TOKEN=%s\n" % new)
                tmp = KEYS + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    f.write("".join(out_lines))
                os.chmod(tmp, 0o600)   # 2026-08-14 감사: umask 기본값이면 장기 토큰이 644로 노출된다
                os.replace(tmp, KEYS)
            token = new
        if not new:
            # ⚠️ 200인데 access_token이 없는 응답 — 갱신은 안 됐다. 여기서 스탬프를 찍으면
            #    ①7일 게이트가 닫히고 ②age_days 경보는 매주 나이가 리셋돼 **영원히 안 울린다**.
            #    60일 만료일에 릴스·캐러셀·댓글DM이 동시에 죽는다 (2026-08-25 재감사).
            #    스탬프를 남기지 않아 다음 호출이 즉시 재시도하게 한다.
            print("IG 토큰 갱신 응답에 access_token 없음 — 스탬프 미기록, 다음 호출에 재시도: %s"
                  % json.dumps(resp)[:200])
            return token
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        with open(STATE, "w") as _sf:   # flush 보장 (2026-08-25 자체 점검)
            _sf.write(str(int(time.time())))
        print("IG 토큰 갱신 완료 (유효기간 %d일)" % (resp.get("expires_in", 0) // 86400))
    except Exception as e:
        print("IG 토큰 갱신 실패(기존 토큰으로 계속): %s" % e)
        try:
            age_days = (time.time() - os.path.getmtime(STATE)) / 86400
        except OSError:
            # 2026-08-02 리뷰 [A18]: STATE 부재(첫 가동 — IG는 발급 24h 미만 토큰 갱신 거부)와
            #                        '장기 연속 실패'를 구분 — 999일 가짜 경보 방지
            age_days = None
        if age_days is not None and age_days > 40:   # 60일 만료 임박인데 갱신이 계속 실패 → 무증상 방지 경보
            tg("⚠️ 인스타 토큰 갱신이 %d일째 실패 중 — 60일 만료 전에 재발급 필요" % int(age_days))
    return token


def build_caption(meta):
    """캡션 = [제목 + 해시태그] 한 줄 → 빈 줄 → 본문(출처까지).
    2026-08-16 디렉터 포맷 개정: 해시태그를 **제목 줄 끝**에 붙이고, 본문 하단의
    해시태그 줄과 '태그: ...' 줄은 지운다 — 피드에서 첫 줄만 보이므로 태그도 함께 노출된다.
    Pexels 크레딧은 계속 제거(채널 정보란으로 이관, 2026-08-05)."""
    title = meta["title"].replace("#shorts", "").replace("#Shorts", "").strip()
    body, tagline = [], ""
    for l in meta["description"].splitlines():
        t = l.strip()
        if t.startswith("태그:") or "Pexels" in l or "pexels" in l:
            continue
        if t.startswith("#"):
            tagline = t          # 본문 하단 해시태그 줄 → 제목 뒤로 이동
            continue
        body.append(l)
    if not tagline and meta.get("tags"):
        tagline = " ".join("#" + t.lstrip("#") for t in meta["tags"])
    head = ("%s %s" % (title, tagline)).strip()
    return ("%s\n\n%s" % (head, "\n".join(body).strip()))[:2200]


def _strip_tags(line):
    """줄 끝의 해시태그 묶음을 떼어낸다 — 훅 문장만 남긴다.
    #1 같은 순수 숫자 표기는 순위이지 태그가 아니므로 남긴다 (2026-08-28 감사)."""
    return re.sub(r"(\s*#(?![0-9]+(?:\s|$))[^\s#]+)+\s*$", "", line or "").strip()


def _caption_for_threads(caption):
    """IG 캡션을 스레드 폴백 본문으로 쓸 때 해시태그를 걷어낸다 (2026-08-28 감사).

    해시태그 제거 규칙이 native_threads_text에만 있고 폴백 두 곳(threads_parts의 head,
    카드의 `or caption`)에는 없어서, threads_text가 없는 편은 태그가 그대로 스레드에 나갔다
    — 실측: 08-28-am.meta.json이 threads_text 없이 실재해 잠복이 아니라 현행 구멍이었다."""
    lines = []
    for l in (caption or "").split("\n"):
        t = l.strip()
        if t.startswith("#"):        # 태그 전용 줄은 통째로 제거
            continue
        lines.append(_strip_tags(l) if "#" in l else l)
    return "\n".join(lines).strip()


def native_threads_text(threads_text, caption):
    """스레드 전용 본문 가드 (2026-08-23 성장 연구 — 뉴스체 캡션 복제 대신 1인칭 현지화 본문 사용).
    단 **첫 줄(훅)은 IG 캡션 첫 줄과 동일**해야 한다 — 제휴봇(find_recent_post)이 캡션 첫 줄로
    스레드 글을 되찾아 쿠팡 링크를 달기 때문. 다르면 캡션 훅을 첫 줄로 강제 삽입한다.

    **해시태그는 스레드 본문에 넣지 않는다 (2026-08-28 실측 A/B)**: build_caption이 제목 뒤에
    해시태그를 붙이는데(IG 피드는 첫 줄만 보여 태그도 함께 노출되므로 맞는 설계다),
    그 줄이 그대로 스레드 훅으로 딸려 들어갔다. 실측 —
      태그 0개 36건 평균 1,069회 · 태그 4개 22건 502회 · 태그 5개 2건 291회
      영상만 비교해도 태그 없는 1건 1,481회 vs 태그 붙은 24건 484회(3배)
    스레드는 인스타와 달리 해시태그 문화가 약하고, 태그가 붙으면 유통이 눌리는 것으로 보인다.
    표본이 작아 단정은 못 하므로 **되돌리기 쉬운 형태로 적용하고 며칠 뒤 재측정한다.**
    (제휴봇 매칭은 캡션 첫 줄의 앞부분으로 하므로 태그를 떼도 훅 문장은 그대로 남는다.)"""
    if not threads_text:
        return None
    hook = _strip_tags((caption or "").split("\n")[0])
    first = _strip_tags(threads_text.split("\n")[0])
    if hook and first != hook:
        return hook + "\n\n" + threads_text
    return threads_text


def threads_parts(meta):
    """스레드 본문 (2026-08-16 디렉터 확정): 첫 글 = 제목 + 내용(출처 제외),
    답글 = 쿠팡 링크. **쿠팡 링크가 없으면 답글을 달지 않는다.**
    스레드 상한 500자라 넘치면 블록 단위로 잘라낸다(잘랐음을 숨기지 않고 '…'로 표시).
    쿠팡 링크에는 대가성 문구가 법적 의무이므로 항상 같은 글에 붙인다."""
    blocks = [b.strip() for b in _caption_for_threads(build_caption(meta)).split("\n\n") if b.strip()]
    keep = [b for b in blocks
            if not b.startswith("출처") and not b.lstrip().startswith("•")]
    head = ""
    for b in keep:
        cand = (head + "\n\n" + b) if head else b
        if len(cand) > MAX_THREADS:
            break
        head = cand
    if not head:                      # 제목 한 줄도 넘치는 예외
        head = keep[0][:MAX_THREADS - 1] + "…" if keep else ""
    # 링크는 본문 말미가 원칙 — 답글은 거의 읽히지 않는다 (with_affiliate 주석)
    head, replies = with_affiliate(head, meta)
    return head, replies


from disclosure import DISCLOSURE as DISCLOSURE_TEXT   # 법정 고지 문구 단일 정본 (2026-08-25)


def affiliate_for(meta, text=None):
    """이 편과 짝이 되는 쿠팡 상품 (링크, 이름). 없으면 (None, None).

    2026-08-27: 후보를 `last_product`(가장 최근 회신 1건)에서 **확보한 링크 풀 전체**로
      넓혔다. 실측에서 hub_items에 15개가 쌓여 있는데 그중 1개만 후보라, 소재가 '폰 쿨러'여도
      last_product가 '제습제'면 링크가 통째로 빠졌다. 판정은 affiliate_pool 단일 정본.

    text: 스레드처럼 캡션과 다른 본문으로 게시하는 경로는 **실제 게시할 글**로 매칭한다.
    """
    from affiliate_pool import best
    return best(text if text is not None else build_caption(meta))


def with_affiliate(text, meta=None, limit=MAX_THREADS):
    """스레드 본문 말미에 쿠팡 링크를 붙인다 → (본문, 답글목록).

    2026-08-27 실사고: 링크가 **답글**로만 달렸는데, 답글은 원글 조회의 극히 일부만 본다.
      실측 — 스레드 7일 조회 151,571회에 쿠팡 링크 클릭 12회(11일). 최근 글 25개 중
      본문에 링크가 있는 글은 0개였다. 게다가 native_threads_text 경로(현재 대부분의 글)는
      답글 체인 자체를 안 써서 링크가 아예 붙지 않았다.
    상한(500자)을 넘으면 본문을 자르지 않고 답글로 폴백한다 — 내용을 상하게 하면서까지
      넣을 이유는 없다. 고지 문구는 링크와 **같은 글**에 있어야 한다(법정 의무).
    """
    if not AFFILIATE_MEDIA_REGISTERED:
        print("[affiliate] 매체 미등록으로 부착 보류 — 파트너스에 스레드·블로그 등록 후 "
              "AFFILIATE_MEDIA_REGISTERED=True (2026-09-05)", flush=True)
        return text, []
    from affiliate_pool import attach, link_block
    url, name = affiliate_for(meta or {}, text=text)
    if not url:
        return text, []
    # 2026-08-31: 팔로우 유도 문구를 폐기하면서(디렉터: "짜친다") CTA를 맨 끝으로
    # 옮기던 로직도 함께 제거했다. 본문은 출처로 끝나고 링크 블록이 그 뒤에 붙는다.
    joined = attach(text, name, url, limit=limit)
    if joined:
        return joined, []
    return text, [link_block(name, url)]


def r2_put(kv, path):
    """렌더 mp4를 R2에 임시 공개 업로드 → (s3클라이언트, 키, 공개 URL).
    2026-08-05 실측: 이 계정/앱 유형은 resumable(rupload) 거부, video_url 방식만 허용 —
    Meta가 URL에서 가져가면 삭제한다."""
    import boto3
    # 파일 내용 해시를 키에 붙인다 — 같은 파일명으로 재렌더·재게시할 때 URL이 바뀌지 않으면
    # 메타(스레드) CDN이 **첫 요청 때 가져간 옛 영상을 URL 기준으로 재사용**한다.
    # 2026-08-25 실사고: 추석 편 배경을 교체해 재게시했는데 릴스는 새 영상, 스레드는 옛 영상(중국 한푸)이
    # 올라갔다 — IG와 스레드가 캐시를 따로 갖고 있어 스레드만 캐시 히트했다. 내용이 바뀌면 URL도 바뀌게 한다.
    import hashlib
    _h = hashlib.sha1()
    with open(path, "rb") as _f:
        for _chunk in iter(lambda: _f.read(1 << 20), b""):
            _h.update(_chunk)
    _base, _ext = os.path.splitext(os.path.basename(path))
    key = "reels/%s-%s%s" % (_base, _h.hexdigest()[:10], _ext)
    s3 = boto3.client("s3",
                      endpoint_url="https://%s.r2.cloudflarestorage.com" % kv["R2_ACCOUNT_ID"],
                      aws_access_key_id=kv["R2_ACCESS_KEY"],
                      aws_secret_access_key=kv["R2_SECRET_KEY"], region_name="auto")
    s3.upload_file(path, kv["R2_BUCKET"], key, ExtraArgs={"ContentType": "video/mp4"})
    return s3, key, kv["R2_PUBLIC_URL"].rstrip("/") + "/" + key


def _validate_r2_config(kv):
    """R2 설정 단일 가드 — 존재 검사 후 오염 검사 (2026-08-23 리뷰: upload()·publish_carousel의
    5키 루프 사본을 여기로 통합. 키가 아예 없으면 '없음'으로, 있는데 이상하면 '오염'으로 구분 보고).
    오염 검출 배경: 2026-08-12 실사고 — 키 추가 시 줄바꿈 누락으로 R2_PUBLIC_URL 끝에
    다른 키가 이어붙어 IG 컨테이너가 조용히 ERROR, 슬롯 2회 실패."""
    for k in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY", "R2_SECRET_KEY", "R2_BUCKET", "R2_PUBLIC_URL"):
        if not kv.get(k):
            raise RuntimeError("keys.env에 %s 없음 — R2 업로드 불가" % k)
    u = kv["R2_PUBLIC_URL"]
    if not u.startswith("https://") or "=" in u or not u.rstrip("/").endswith(".r2.dev"):
        raise RuntimeError("keys.env 오염 의심: R2_PUBLIC_URL 형식 이상(%r...) — "
                           "줄바꿈 누락으로 다른 키가 이어붙었는지 확인하라" % u[:40])


def upload(video, meta, publish=True):
    kv = load_keys()
    _validate_r2_config(kv)
    token, user_id = kv.get("IG_ACCESS_TOKEN"), kv.get("IG_USER_ID")
    if not token or not user_id:
        raise RuntimeError("keys.env에 IG_ACCESS_TOKEN/IG_USER_ID 없음 — 릴스 업로드 건너뜀")
    # 멱등 가드 (2026-08-05 점검): 이미 게시된 파일이면 건너뛰고 성공 취급 — 재실행/재시도 중복 게시 봉쇄
    sent_p = os.path.join(ROOT, "logs", "sent.log")
    base = os.path.basename(video)
    if os.path.exists(sent_p) and any(ln.rstrip().endswith("IG:" + base)
                                      for ln in open(sent_p, encoding="utf-8", errors="ignore")):
        # 2026-08-17 실사고: 16시 슬롯이 상주 세션과 같은 파일명(-pm)을 써서 여기서 건너뛰었는데,
        #   세션이 반환값을 '성공'으로 읽고 "Instagram 게시 완료"라고 허위 보고했다.
        #   → 조용히 넘기지 말고 경고를 띄운다. 파일명 충돌은 사고지 정상이 아니다.
        print("이미 게시됨(IG:%s) — 건너뜀" % base)
        try:
            tg("⚠️ 인스타 게시를 건너뛰었습니다 — 같은 파일명이 이미 게시된 기록이 있습니다: %s\n"
               "파일명이 겹친 것이라면 다른 이름으로 다시 렌더해 게시하세요." % base)
        except Exception:
            pass
        return "already-published"
    token = refresh_token_if_due(token)

    # 1) R2 임시 업로드 → 공개 URL
    s3, r2key, url = r2_put(kv, video)
    print("R2 업로드: %s (%.1fMB)" % (url, os.path.getsize(video) / 1e6), flush=True)
    try:
        # 2) 컨테이너 생성 (video_url 방식)
        # 커버 = 훅 텍스트 전부 노출된 프레임 (렌더러가 meta에 기록, 없으면 3초 지점)
        data = {
            "media_type": "REELS", "video_url": url,
            "caption": build_caption(meta), "share_to_feed": "true",
            "thumb_offset": str(int(meta.get("ig_thumb_ms", 3000))),
            "access_token": token,
        }
        cont = api("POST", "/%s/media" % user_id, data=data)
        cid = cont["id"]
        print("컨테이너 생성: %s" % cid, flush=True)
        return _wait_and_publish(kv, s3, r2key, cid, user_id, token, meta, publish, video, data, url)
    except Exception:
        _r2_cleanup(kv, s3, r2key)
        raise


def _r2_cleanup(kv, s3, r2key):
    try:
        s3.delete_object(Bucket=kv["R2_BUCKET"], Key=r2key)
        print("R2 정리 완료", flush=True)
    except Exception as e:
        print("R2 삭제 실패(%s) — 수동 정리 필요: %s" % (e, r2key), flush=True)
        tg("⚠️ R2 임시 파일 삭제 실패 — 수동 정리 필요: %s" % r2key)


def _wait_and_publish(kv, s3, r2key, cid, user_id, token, meta, publish, video, container_data, public_url):

    # 3) 처리 대기 (ERROR·타임아웃 시 컨테이너 1회 재생성 — 2026-08-14 감사: 일시 인코딩 실패 내성)
    def _wait(cid_):
        for _ in range(POLL_MAX):
            st = api("GET", "/%s" % cid_, params={"fields": "status_code", "access_token": token})
            code = st.get("status_code")
            if code == "FINISHED":
                return None
            if code == "ERROR":
                return "IG 컨테이너 처리 실패: %s" % st
            time.sleep(POLL_INTERVAL)
        return "IG 처리 대기 시간 초과(5분)"
    err = _wait(cid)
    if err:
        print("1차 실패(%s) — 컨테이너 재생성 1회 재시도" % err, flush=True)
        cont2 = api("POST", "/%s/media" % user_id, data=container_data)
        cid = cont2["id"]
        print("컨테이너 재생성: %s" % cid, flush=True)
        err = _wait(cid)
        if err:
            raise RuntimeError(err)

    if not publish:
        # 시험 모드: 게시 직전 중단 — 미게시 컨테이너는 24시간 뒤 자동 소멸 (2026-08-05 리허설용)
        print("--no-publish: 컨테이너 %s 처리 FINISHED 확인, 게시 없이 종료" % cid)
        _r2_cleanup(kv, s3, r2key)
        return None

    # 4) 게시 — 성공 즉시 실측 기록(멱등 가드·러너 판정의 근거), 이후 조회 실패는 성공을 뒤집지 않는다
    pub = api("POST", "/%s/media_publish" % user_id,
              data={"creation_id": cid, "access_token": token})
    media_id = pub["id"]
    import datetime
    with open(os.path.join(ROOT, "logs", "sent.log"), "a") as f:
        f.write("%s IG:%s\n" % (datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                                os.path.basename(video)))
    # ── 스레드 동시 게시 (2026-08-16 디렉터: "릴스 올리면 쓰레드에도 자동으로")
    # R2 정리 '전에' 해야 한다 — 같은 공개 URL을 스레드가 다시 가져가기 때문이다.
    # 실패해도 릴스 게시는 이미 끝났으니 슬롯을 죽이지 않는다(경고만).
    if not VIDEO_TO_THREADS:
        print("[영상] 스레드 건너뜀 — 플랫폼 분리 편성 (2026-08-29)", flush=True)
        _r2_cleanup(kv, s3, r2key)
        return media_id
    try:
        import upload_threads
        _tt = native_threads_text(meta.get("threads_text"), build_caption(meta))
        if _tt:
            # 2026-08-27: 이 경로가 '답글 체인 없이 단독 완결'이라 쿠팡 링크가 통째로 빠져 있었다.
            # 최근 글 대부분이 이 경로다 — 스레드 25개 글 중 본문 링크 0개의 직접 원인.
            _tt, _rep = with_affiliate(_tt, meta)
            th_link = upload_threads.publish(public_url, _tt, replies=_rep)
        else:
            _head, _replies = threads_parts(meta)
            th_link = upload_threads.publish(public_url, _head, replies=_replies)
        print("스레드 게시 완료:", th_link, flush=True)
    except Exception as _te:
        print("스레드 게시 실패(무해, 릴스는 정상):", str(_te)[:200], flush=True)
        tg("⚠️ 스레드 게시 실패(릴스는 정상 게시됨): %s" % str(_te)[:150])
    _r2_cleanup(kv, s3, r2key)   # Meta가 인코딩까지 마친 뒤라 원본 URL은 더 필요 없음
    try:
        perma = api("GET", "/%s" % media_id,
                    params={"fields": "permalink", "access_token": token}).get("permalink", "")
    except Exception as e:
        perma = "(permalink 조회 실패: %s)" % str(e)[:80]
    print("릴스 게시 완료:", perma or media_id)
    # 2026-08-10: permalink 원장 — 제목을 나중에 교체하면 IG 캡션과 어긋나 대조가 실패한다(치킨게임 편 실사고).
    # 파일명 기준 원장을 남겨 두면 어떤 편이 어떤 게시물인지 항상 역추적 가능.
    try:
        with open(os.path.join(ROOT, "logs", "ig_posts.log"), "a", encoding="utf-8") as _f:
            _f.write("%s\t%s\t%s\t%s\n" % (time.strftime("%Y-%m-%dT%H:%M:%S"),
                     os.path.basename(video), media_id, perma or ""))
    except Exception as _e:
        print("permalink 원장 기록 실패(무해):", _e)
    tg("✅ 인스타 릴스 게시 완료\n%s\n%s" % (build_caption(meta).split("\n")[0], perma))
    return media_id


def _publish_threads_card(kv, keys, caption, threads_text, card_name, ig=True):
    """카드 이미지를 스레드에 게시한다 (IG 게시 여부와 무관하게 같은 경로를 쓴다).
    R2 정리(finally) 전에 호출해야 한다 — 스레드 컨테이너가 이미지 URL을 읽어야 하기 때문.
    제휴봇이 IG 캡션 첫 줄로 스레드 글을 찾으므로 첫 줄은 캡션과 일치해야 한다."""
    import datetime
    try:
        import upload_threads as _th
        base = kv["R2_PUBLIC_URL"].rstrip("/")
        _body, _rep = with_affiliate(
            native_threads_text(threads_text, caption) or _caption_for_threads(caption),
            {"caption": caption})
        th_link = _th.publish_images([base + "/" + k for k in keys], _body, replies=_rep)
        print("스레드 게시 완료:", th_link, flush=True)
        if not ig:
            # 스레드 전용 슬롯의 멱등 가드용 기록 (IGCARD가 안 남으므로)
            with open(os.path.join(ROOT, "logs", "sent.log"), "a") as f:
                f.write("%s THCARD:%s\n"
                        % (datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"), card_name))
            tg("✅ 지식 카드 게시 완료 (스레드 전용)\n%s\n%s"
               % (caption.split("\n")[0], th_link or ""))
        return th_link
    except Exception as _e:
        print("스레드 게시 실패:", str(_e)[:150], flush=True)
        tg("⚠️ 카드 스레드 게시 실패%s — 제휴 링크 답글이 안 붙을 수 있음\n%s"
           % ("" if ig else " (이 슬롯은 스레드 전용이라 아무 데도 안 나갔다)", str(_e)[:150]))
        return None


def publish_carousel(images, caption, publish=True, threads_text=None, ig=None):
    """지식 카드 캐러셀 게시.
    images: PNG 경로 리스트(2~3장). 흐름: R2 업로드 → 아이템 컨테이너 → 캐러셀 컨테이너 → 게시 → R2 정리.

    ig=False면 **인스타를 건너뛰고 스레드에만** 올린다 (2026-08-29 디렉터 지시:
    "카드는 스레드는 유지, 인스타는 3장으로 줄입시다").
    근거 — 인스타 릴스 중앙값이 8/25 706회 → 8/29 161회로 5일 만에 1/4이 됐고, 카드는
    릴스의 40% 수준(74회)에서 계속 낮았다. 팔로워 1,141명에게조차 안 닿는 상태다.
    같은 소재로 스레드(카드 최고편 2,529회·반응 22)와 유튜브(평균 588회)는 정상이므로
    소재가 아니라 **인스타 계정 도달** 문제로 보고, 하루 12편(릴스 6+카드 6)의 1~2시간
    간격 연속 게시를 과다 신호 후보로 잡아 카드 IG 노출을 3장으로 줄인다.
    스레드는 카드가 잘 받고 있으므로 6장 전부 유지한다."""
    if ig is None:
        ig = CARD_TO_IG        # 기본값은 편성 스위치를 따른다 (2026-08-29)
    kv = load_keys()
    _validate_r2_config(kv)   # upload()와 동일 단일 가드 (2026-08-23 리뷰: 존재+오염 통합)
    token, user_id = kv.get("IG_ACCESS_TOKEN"), kv.get("IG_USER_ID")
    if not token or not user_id:
        raise RuntimeError("keys.env에 IG_ACCESS_TOKEN/IG_USER_ID 없음")
    # 멱등 가드 (2026-08-05 점검): 같은 카드 묶음(디렉터리명)이 이미 게시됐으면 건너뜀
    card_name = os.path.basename(os.path.dirname(images[0]))
    sent_p = os.path.join(ROOT, "logs", "sent.log")
    # 스레드 전용 게시(ig=False)는 IGCARD 로그를 남기지 않으므로 THCARD로 따로 가드한다
    _mark = "IGCARD:" if ig else "THCARD:"
    if os.path.exists(sent_p) and any(ln.rstrip().endswith(_mark + card_name)
                                      for ln in open(sent_p, encoding="utf-8", errors="ignore")):
        print("이미 게시됨(%s%s) — 건너뜀" % (_mark, card_name))
        return "already-published"
    token = refresh_token_if_due(token)
    import boto3
    s3 = boto3.client("s3",
                      endpoint_url="https://%s.r2.cloudflarestorage.com" % kv["R2_ACCOUNT_ID"],
                      aws_access_key_id=kv["R2_ACCESS_KEY"],
                      aws_secret_access_key=kv["R2_SECRET_KEY"], region_name="auto")
    keys, child_ids = [], []
    try:
        for p in images:
            # 파일 내용 해시를 키에 붙인다 — 고정 키로 덮어쓰면 URL이 그대로라 메타 CDN이
            # **첫 요청 때 가져간 옛 이미지를 재사용**한다. 2026-08-27 실사고: 아이폰 카드
            # 이미지를 교체해 재게시했는데 IG·스레드 양쪽에 옛 이미지가 그대로 올라갔다
            # (영상 r2_put에는 8/25에 같은 수정을 했는데 카드 경로만 빠져 있었다).
            import hashlib as _hl
            _h = _hl.sha1()
            with open(p, "rb") as _f:
                for _c in iter(lambda: _f.read(1 << 20), b""):
                    _h.update(_c)
            _stem, _ext = os.path.splitext(os.path.basename(p))
            key = "cards/%s/%s-%s%s" % (os.path.basename(os.path.dirname(p)),
                                        _stem, _h.hexdigest()[:10], _ext)
            s3.upload_file(p, kv["R2_BUCKET"], key, ExtraArgs={"ContentType": "image/png"})
            keys.append(key)
            url = kv["R2_PUBLIC_URL"].rstrip("/") + "/" + key
            item = api("POST", "/%s/media" % user_id, data={
                "image_url": url, "is_carousel_item": "true", "access_token": token})
            child_ids.append(item["id"])
        print("아이템 컨테이너 %d개 생성" % len(child_ids), flush=True)
        for ch in child_ids:   # 자식 인코딩 완료 대기 (2026-08-05 점검)
            for _ in range(POLL_MAX):
                st = api("GET", "/%s" % ch, params={"fields": "status_code", "access_token": token})
                if st.get("status_code") == "FINISHED":
                    break
                if st.get("status_code") == "ERROR":
                    raise RuntimeError("아이템 컨테이너 처리 실패: %s" % st)
                time.sleep(3)
            else:
                raise RuntimeError("아이템 컨테이너 처리 대기 초과")
        if not ig:
            # 인스타 건너뛰기 — R2 업로드는 이미 끝났으므로 스레드 게시로 직행한다.
            print("[카드] 인스타 건너뜀 (스레드 전용 슬롯) — 2026-08-29 도달 회복 조치",
                  flush=True)
            media_id, perma = None, ""
            _publish_threads_card(kv, keys, caption, threads_text, card_name, ig=False)
            return "threads-only"
        cont = api("POST", "/%s/media" % user_id, data={
            "media_type": "CAROUSEL", "children": ",".join(child_ids),
            "caption": caption[:2200], "access_token": token})
        cid = cont["id"]
        for _ in range(POLL_MAX):
            st = api("GET", "/%s" % cid, params={"fields": "status_code", "access_token": token})
            if st.get("status_code") == "FINISHED":
                break
            if st.get("status_code") == "ERROR":
                raise RuntimeError("캐러셀 컨테이너 처리 실패: %s" % st)
            time.sleep(POLL_INTERVAL)
        else:
            raise RuntimeError("캐러셀 처리 대기 초과")
        if not publish:
            print("--no-publish: 캐러셀 %s FINISHED 확인, 게시 없이 종료" % cid)
            return None
        # media_publish 재시도 — FINISHED 직후에도 9007 "not available" 가능
        pub = None
        for attempt in range(5):
            try:
                pub = api("POST", "/%s/media_publish" % user_id,
                          data={"creation_id": cid, "access_token": token})
                break
            except RuntimeError as e:
                if "9007" in str(e) and attempt < 4:
                    print("media_publish 대기 재시도 %d/4…" % (attempt + 1), flush=True)
                    time.sleep(10)
                else:
                    raise
        assert pub is not None
        media_id = pub["id"]
        import datetime
        with open(os.path.join(ROOT, "logs", "sent.log"), "a") as f:
            f.write("%s IGCARD:%s\n" % (datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"), card_name))
        try:
            perma = api("GET", "/%s" % media_id,
                        params={"fields": "permalink", "access_token": token}).get("permalink", "")
        except Exception as e:
            perma = "(permalink 조회 실패: %s)" % str(e)[:80]
        print("카드 게시 완료:", perma or media_id)
        # 스레드에도 게시 (2026-08-20 디렉터: "카드 소재도 스레드에 올리자" —
        # 제휴봇이 IG 캡션 첫 줄로 스레드 글을 찾아 쿠팡 링크 답글을 달기 때문.
        # 첫 줄이 IG 캡션과 반드시 일치해야 find_recent_post 매칭이 된다.)
        # R2 정리(finally) 전에 실행 — 스레드 컨테이너가 이미지 URL을 읽어야 한다.
        _publish_threads_card(kv, keys, caption, threads_text, card_name, ig=True)
        tg("✅ 지식 카드 게시 완료\n%s\n%s" % (caption.split("\n")[0], perma))
        return media_id
    finally:
        for key in keys:
            try:
                s3.delete_object(Bucket=kv["R2_BUCKET"], Key=key)
            except Exception as e:
                print("R2 삭제 실패(%s): %s" % (e, key), flush=True)


def main():
    args = [a for a in sys.argv[1:] if a != "--no-publish"]
    if len(args) < 2:
        sys.exit("사용: upload_instagram.py <video.mp4> <meta.json> [--no-publish]")
    with open(args[1], encoding="utf-8") as f:
        meta = json.load(f)
    upload(args[0], meta, publish="--no-publish" not in sys.argv)


if __name__ == "__main__":
    main()
