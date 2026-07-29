#!/usr/bin/env python3
# 인스타그램 릴스 자동 업로더 (Instagram API with Instagram Login).
#  - keys.env에 IG_ACCESS_TOKEN, IG_USER_ID 필요 (본인 프로페셔널 계정, 앱 심사 불필요)
#  - 흐름: 컨테이너 생성(resumable) → rupload로 바이너리 업로드 → 상태 폴링 → 게시
#  - 캡션 = 제목 + 본문 (유튜브 설명과 동일 포맷, 디렉터 지정 2026-07-29)
#  - 장기 토큰(60일)은 마지막 갱신 7일 경과 시 자동 갱신해 keys.env를 업데이트
# 사용: python3 pipeline/upload_instagram.py out/영상.mp4 content/영상.meta.json
import json, os, re, subprocess, sys, time
import urllib.request, urllib.parse, urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEYS = os.path.join(ROOT, "keys.env")
STATE = os.path.join(ROOT, "logs", ".ig_token_refreshed")
GRAPH = "https://graph.instagram.com"
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
            age_days = 999
        if age_days > 40:   # 60일 만료 임박인데 갱신이 계속 실패 → 무증상 방지 경보
            tg("⚠️ 인스타 토큰 갱신이 %d일째 실패 중 — 60일 만료 전에 재발급 필요" % int(age_days))
    return token


def build_caption(meta):
    title = meta["title"].replace("#shorts", "").replace("#Shorts", "").strip()
    desc = meta["description"]
    if "Pexels" not in desc:
        desc += "\n\n배경 영상: Pexels (www.pexels.com)"
    return ("%s\n\n%s" % (title, desc))[:2200]


def upload(video, meta):
    kv = load_keys()
    token, user_id = kv.get("IG_ACCESS_TOKEN"), kv.get("IG_USER_ID")
    if not token or not user_id:
        raise RuntimeError("keys.env에 IG_ACCESS_TOKEN/IG_USER_ID 없음 — 릴스 업로드 건너뜀")
    token = refresh_token_if_due(token)

    # 1) 컨테이너 생성 (resumable)
    cont = api("POST", "/%s/media" % user_id, data={
        "media_type": "REELS", "upload_type": "resumable",
        "caption": build_caption(meta), "share_to_feed": "true",
        "access_token": token,
    })
    cid = cont["id"]
    print("컨테이너 생성: %s" % cid, flush=True)

    # 2) 바이너리 업로드
    size = os.path.getsize(video)
    with open(video, "rb") as f:
        api("POST", "/%s" % cid, base=RUPLOAD, raw_body=f.read(), headers={
            "Authorization": "OAuth " + token,
            "offset": "0", "file_size": str(size),
            "Content-Type": "application/octet-stream",
        })
    print("바이너리 업로드 완료 (%.1fMB)" % (size / 1e6), flush=True)

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

    # 4) 게시
    pub = api("POST", "/%s/media_publish" % user_id,
              data={"creation_id": cid, "access_token": token})
    media_id = pub["id"]
    perma = api("GET", "/%s" % media_id,
                params={"fields": "permalink", "access_token": token}).get("permalink", "")
    print("릴스 게시 완료:", perma or media_id)
    tg("✅ 인스타 릴스 게시 완료\n%s\n%s" % (build_caption(meta).split("\n")[0], perma))
    return media_id


def main():
    if len(sys.argv) < 3:
        sys.exit("사용: upload_instagram.py <video.mp4> <meta.json>")
    with open(sys.argv[2], encoding="utf-8") as f:
        meta = json.load(f)
    upload(sys.argv[1], meta)


if __name__ == "__main__":
    main()
