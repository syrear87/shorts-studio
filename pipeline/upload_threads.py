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
import re
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
    # DRY_RUN=1 이면 실제 API를 치지 않는다 (2026-09-05 실사고: 세션이 게이트 검증용으로
    # publish_text('x')를 호출했는데 그대로 라이브 계정에 'x'가 게시됐다 — 디렉터 발견).
    # 모든 게시·답글이 이 함수를 지나므로 여기 한 곳이 테스트 안전선이다.
    if os.environ.get("DRY_RUN") in ("1", "true", "True"):
        print("[threads][DRY_RUN] POST %s %s" % (path, {k: (str(v)[:60] if k != "access_token" else "***")
                                                       for k, v in params.items()}), flush=True)
        return {"id": "dryrun-" + path.replace("/", "_")[-24:]}
    url = "%s/%s" % (API, path.lstrip("/"))
    data = urllib.parse.urlencode(params).encode()
    with urllib.request.urlopen(urllib.request.Request(url, data=data, method="POST"), timeout=timeout) as r:
        return json.load(r)


def _save_token(tok, expires_in):
    """갱신된 토큰을 keys.env에 되쓴다. 만료 예정일도 함께 적어 다음 갱신 판단에 쓴다."""
    from keyfile import locked
    with locked():   # 읽기~교체 전체를 직렬화 (2026-08-25 감사: IG 갱신과 lost update 경쟁)
        _save_token_locked(tok, expires_in)


def _save_token_locked(tok, expires_in):
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
    # ⚠️ keys.env 전체(전 채널 자격증명)를 재작성하는 경로다 — flush 보장 없이 os.replace가 먼저
    # 실행되면 잘린 keys.env가 정본이 된다. with로 닫고 나서 교체한다 (2026-08-25 감사).
    with open(tmp, "w", encoding="utf-8") as f:
        f.writelines(lines)
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


def _create(me, tok, params):
    params["access_token"] = tok
    return _post("%s/threads" % me, params)["id"]


def _publish_container(me, tok, cid):
    pid = _post("%s/threads_publish" % me, {"creation_id": cid, "access_token": tok})["id"]
    return pid


def publish_image(image_url, text, replies=()):
    """이미지 1장 스레드 게시 (2026-08-20 — 카드도 스레드에 올린다: 제휴봇이
    IG 캡션 첫 줄로 스레드 글을 찾아 쿠팡 링크 답글을 달기 때문. IG API 게시는
    앱과 달리 스레드 자동 공유가 없어 여기서 직접 올린다)."""
    tok = token()
    me = _get("%s/me?fields=id&access_token=%s" % (API, tok))["id"]
    cid = _create(me, tok, {"media_type": "IMAGE", "image_url": image_url,
                            "text": text[:MAX_TEXT]})
    return _publish_with_retry(me, tok, cid, "threads 이미지 게시 실패", replies=replies)


def _publish_with_retry(me, tok, cid, fail_msg, tries=6, replies=()):
    """컨테이너 발행 재시도 후 permalink 조회 (2026-08-23 감사: permalink 조회 실패가
    발행 성공을 뒤집고 같은 컨테이너를 재발행하던 것 분리 — 조회 실패는 성공을 뒤집지 않는다).

    replies: 발행 뒤 이어 달 답글들 (2026-08-27 — 카드 경로에도 쿠팡 링크를 달 수 있게.
      publish()에만 답글 체인이 있어서, 본문 상한을 넘긴 카드는 링크를 붙일 방법이 없었다)."""
    last, pid = None, None
    for _ in range(tries):
        time.sleep(4)
        try:
            pid = _publish_container(me, tok, cid)
            break
        except Exception as e:
            last = e
    if pid is None:
        raise RuntimeError("%s: %s" % (fail_msg, str(last)[:150]))
    parent = pid
    for r in replies:
        if not str(r).strip():
            continue
        try:
            rid = _create(me, tok, {"media_type": "TEXT", "text": str(r)[:MAX_TEXT],
                                    "reply_to_id": parent})
            time.sleep(2)
            parent = _publish_container(me, tok, rid)
        except Exception as e:
            print("[threads] 답글 실패(본문은 게시됨):", str(e)[:150], flush=True)
            break
    try:
        link = _get("%s/%s?fields=permalink&access_token=%s" % (API, pid, tok)).get("permalink")
    except Exception:
        link = None
    return link or pid


def publish_text(text):
    """텍스트 단독 게시 (2026-08-23 스레드 성장 연구 — 네이티브 리스트형 글용).

    2026-09-05: 영상 세션이 이 함수로 영화 소식을 스레드에 올려 계정 성격이 깨졌다
    (「나홍진 호프」 — 테크 카드 사이에 영화 글). 스레드는 카드 라인 전용이므로,
    카드 슬롯이 아닌 세션에서 부르면 거부한다. 결산·수동 글은 CARD_MODE=1로 실행하라.
    """
    import os
    if os.environ.get("CARD_MODE") not in ("1", "true", "True"):
        raise RuntimeError(
            "스레드 텍스트 게시는 카드 라인 전용이다 (2026-09-05). "
            "영상 세션은 유튜브·인스타에만 게시하라. "
            "결산 등 의도된 수동 게시라면 CARD_MODE=1 로 실행할 것.")
    tok = token()
    me = _get("%s/me?fields=id&access_token=%s" % (API, tok))["id"]
    cid = _create(me, tok, {"media_type": "TEXT", "text": text[:MAX_TEXT]})
    return _publish_with_retry(me, tok, cid, "threads 텍스트 게시 실패")


def publish_images(image_urls, text, replies=()):
    """이미지 여러 장 캐러셀 게시 (2026-08-22 디렉터: "쓰레드에는 사진이 한장만 게시되네?" —
    카드 캐러셀 전 장을 스레드에도 그대로 올린다). 1장이면 단장 게시로 폴백."""
    urls = [u for u in image_urls if u]
    if not urls:
        raise ValueError("이미지 URL이 없다")
    if len(urls) < 2:   # 스레드 캐러셀은 2장부터
        return publish_image(urls[0], text, replies=replies)
    tok = token()
    me = _get("%s/me?fields=id&access_token=%s" % (API, tok))["id"]
    children = [_create(me, tok, {"media_type": "IMAGE", "image_url": u,
                                  "is_carousel_item": "true"}) for u in urls[:20]]
    time.sleep(4)   # 자식 컨테이너 처리 대기
    car = _create(me, tok, {"media_type": "CAROUSEL", "children": ",".join(children),
                            "text": text[:MAX_TEXT]})
    return _publish_with_retry(me, tok, car, "threads 캐러셀 게시 실패", replies=replies)


def publish(video_url, text, timeout_s=300, replies=()):
    """R2 공개 URL의 mp4를 스레드에 올리고, 넘치는 본문은 답글로 이어붙인다.
    2026-08-16 디렉터: "캡션도 인스타와 동일하게" — 스레드 본문 상한이 500자라
    한 게시물에 다 넣을 수 없다. 첫 게시물에 도입부, 나머지는 자기 글 답글로 잇는다."""
    tok = token()
    me = _get("%s/me?fields=id&access_token=%s" % (API, tok))["id"]
    cid = _create(me, tok, {"media_type": "VIDEO", "video_url": video_url, "text": text[:MAX_TEXT]})
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
    # FINISHED 직후에도 발행이 '아직 준비 안 됨'으로 튕기는 경우가 있다(upload_instagram의 9007과 같은 계열).
    # 다른 경로(이미지·텍스트·캐러셀)는 전부 _publish_with_retry를 쓰는데 영상만 1회 호출이라
    # 2026-08-25 21시 별자리 편이 스레드에서 영상 첨부에 실패해 텍스트로 대체 게시됐다 —
    # 스레드는 쿠팡 링크가 클릭되는 통로이자 도달이 가장 큰 채널이라 손실이 크다. 같은 재시도를 적용한다.
    last, pid = None, None
    for _i in range(6):
        if _i:
            time.sleep(4)   # 첫 시도는 지연 없이 — 정상 경로를 4초 늦추지 않는다
        try:
            pid = _publish_container(me, tok, cid)
            break
        except Exception as e:
            last = e
            # 4xx는 재시도해도 같은 결과다(토큰 만료·권한·잘못된 컨테이너). 즉시 포기해
            # 24초를 태우지 않고, 서버가 이미 발행한 뒤 응답만 끊긴 경우의 중복 발행 위험도 줄인다.
            _code = getattr(e, "code", None)
            if isinstance(_code, int) and 400 <= _code < 500 and _code != 429:
                break
    if pid is None:
        raise RuntimeError("스레드 영상 게시 실패: %s" % str(last)[:150])
    # 답글 체인 — 각 답글은 바로 앞 글에 달아 하나의 실로 읽히게 한다
    parent = pid
    for r in replies:
        if not r.strip():
            continue
        try:
            rid = _create(me, tok, {"media_type": "TEXT", "text": r[:MAX_TEXT], "reply_to_id": parent})
            time.sleep(2)
            parent = _publish_container(me, tok, rid)
        except Exception as e:
            print("[threads] 답글 실패(본문은 게시됨):", str(e)[:150], flush=True)
            break
    try:
        link = _get("%s/%s?fields=permalink&access_token=%s" % (API, pid, tok)).get("permalink")
    except Exception:
        link = None   # 조회 실패는 게시 성공을 뒤집지 않는다 (2026-08-23 감사)
    # 폴백 URL의 username을 하드코딩하지 않는다 (2026-09-02: 계정명을 syusyu_channel →
    # daily_1_pick으로 바꾸면서 죽은 링크가 됐다). 계정 정보를 조회해 만들고, 그것도
    # 실패하면 링크 없이 게시 id만 돌려준다 — 잘못된 URL보다 없는 편이 낫다.
    if not link:
        try:
            _u = _get("%s/me?fields=username&access_token=%s" % (API, tok)).get("username")
            link = ("https://www.threads.net/@%s/post/%s" % (_u, pid)) if _u else pid
        except Exception:
            link = pid
    return link


def find_recent_post(caption_hint, limit=8):
    """내 최근 스레드 글 중 캡션 앞부분이 일치하는 글의 id를 찾는다 (2026-08-16).
    게시(슬롯 시각)와 제휴 링크 회신(디렉터가 나중) 사이에 시차가 있어,
    링크가 오면 그 편의 스레드 글을 되찾아 답글로 붙여야 하기 때문이다."""
    tok = token()
    me = _get("%s/me?fields=id&access_token=%s" % (API, tok))["id"]
    d = _get("%s/%s/threads?fields=id,text,timestamp&limit=%d&access_token=%s" % (API, me, limit, tok))
    # 스레드는 게시물당 해시태그를 하나만 허용해 **첫 해시태그의 #을 지운다**
    # ("…아닙니다 #장마 #날씨" → "…아닙니다 장마 #날씨"). 그래서 원문 그대로 비교하면 못 찾는다.
    # → 해시태그가 시작되기 전까지의 제목 부분만 비교한다 (2026-08-17 실사고).
    import re as _re
    def _core(t):
        t = _re.split(r"[#\n]", t or "", maxsplit=1)[0]
        return _re.sub(r"\s+", " ", t).strip()
    key = _core(caption_hint)[:22]
    if not key:
        return None
    for it in d.get("data") or []:
        if key and key in _core(it.get("text") or ""):
            return it["id"]
    return None


def reply_correction(parent_id, text, approved=False):
    """정정 답글 전용 — 디렉터 승인(approved=True) 없이는 게시하지 않는다 (2026-09-05 확정).

    왜 분리했나: reply_text는 쿠팡 링크 답글도 쓰는 통로라, 거기에 승인 검사를 걸면
    제휴 부착까지 막힌다. 정정만 따로 뺀다.
    왜 승인이 필요한가: **스레드 답글은 API로 삭제할 수 없다.** 잘못 쓴 정정문은
    되돌릴 방법이 없어 2차 사고가 된다(9/5 'x' 게시 사고에서 삭제 불가를 확인).
    형식은 기계로 검사하고, 게시 여부는 사람이 정한다.
    """
    problems = []
    t = (text or "").strip()
    if not t.startswith("[정정]"):
        problems.append("'[정정]'으로 시작하지 않음")
    if len(t) > MAX_TEXT:
        problems.append("%d자 (%d자 초과)" % (len(t), MAX_TEXT))
    if re.search(r"@\w|당신|여러분|님께서|말씀하신", t):
        problems.append("2인칭·멘션 포함 (특정인에게 답하지 말고 공지로 쓴다)")
    if not re.search(r"\d{4}[.\-년]|\d{1,2}월\s?\d{1,2}일|기준", t):
        problems.append("기준 시점 없음 (언제 확인한 값인지 밝혀라)")
    if problems:
        raise RuntimeError("정정문 형식 미달: " + " / ".join(problems))
    if not approved:
        raise RuntimeError(
            "정정 답글은 디렉터 승인이 필요하다 (2026-09-05 확정, 월 2건 이하).\n"
            "  절차: 정정문 초안을 텔레그램으로 보내고 'ok' 회신을 받은 뒤 approved=True로 호출.\n"
            "  스레드 답글은 삭제가 불가능해 잘못 쓰면 되돌릴 수 없다.\n"
            "  초안:\n" + t)
    return reply_text(parent_id, t)


def reply_text(parent_id, text):
    """기존 글에 텍스트 답글을 단다."""
    tok = token()
    me = _get("%s/me?fields=id&access_token=%s" % (API, tok))["id"]
    cid = _create(me, tok, {"media_type": "TEXT", "text": text[:MAX_TEXT], "reply_to_id": parent_id})
    time.sleep(2)
    return _publish_container(me, tok, cid)




# 팔로우 유도 확인 기능은 제거했다 (2026-08-31 디렉터: "그냥 그런 문구 하지 말자.. 짜친다").
# 8/28에 넣었다가 실제로 나가는 글을 보고 되돌렸다 — 스레드 본문은 출처 괄호로 끝낸다.


# CLI 진입점은 파일 맨 끝에 둔다 (2026-08-28 감사: 모듈 하단 정의보다 위에 있어
# `python3 upload_threads.py <url> <text>` 수동 재게시가 100% NameError로 죽었다.
# import 경유는 모듈 전체가 먼저 실행돼 무사했지만, CLI는 정의 전에 publish()를 불렀다.)
if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        sys.exit("사용: upload_threads.py <video_url> <text>")
    print(publish(sys.argv[1], sys.argv[2]))
