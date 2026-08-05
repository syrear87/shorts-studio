#!/usr/bin/env python3
# 인스타그램 릴스 자동 업로더 (Instagram API with Instagram Login).
#  - keys.env에 IG_ACCESS_TOKEN, IG_USER_ID 필요 (본인 프로페셔널 계정, 앱 심사 불필요)
#  - 흐름: 컨테이너 생성(resumable) → rupload로 바이너리 업로드 → 상태 폴링 → 게시
#  - 캡션 = 제목 + 본문 (유튜브 설명과 동일 포맷, 디렉터 지정 2026-07-29)
#  - 장기 토큰(60일)은 마지막 갱신 7일 경과 시 자동 갱신해 keys.env를 업데이트
# 사용: python3 pipeline/upload_instagram.py out/영상.mp4 content/영상.meta.json
import json, os, subprocess, sys, time  # 2026-08-02 리뷰 [A18]: 미사용 re 제거
import urllib.request, urllib.parse, urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEYS = os.path.join(ROOT, "keys.env")
STATE = os.path.join(ROOT, "logs", ".ig_token_refreshed")   # 새 토큰 투입 시 touch logs/.ig_token_refreshed 병행 (2026-08-02 리뷰 [A18])
GRAPH = "https://graph.instagram.com/v23.0"   # 2026-08-02 리뷰 [A18]: RUPLOAD와 버전 일치 고정 — 무버전 호출은 Meta 버전 폐기 시 무예고 파손
RUPLOAD = "https://rupload.facebook.com/ig-api-upload/v23.0"
REFRESH_AFTER = 7 * 86400          # 7일마다 토큰 갱신
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


def api(method, path, params=None, data=None, headers=None, raw_body=None, base=GRAPH):
    url = base + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    body = raw_body
    if data is not None:
        body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
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
            os.replace(tmp, KEYS)
            token = new
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        open(STATE, "w").write(str(int(time.time())))
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
    """캡션 = 제목 + 본문 전문, 단 맨 아래 '태그: ...' 줄만 제거 (2026-08-05 디렉터 포맷 지정).
    본문 안의 해시태그 줄(#...)과 Pexels 크레딧은 그대로 유지한다."""
    title = meta["title"].replace("#shorts", "").replace("#Shorts", "").strip()
    desc = meta["description"]
    # 2026-08-05 디렉터: Pexels 크레딧 줄도 캡션에서 제거 (채널 정보란으로 이관)
    lines = [l for l in desc.splitlines()
             if not l.strip().startswith("태그:") and "배경 영상: Pexels" not in l]
    desc = "\n".join(lines).strip()
    return ("%s\n\n%s" % (title, desc))[:2200]


def r2_put(kv, path):
    """렌더 mp4를 R2에 임시 공개 업로드 → (s3클라이언트, 키, 공개 URL).
    2026-08-05 실측: 이 계정/앱 유형은 resumable(rupload) 거부, video_url 방식만 허용 —
    Meta가 URL에서 가져가면 삭제한다."""
    import boto3
    key = "reels/%s" % os.path.basename(path)
    s3 = boto3.client("s3",
                      endpoint_url="https://%s.r2.cloudflarestorage.com" % kv["R2_ACCOUNT_ID"],
                      aws_access_key_id=kv["R2_ACCESS_KEY"],
                      aws_secret_access_key=kv["R2_SECRET_KEY"], region_name="auto")
    s3.upload_file(path, kv["R2_BUCKET"], key, ExtraArgs={"ContentType": "video/mp4"})
    return s3, key, kv["R2_PUBLIC_URL"].rstrip("/") + "/" + key


def upload(video, meta, publish=True):
    kv = load_keys()
    token, user_id = kv.get("IG_ACCESS_TOKEN"), kv.get("IG_USER_ID")
    if not token or not user_id:
        raise RuntimeError("keys.env에 IG_ACCESS_TOKEN/IG_USER_ID 없음 — 릴스 업로드 건너뜀")
    for k in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY", "R2_SECRET_KEY", "R2_BUCKET", "R2_PUBLIC_URL"):
        if not kv.get(k):
            raise RuntimeError("keys.env에 %s 없음 — 릴스 업로드 건너뜀" % k)
    # 멱등 가드 (2026-08-05 점검): 이미 게시된 파일이면 건너뛰고 성공 취급 — 재실행/재시도 중복 게시 봉쇄
    sent_p = os.path.join(ROOT, "logs", "sent.log")
    base = os.path.basename(video)
    if os.path.exists(sent_p) and any(ln.rstrip().endswith("IG:" + base)
                                      for ln in open(sent_p, encoding="utf-8", errors="ignore")):
        print("이미 게시됨(IG:%s) — 건너뜀" % base)
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
        return _wait_and_publish(kv, s3, r2key, cid, user_id, token, meta, publish, video)
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


def _wait_and_publish(kv, s3, r2key, cid, user_id, token, meta, publish, video):

    # 3) 처리 대기
    for _ in range(POLL_MAX):
        st = api("GET", "/%s" % cid, params={"fields": "status_code", "access_token": token})
        code = st.get("status_code")
        if code == "FINISHED":
            break
        if code == "ERROR":
            raise RuntimeError("IG 컨테이너 처리 실패: %s" % st)
        time.sleep(POLL_INTERVAL)
    else:
        raise RuntimeError("IG 처리 대기 시간 초과(5분)")

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
    _r2_cleanup(kv, s3, r2key)   # Meta가 인코딩까지 마친 뒤라 원본 URL은 더 필요 없음
    try:
        perma = api("GET", "/%s" % media_id,
                    params={"fields": "permalink", "access_token": token}).get("permalink", "")
    except Exception as e:
        perma = "(permalink 조회 실패: %s)" % str(e)[:80]
    print("릴스 게시 완료:", perma or media_id)
    tg("✅ 인스타 릴스 게시 완료\n%s\n%s" % (build_caption(meta).split("\n")[0], perma))
    return media_id


def publish_carousel(images, caption, publish=True):
    """지식 카드 캐러셀 게시 (2026-08-05 디렉터 승인 — 하루 3편 아침·점심·저녁).
    images: PNG 경로 리스트(2~3장). 흐름: R2 업로드 → 아이템 컨테이너 → 캐러셀 컨테이너 → 게시 → R2 정리."""
    kv = load_keys()
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
        pub = api("POST", "/%s/media_publish" % user_id,
                  data={"creation_id": cid, "access_token": token})
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
