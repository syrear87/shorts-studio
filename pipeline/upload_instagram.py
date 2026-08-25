#!/usr/bin/env python3
# 인스타그램 릴스 자동 업로더 (Instagram API with Instagram Login).
#  - keys.env에 IG_ACCESS_TOKEN, IG_USER_ID 필요 (본인 프로페셔널 계정, 앱 심사 불필요)
#  - 흐름: R2 공개 URL 업로드 → 컨테이너 생성(video_url) → 상태 폴링 → 게시 (이 계정은 rupload 거부 — R2 경유가 정본)
#  - 캡션 = 제목 + 본문 (유튜브 설명과 동일 포맷, 디렉터 지정 2026-07-29)
#  - 장기 토큰(60일)은 마지막 갱신 7일 경과 시 자동 갱신해 keys.env를 업데이트
# 사용: python3 pipeline/upload_instagram.py out/영상.mp4 content/영상.meta.json
import json, os, subprocess, sys, time  # 2026-08-02 리뷰 [A18]: 미사용 re 제거
import urllib.request, urllib.parse, urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEYS = os.path.join(ROOT, "keys.env")
STATE = os.path.join(ROOT, "logs", ".ig_token_refreshed")   # 새 토큰 투입 시 touch logs/.ig_token_refreshed 병행 (2026-08-02 리뷰 [A18])
GRAPH = "https://graph.instagram.com/v23.0"   # 버전 고정 — 무버전 호출은 Meta 버전 폐기 시 무예고 파손 (2026-08-02 리뷰 [A18])
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


def native_threads_text(threads_text, caption):
    """스레드 전용 본문 가드 (2026-08-23 성장 연구 — 뉴스체 캡션 복제 대신 1인칭 현지화 본문 사용).
    단 **첫 줄(훅)은 IG 캡션 첫 줄과 동일**해야 한다 — 제휴봇(find_recent_post)이 캡션 첫 줄로
    스레드 글을 되찾아 쿠팡 링크를 달기 때문. 다르면 캡션 훅을 첫 줄로 강제 삽입한다."""
    if not threads_text:
        return None
    hook = (caption or "").split("\n")[0].strip()
    first = threads_text.split("\n")[0].strip()
    if hook and first != hook:
        return hook + "\n\n" + threads_text
    return threads_text


def threads_parts(meta):
    """스레드 본문 (2026-08-16 디렉터 확정): 첫 글 = 제목 + 내용(출처 제외),
    답글 = 쿠팡 링크. **쿠팡 링크가 없으면 답글을 달지 않는다.**
    스레드 상한 500자라 넘치면 블록 단위로 잘라낸다(잘랐음을 숨기지 않고 '…'로 표시).
    쿠팡 링크에는 대가성 문구가 법적 의무이므로 항상 같은 글에 붙인다."""
    blocks = [b.strip() for b in build_caption(meta).split("\n\n") if b.strip()]
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
    link, name = affiliate_for(meta)
    replies = ["%s\n%s\n\n%s" % (name, link, DISCLOSURE_TEXT)] if link else []
    return head, replies


from disclosure import DISCLOSURE as DISCLOSURE_TEXT   # 법정 고지 문구 단일 정본 (2026-08-25)


def affiliate_for(meta):
    """이 편과 짝이 되는 쿠팡 상품 (링크, 이름). 없으면 (None, None).
    판정: 상품명 낱말이 이 편 캡션에 등장하는가 — 무관한 편에 상품을 붙이면 광고 계정이 된다
    (2026-08-16 '직결 판정법'과 같은 기준)."""
    import re as _re
    try:
        st = json.load(open(os.path.join(ROOT, "logs", "affiliate_state.json"), encoding="utf-8"))
    except Exception:
        return None, None
    p = st.get("last_product") or {}
    name, url = p.get("name"), p.get("url")
    if not (name and url):
        return None, None
    # 2026-08-24 실사고: 여기 있던 자체 채점 사본이 영문 조각 소음으로 '앤커 충전기'를
    # 관절 편에 3점 매칭 — 채점은 product_match 단일 정본만 쓴다.
    from product_match import score
    if score(name, build_caption(meta)) >= 3:
        return url, name
    return None, None


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
    try:
        import upload_threads
        _tt = native_threads_text(meta.get("threads_text"), build_caption(meta))
        if _tt:
            th_link = upload_threads.publish(public_url, _tt)   # 현지화 본문 — 답글 체인 없이 단독 완결
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


def publish_carousel(images, caption, publish=True, threads_text=None):
    """지식 카드 캐러셀 게시 (2026-08-05 디렉터 승인 — 하루 3편 아침·점심·저녁).
    images: PNG 경로 리스트(2~3장). 흐름: R2 업로드 → 아이템 컨테이너 → 캐러셀 컨테이너 → 게시 → R2 정리."""
    kv = load_keys()
    _validate_r2_config(kv)   # upload()와 동일 단일 가드 (2026-08-23 리뷰: 존재+오염 통합)
    token, user_id = kv.get("IG_ACCESS_TOKEN"), kv.get("IG_USER_ID")
    if not token or not user_id:
        raise RuntimeError("keys.env에 IG_ACCESS_TOKEN/IG_USER_ID 없음")
    # 멱등 가드 (2026-08-05 점검): 같은 카드 묶음(디렉터리명)이 이미 게시됐으면 건너뜀
    card_name = os.path.basename(os.path.dirname(images[0]))
    sent_p = os.path.join(ROOT, "logs", "sent.log")
    if os.path.exists(sent_p) and any(ln.rstrip().endswith("IGCARD:" + card_name)
                                      for ln in open(sent_p, encoding="utf-8", errors="ignore")):
        print("이미 게시됨(IGCARD:%s) — 건너뜀" % card_name)
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
            key = "cards/%s/%s" % (os.path.basename(os.path.dirname(p)), os.path.basename(p))
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
        try:
            import upload_threads as _th
            base = kv["R2_PUBLIC_URL"].rstrip("/")
            th_link = _th.publish_images([base + "/" + k for k in keys],
                                         native_threads_text(threads_text, caption) or caption)
            print("스레드 게시 완료:", th_link, flush=True)
        except Exception as _e:
            print("스레드 게시 실패(카드 자체는 게시됨):", str(_e)[:150], flush=True)
            tg("⚠️ 카드는 게시됐지만 스레드 게시 실패 — 제휴 링크 답글이 안 붙을 수 있음\n%s" % str(_e)[:150])
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
