#!/usr/bin/env python3
# 스레드(Threads) 게시 (2026-08-16 디렉터: "인스타 릴스 올리면 쓰레드에도 자동으로 올라가게 가능하니")
#
# 왜 하는가: 우리 병목은 '릴스를 본 비팔로워가 링크에 닿을 방법이 없다'는 것이다
#   (IG 캡션 URL은 클릭 불가, 스토리는 팔로워만 본다 — 2026-08-16 오전 진단).
#   **스레드는 게시물 안 링크가 클릭된다** — 파트너스 통로가 하나 더 생긴다.
#
# 흐름: R2 공개 URL(인스타 업로드와 동일한 mp4)로 컨테이너 생성 → 상태 폴링 → 발행.
#   토큰은 keys.env의 THREADS_TOKEN(장기 60일). 만료가 가까우면 자동 갱신한다.
#
# 사용: from upload_threads import publish; publish(video_url, text)
import json
import os
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = "https://graph.threads.net/v1.0"
KEYS = os.path.join(ROOT, "keys.env")
MAX_TEXT = 500          # 스레드 본문 상한
REFRESH_BEFORE = 7 * 86400   # 만료 7일 전부터 갱신 시도


def _env():
    out = {}
    for line in open(KEYS, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"')
    return out


def _get(url, timeout=60):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.load(r)


def _post(path, params, timeout=120):
    url = "%s/%s" % (API, path.lstrip("/"))
    data = urllib.parse.urlencode(params).encode()
    with urllib.request.urlopen(urllib.request.Request(url, data=data, method="POST"), timeout=timeout) as r:
        return json.load(r)


def _save_token(tok, expires_in):
    """갱신된 토큰을 keys.env에 되쓴다. 만료 예정일도 함께 적어 다음 갱신 판단에 쓴다."""
    stamp = int(time.time()) + int(expires_in or 0)
    lines, seen_t, seen_e = [], False, False
    for line in open(KEYS, encoding="utf-8"):
        if line.startswith("THREADS_TOKEN="):
            lines.append("THREADS_TOKEN=%s\n" % tok); seen_t = True
        elif line.startswith("THREADS_TOKEN_EXPIRES="):
            lines.append("THREADS_TOKEN_EXPIRES=%d\n" % stamp); seen_e = True
        else:
            lines.append(line)
    if not seen_t:
        lines.append("THREADS_TOKEN=%s\n" % tok)
    if not seen_e:
        lines.append("THREADS_TOKEN_EXPIRES=%d\n" % stamp)
    tmp = KEYS + ".tmp"
    open(tmp, "w", encoding="utf-8").writelines(lines)
    os.chmod(tmp, 0o600)
    os.replace(tmp, KEYS)


def token():
    """유효 토큰을 돌려준다. 만료가 7일 안이면 먼저 갱신한다(시크릿 불필요)."""
    e = _env()
    tok = e.get("THREADS_TOKEN")
    if not tok:
        raise RuntimeError("keys.env에 THREADS_TOKEN이 없다")
    exp = int(e.get("THREADS_TOKEN_EXPIRES") or 0)
    if exp and exp - time.time() < REFRESH_BEFORE:
        try:
            d = _get("https://graph.threads.net/refresh_access_token"
                     "?grant_type=th_refresh_token&access_token=" + tok)
            if d.get("access_token"):
                _save_token(d["access_token"], d.get("expires_in"))
                print("[threads] 토큰 갱신 완료 (%d일 연장)" % (int(d.get("expires_in", 0)) / 86400), flush=True)
                return d["access_token"]
        except Exception as ex:
            print("[threads] 토큰 갱신 실패(계속 진행):", str(ex)[:120], flush=True)
    return tok


def publish(video_url, text, timeout_s=300):
    """R2 공개 URL의 mp4를 스레드에 올린다. 성공하면 permalink, 실패하면 예외."""
    tok = token()
    me = _get("%s/me?fields=id&access_token=%s" % (API, tok))["id"]
    cid = _post("%s/threads" % me, {
        "media_type": "VIDEO", "video_url": video_url,
        "text": text[:MAX_TEXT], "access_token": tok})["id"]
    # 컨테이너가 FINISHED가 될 때까지 기다린다 — 바로 발행하면 처리 중이라 실패한다
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        time.sleep(6)
        st = _get("%s/%s?fields=status,error_message&access_token=%s" % (API, cid, tok))
        s = st.get("status")
        if s == "FINISHED":
            break
        if s == "ERROR":
            raise RuntimeError("스레드 미디어 처리 실패: %s" % st.get("error_message"))
    else:
        raise RuntimeError("스레드 미디어 처리 시간 초과(%ds)" % timeout_s)
    pid = _post("%s/threads_publish" % me, {"creation_id": cid, "access_token": tok})["id"]
    link = _get("%s/%s?fields=permalink&access_token=%s" % (API, pid, tok)).get("permalink")
    return link or ("https://www.threads.net/@syusyu_channel/post/" + pid)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        sys.exit("사용: upload_threads.py <video_url> <text>")
    print(publish(sys.argv[1], sys.argv[2]))
