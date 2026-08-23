#!/usr/bin/env python3
# 인스타 해시태그 인기 게시물 스캔 (2026-08-18 디렉터: "해시태그 그거도 만들어 놔")
#
# IG API에는 유튜브 mostPopular 같은 트렌딩 피드가 없다. 유일한 공식 통로가
# 해시태그 검색(ig_hashtag_search) → 인기 게시물(top_media)이다.
#
# ⛔ 2026-08-18 현재 **사용 불가** — 우리 토큰은 Instagram 로그인 방식(graph.instagram.com)인데
#   해시태그 검색은 Facebook 로그인 방식(graph.facebook.com + FB 페이지 연결 계정)에서만 지원된다.
#   활성화하려면: ①FB 페이지 생성 ②인스타 계정을 페이지에 연결 ③앱에 FB 로그인 추가 + 새 토큰
#   → 그 후 이 파일의 G를 graph.facebook.com으로 바꾸고 새 토큰 사용. 그때까지 슬롯 절차에 미배선.
# ⚠️ 제약: 계정당 **7일 창에서 고유 해시태그 30개까지만** 조회 가능 — 태그 묶음을 작게 유지.
#          조회수는 안 주고 좋아요·댓글 수만 준다(인기 순위 파악용으로 충분).
#
# 사용: .venv/bin/python3 pipeline/ig_hashtags.py [태그 ...]   (기본: TAGS)
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
G = "https://graph.instagram.com/v23.0"

# 지식 릴스판 기본 묶음 — 주 30개 한도 안에서 유지 (6개 × 매일 돌려도 6개 고유)
TAGS = ["상식", "지식", "꿀팁", "정보", "알쓸신잡", "오늘의지식"]
KST = timezone(timedelta(hours=9))


def _env():
    out = {}
    for line in open(os.path.join(ROOT, "keys.env"), encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"')
    return out


def _get(url):
    with urllib.request.urlopen(url, timeout=40) as r:
        return json.load(r)


def top_media(tag, user_id, token, limit=6):
    """해시태그의 인기 게시물 — (좋아요, 댓글, 캡션 첫 줄, 링크, 게시시각) 리스트."""
    q = urllib.parse.quote(tag)
    d = _get(f"{G}/ig_hashtag_search?user_id={user_id}&q={q}&access_token={token}")
    if not d.get("data"):
        return []
    hid = d["data"][0]["id"]
    m = _get(f"{G}/{hid}/top_media?user_id={user_id}"
             f"&fields=like_count,comments_count,caption,permalink,timestamp,media_type"
             f"&limit={limit}&access_token={token}")
    out = []
    for it in m.get("data", []):
        ts = it.get("timestamp", "")
        try:
            k = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S%z").astimezone(KST).strftime("%m/%d")
        except ValueError:
            k = "?"
        out.append((it.get("like_count", 0), it.get("comments_count", 0),
                    (it.get("caption") or "").split("\n")[0][:48],
                    it.get("permalink", ""), k))
    out.sort(reverse=True)
    return out


def main():
    env = _env()
    uid, tok = env.get("IG_USER_ID"), env.get("IG_ACCESS_TOKEN")
    if not (uid and tok):
        sys.exit("keys.env에 IG_USER_ID / IG_ACCESS_TOKEN 필요")
    tags = sys.argv[1:] or TAGS
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    print("# 인스타 해시태그 인기 게시물 — %s" % now)
    print("> 좋아요·댓글 순. 지식 릴스판에서 지금 도는 형식·소재 참고용. "
          "⚠️ 계정당 7일 창 고유 태그 30개 한도 — 태그를 함부로 늘리지 마라.\n")
    for tag in tags:
        print("## #%s" % tag)
        try:
            rows = top_media(tag, uid, tok)
            if not rows:
                print("- (결과 없음)")
            for lk, cm, cap, url, day in rows:
                print("- ♥%s 💬%s [%s] %s" % (format(lk, ","), cm, day, cap))
        except Exception as e:
            print("- 조회 실패: %s" % str(e)[:100])
        print()


if __name__ == "__main__":
    main()
