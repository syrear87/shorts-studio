#!/usr/bin/env python3
"""Blogger 자동 발행 (2026-08-27 신설).

왜 Blogger인가: 디렉터가 "자동화가 아니면 의미가 없다"고 못박았다. 후보를 다 재봤다.
  - 티스토리: 오픈API가 **2024-02 완전 종료**. 브라우저 자동화는 로그인 세션에 묶여
    무인 크론으로 못 돌린다 → 탈락.
  - 네이버 블로그: 글쓰기 API 자체가 없다 → 탈락.
  - 워드프레스: REST API로 되지만 호스팅·도메인 비용이 든다 → 검증 후 이전 대상.
  - **Blogger API v3**: 현역(최신 rev 2026-07), 무료, 그리고 우리가 이미 쓰는
    구글 OAuth를 그대로 쓴다(token.json에 blogger 스코프만 추가). → 채택.

블로그 '생성'은 API가 지원하지 않는다 — blogger.com에서 한 번 만들어야 한다.
이 모듈이 하는 일은 글 발행뿐이다.

기본이 **초안(draft) 발행**인 이유: 무인 생성 글을 그대로 공개하면 팩트 사고가
  그대로 나간다. 거제 만조·수능 4억·네팔 편이 전부 공개된 뒤에야 잡혔다. 블로그 글은
  검색에 영구히 남아 SNS 글보다 회수가 어렵다. 공개는 --publish를 명시할 때만 한다.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))

SCOPE = "https://www.googleapis.com/auth/blogger"


def _service():
    from googleapiclient.discovery import build
    from google_creds import load_creds
    return build("blogger", "v3", credentials=load_creds(require_scope=SCOPE))


def blogs():
    """이 계정이 쓸 수 있는 블로그 목록 [(id, name, url), ...]."""
    svc = _service()
    d = svc.blogs().listByUser(userId="self").execute()
    return [(b["id"], b.get("name"), b.get("url")) for b in d.get("items", [])]


def _from_keys():
    """keys.env의 BLOGGER_BLOG_ID (다른 모듈들과 같은 설정 위치)."""
    try:
        with open(os.path.join(ROOT, "keys.env"), encoding="utf-8") as f:
            for line in f:
                k, _, v = line.partition("=")
                if k.strip() == "BLOGGER_BLOG_ID":
                    return v.strip()
    except Exception:
        pass
    return None


def resolve_blog_id(blog_id=None):
    """blog_id를 정한다 — 인자 > 환경변수 BLOGGER_BLOG_ID > 계정에 블로그가 하나뿐이면 그것."""
    if blog_id:
        return blog_id
    env = os.environ.get("BLOGGER_BLOG_ID") or _from_keys()
    if env:
        return env
    found = blogs()
    if len(found) == 1:
        return found[0][0]
    if not found:
        sys.exit("이 계정에 블로그가 없다 — blogger.com에서 먼저 하나 만들어라")
    sys.exit("블로그가 여러 개다. BLOGGER_BLOG_ID를 지정하라:\n" +
             "\n".join("  %s  %s  %s" % b for b in found))


def publish(title, html, labels=(), blog_id=None, draft=True):
    """글 발행 → 결과 dict. draft=True면 초안으로만 저장한다(기본).

    labels: 블로거 라벨(카테고리 역할).
    """
    if not (title or "").strip():
        raise ValueError("제목이 비었다")
    if not (html or "").strip():
        raise ValueError("본문이 비었다")
    svc = _service()
    bid = resolve_blog_id(blog_id)
    body = {"title": title, "content": html}
    if labels:
        body["labels"] = list(labels)
    post = svc.posts().insert(blogId=bid, body=body, isDraft=bool(draft)).execute()
    return {"id": post.get("id"), "url": post.get("url"),
            "status": "draft" if draft else "live", "blog_id": bid}


def get(post_id, blog_id=None):
    """글 하나를 본문까지 읽어온다."""
    return _service().posts().get(blogId=resolve_blog_id(blog_id), postId=str(post_id)).execute()


def update(post_id, title=None, html=None, labels=None, blog_id=None):
    """이미 발행된 글을 고친다 (2026-09-06 신설).

    왜 필요한가: 초기 86편에 마크다운 잔재(`**볼드**`)와 빈 alt가 그대로 박혀 있었다.
    발행 시점 코드를 고쳐도 **이미 나간 글은 그대로 남는다** — 검색엔진이 보는 건
    지금 올라가 있는 HTML이다. 고칠 수단이 없으면 초기 글은 영영 기계 티를 달고 있다.

    None인 항목은 건드리지 않는다 — 부분 수정이 기본이다.
    """
    svc = _service()
    bid = resolve_blog_id(blog_id)
    cur = svc.posts().get(blogId=bid, postId=str(post_id)).execute()
    body = {"id": str(post_id),
            "title": title if title is not None else cur.get("title"),
            "content": html if html is not None else cur.get("content")}
    if labels is not None:
        body["labels"] = list(labels)
    elif cur.get("labels"):
        body["labels"] = cur["labels"]
    post = svc.posts().update(blogId=bid, postId=str(post_id), body=body).execute()
    return {"id": post.get("id"), "url": post.get("url"), "blog_id": bid}


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--list" in sys.argv:
        for b in blogs():
            print("%s  %s  %s" % b)
        return
    if len(args) < 2:
        sys.exit("사용: upload_blogger.py <제목> <본문.html> [--publish] [--label 라벨]\n"
                 "      upload_blogger.py --list")
    title, path = args[0], args[1]
    with open(path, encoding="utf-8") as f:
        html = f.read()
    labels = []
    if "--label" in sys.argv:
        i = sys.argv.index("--label")
        if i + 1 < len(sys.argv):
            labels = [sys.argv[i + 1]]
    r = publish(title, html, labels=labels, draft="--publish" not in sys.argv)
    print("%s: %s" % ("공개 발행" if r["status"] == "live" else "초안 저장", r["url"] or r["id"]))


if __name__ == "__main__":
    main()
