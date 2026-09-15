#!/usr/bin/env python3
"""블로그 초안을 하루 N편씩 나눠 공개한다 (2026-08-27 디렉터 지시: "하루 5편씩 발행").

왜 나눠 올리나 — 구글 **scaled content abuse** 정책 때문이다:
  - '편집자 검토 없이 AI 페이지를 대량 발행'이 명시적 위반이고, 2026년 3월 단속에서
    해당 사이트들이 트래픽 50~80%를 잃었다. 회복에 3~6개월이 걸린다.
  - 애드센스 승인 요건에도 '사람이 AI 결과물을 발행 전 검토할 것'이 들어 있다.
  - 문제는 AI를 썼다는 사실이 아니라 **한꺼번에 쏟아내는 패턴**이다.
  초안은 검색에 잡히지 않으므로 아무리 쌓아도 무해하다. 조절할 것은 발행 속도뿐이다.

하루 한 번만 돈다 — 스탬프 파일로 같은 날 재실행을 막는다(러너가 여러 번 불러도 안전).
"""
import datetime
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
STAMP = os.path.join(ROOT, "logs", "blog_published.json")
# 발행 정지 스위치 (2026-09-10 디렉터 지시). 이 파일이 있으면 공개를 하지 않는다.
# 왜: 서치콘솔 확인 결과 94편 중 **색인 생성 0편**이고, 85편이 "발견됨 - 현재 색인이
# 생성되지 않음"이다 — 구글이 URL은 알면서 크롤링조차 하지 않기로 한 상태다.
# 이 상태에서 페이지를 더 늘리면 '대량 생산' 신호만 강해진다. 색인이 잡히기 시작할
# 때까지 멈춘다. 초안 생성(blog_autogen)은 계속한다 — 초안은 검색에 안 잡혀 무해하고,
# 재개할 때 바로 나갈 재고가 된다.
# 재개: rm logs/.blog_publish_paused
PAUSE = os.path.join(ROOT, "logs", ".blog_publish_paused")
# 하루 발행 편수. 최근 7일 실측 공급이 7.7편/일(카드 8.0장 중 테크 게이트 통과분)이라
# 5편으로는 매일 2.7편씩 적체가 늘어난다. 8편이면 신규를 소화하면서 밀린 초안도 조금씩 준다.
# 2026-09-05 어벤져스 권고: 하루 8편 자동 발행은 구글 scaled content abuse 프로필이다
# (86편이 동일 H2 골격·alt 공백 75편). 색인·애드센스 심사 전까지 3편으로 낮춘다.
PER_DAY = 3


def _stamp():
    try:
        with open(STAMP, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save(d):
    os.makedirs(os.path.dirname(STAMP), exist_ok=True)
    tmp = STAMP + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STAMP)


def _source_meta(post):
    """초안 → 원본 카드 원고. autogen이 남긴 `<!-- src:파일 -->` 표식이 우선, 없으면(9/15 이전
    초안) 카드 topic과 제목의 낱말 겹침으로 찾는다."""
    import glob
    import re as _re
    content = post.get("content") or ""
    m = _re.search(r"<!-- src:(cards-[\w.\-]+\.json) -->", content)
    cands = [os.path.join(ROOT, "content", m.group(1))] if m else \
        sorted(glob.glob(os.path.join(ROOT, "content", "cards-*.json")), reverse=True)
    if m and not os.path.exists(cands[0]):
        return None
    from blog_dedup import is_dup
    title = (post.get("title") or "").strip()
    for path in cands:
        try:
            with open(path, encoding="utf-8") as f:
                meta = json.load(f)
        except Exception:
            continue
        if m:
            return meta
        dup, _hit, _w = is_dup(title, [str(meta.get("topic") or "")])
        if dup:
            return meta
    return None


def _photo_queries(text):
    """한국어 제목/topic → Pexels용 영어 검색어 2개. 원 경로는 원고 생성 때 Gemini가
    `PHOTOS:` 줄로 주지만 초안엔 남지 않는다 — 한국어 검색은 Pexels에서 0건이라 다시 뽑는다."""
    import re as _re
    from make_blog import _gemini
    try:
        out = _gemini("다음 글 제목에 어울리는 Pexels 스톡 사진 검색어를 영어로 2개, "
                      "각 2~4 단어, ' | '로만 구분해 한 줄로 답해라. 브랜드명·모델명은 빼고 "
                      "일반 사물·장면으로. 제목: %s" % text[:120], timeout=60)
        qs = [_re.sub(r"[^A-Za-z0-9 ]", " ", q).strip() for q in out.strip().splitlines()[0].split("|")]
        return [q for q in qs if q][:2]
    except Exception as e:
        print("  [검색어 생성 실패] %s" % str(e)[:60])
        return []


def _ensure_images(svc, bid, post, dry):
    """이미지 없는 초안에 현행 게이트로 사진을 소급한다. 발행해도 되면 True.

    ① 이미 <img>가 있다 → 그대로.
    ② 원고를 찾으면 make_blog.pick_images(현행 정책: 실물 → 특정 제품이면 없음 → 스톡).
       특정 제품이라 정책상 이미지가 없는 글은 그대로 발행(9/13 결정).
    ③ 원고를 못 찾으면 제목으로 스톡 검색.
    ④ 그래도 0장이면(Pexels 장애 등) 이번 슬롯은 미루고 초안으로 남긴다."""
    import re as _re
    content = post.get("content") or ""
    if _re.search(r"<img\b", content):
        return True
    title = (post.get("title") or "").strip()
    try:
        from make_blog import pick_images, decorate, specific_product
        meta = _source_meta(post)
        if meta:
            imgs = pick_images(meta, _photo_queries(str(meta.get("topic") or title)))
            if not imgs and specific_product(meta):
                print("  [이미지 없음·정책] 특정 제품 글, 실물 없음 — 그대로 발행: %s" % title[:40])
                return True
        else:
            from blog_media import photos_for
            imgs = [(u, "참고 이미지 · " + (c or ""))
                    for u, c in photos_for(_photo_queries(title) or [title[:60]], count=3)]
    except Exception as e:
        print("  [이미지 소급 실패] %s — %s" % (title[:40], str(e)[:80]))
        imgs = []
    if not imgs:
        print("  [연기·사진 0장] %s — 다음 슬롯 재시도" % title[:44])
        return False
    html = decorate(content, imgs)
    if dry:
        print("  [dry·이미지 %d장 소급 예정] %s" % (len(imgs), title[:44]))
        return True
    try:
        body = {"kind": "blogger#post", "id": post["id"], "title": post.get("title"),
                "content": html}
        if post.get("labels"):
            body["labels"] = post["labels"]
        svc.posts().update(blogId=bid, postId=post["id"], body=body).execute()
        post["content"] = html
        print("  [이미지 %d장 소급] %s" % (len(imgs), title[:44]))
        return True
    except Exception as e:
        print("  [연기·초안 갱신 실패] %s — %s" % (title[:40], str(e)[:80]))
        return False


def run(per_day=PER_DAY, force=False, dry=False):
    from upload_blogger import _service, resolve_blog_id, _dry
    dry = dry or _dry()          # DRY_RUN=1 환경변수도 dry다 (2026-09-06) — 공개·삭제가 실제로 나가는 경로
    if os.path.exists(PAUSE) and not force:
        why = ""
        try:
            why = open(PAUSE, encoding="utf-8").read().strip()[:200]
        except Exception:
            pass
        print("블로그 발행 정지 중 — 건너뜀%s" % (("\n  사유: " + why) if why else ""))
        return 0
    today = datetime.date.today().isoformat()
    st = _stamp()
    if st.get("date") == today and not force:
        print("오늘(%s) 이미 %d편 발행함 — 건너뜀" % (today, st.get("count", 0)))
        return 0

    # 카드가 게시 직전에 자기 글을 공개한다(blog_link). 그만큼 여기서 빼지 않으면
    # 하루 발행량이 두 배가 된다 (2026-09-11).
    try:
        from blog_link import published_today as _card_pub
        _already = _card_pub()
    except Exception:
        _already = 0
    if _already:
        per_day = max(0, per_day - _already)
        print("카드 경로로 오늘 %d편 공개됨 — 남은 쿼터 %d편" % (_already, per_day))
    if per_day <= 0:
        print("오늘 쿼터 소진 — 건너뜀")
        return 0

    svc = _service()
    bid = resolve_blog_id()
    # 초안을 전부 가져와 **시의성 순**으로 고른다 (2026-08-27 디렉터 지시).
    # 생성 순서대로 내보내면 '9월 9일 애플 이벤트' 같은 글이 9월 10일에 나갈 수 있다.
    items = []
    tok = None
    while True:
        kw = {"blogId": bid, "status": "DRAFT", "fetchBodies": True, "maxResults": 100}
        if tok:
            kw["pageToken"] = tok
        d = svc.posts().list(**kw).execute()
        items += d.get("items", [])
        tok = d.get("nextPageToken")
        if not tok:
            break
    if not items:
        print("발행할 초안이 없다")
        return 0

    import re as _re
    from blog_priority import order
    from blog_dedup import is_dup
    ranked = order(items, key=lambda p: (p.get("title") or "") + " " +
                   _re.sub(r"<[^>]+>", " ", p.get("content") or ""))

    # ── 발행 직전 중복 검사 (2026-08-28 실사고) ────────────────────────────
    # blog_dedup은 autogen의 **신규 초안**에만 걸린다. 이미 쌓인 중복 초안은 여기 발행
    # 슬라이스를 무검사로 통과해, 젠하이저 MOMENTUM 글 2편이 **같은 날 동시 공개**됐다.
    # 공개 글 전체와 대조해 중복 초안은 발행하지 않고 삭제한다(중복 초안 삭제는
    # 2026-08-27 디렉터 승인 방식 — 남겨두면 매일 다시 걸리며 목록을 막는다).
    live_texts = []
    tok = None
    while True:
        kw = {"blogId": bid, "status": "LIVE", "fetchBodies": False, "maxResults": 100}
        if tok:
            kw["pageToken"] = tok
        d = svc.posts().list(**kw).execute()
        for lp in d.get("items", []):
            # 제목만 — 본문을 섞으면 한국어 활용형이 우연히 겹쳐 전 초안이 오탐된다 (2026-08-28)
            live_texts.append((lp.get("title") or "").strip())
        tok = d.get("nextPageToken")
        if not tok:
            break

    LABEL = {0: "D-0~2 임박", 1: "일주일 내", 2: "한 달 내", 3: "먼 예정",
             4: "시점 무관", 5: "지난 날짜"}
    picked = []
    picked_titles = []          # 같은 실행 안에서 뽑힌 제목 — live와 구분해서 다룬다
    for r, left, p in ranked:
        if len(picked) >= per_day:
            break
        probe = ((p.get("title") or "") + " " +
                 _re.sub(r"<[^>]+>", " ", p.get("content") or "")[:150]).strip()
        # ① 이미 공개된 글과 겹침 → 진짜 중복이므로 초안을 삭제한다
        dupflag, hit, words = is_dup(probe, live_texts)
        if dupflag:
            if not dry:
                try:
                    svc.posts().delete(blogId=bid, postId=p["id"]).execute()
                    print("  [중복 삭제] %s ↔ '%s' (%s)" % (
                        (p.get("title") or "")[:40], hit.split("  ")[0][:30],
                        ", ".join(words[:4])))
                except Exception as e:
                    print("  [중복 스킵·삭제실패] %s — %s" % ((p.get("title") or "")[:40],
                                                            str(e)[:60]))
            else:
                print("  [dry·중복삭제대상] %s" % (p.get("title") or "")[:44])
            continue
        # ② 오늘 뽑힌 글과만 겹침 → 중복이 아니라 '같은 날 비슷한 글 2편'이다.
        #    삭제하면 안 되고(2026-08-28 재감사: 액션 피규어↔여행 포스터가 챗GPT 계열로
        #    묶여 삭제될 뻔), 초안으로 남겨 **다음 날로 미룬다** — 분산이 목적에도 맞다.
        soft, hit2, _w2 = is_dup(probe, picked_titles)
        if soft:
            print("  [오늘 연기] %s ↔ 오늘자 '%s'" % ((p.get("title") or "")[:38],
                                                    (hit2 or "")[:28]))
            continue
        picked.append(p)
        picked_titles.append((p.get("title") or "").strip())
        print("  [%s D%+d] %s" % (LABEL.get(r, "?"), left, (p.get("title") or "")[:44]))
    print("초안 %d편 → 발행 대상 %d편" % (len(items), len(picked)))
    items = picked

    done = []
    for p in items:
        # 초안은 생성 당시 게이트로 굳어 있다 — 게이트가 바뀐 뒤 발행되면 옛 판정이 그대로
        # 나간다 (2026-09-15 실사고: 9/9 "제품 글이라 이미지 없이" 만든 HDMI 케이블 초안이
        # 9/13 카테고리 스톡 허용 뒤인 9/15에 사진 없이 공개). 발행 직전에 다시 판정한다.
        if not _ensure_images(svc, bid, p, dry):
            continue
        if dry:
            print("[dry] %s" % (p.get("title") or "")[:52])
            continue
        try:
            r = svc.posts().publish(blogId=bid, postId=p["id"]).execute()
            done.append(r.get("title"))
            print("공개: %s\n      %s" % ((r.get("title") or "")[:52], r.get("url")))
        except Exception as e:
            print("실패: %s — %s" % ((p.get("title") or "")[:36], str(e)[:80]))
    if dry:
        return len(items)

    if not done and items:
        # 전부 실패(토큰 만료·API 장애) — 스탬프를 찍으면 그날이 '완료'로 오인돼
        # 이후 슬롯이 전부 건너뛴다 (2026-08-28 감사). 찍지 않아야 다음 슬롯이 재시도한다.
        print("⚠️ 발행 0편 (%d편 시도 전부 실패) — 스탬프 미기록, 다음 슬롯 재시도" % len(items))
        try:
            import subprocess
            subprocess.run(["bash", os.path.join(ROOT, "bin", "tg-send.sh"),
                            "⚠️ 블로그 발행 전부 실패(%d편) — 다음 슬롯 재시도" % len(items)],
                           timeout=30)
        except Exception:
            pass
        return 0
    if not done:
        # 초안이 있었는데 전부 중복 삭제·연기로 걸러져 0편이 됐다. 여기서 스탬프를 찍으면
        # 그날이 '완료'로 도장돼 이후 슬롯이 전부 건너뛴다 — 오전에 초안이 비면 그날 블로그가
        # 통째로 봉인된다 (2026-09-09 실사고: date=9/9 count=0, 이후 다섯 슬롯 전부 스킵).
        print("발행 0편 — 스탬프 미기록, 다음 슬롯 재시도")
        return 0
    _save({"date": today, "count": len(done), "titles": done})
    if done:
        # 알림은 실제 발행이 있을 때만 — 러너 쪽에서 쏘면 rc=0(스킵 포함)마다 오발송된다
        # (2026-08-28 실사고: 하루 8번 가짜 "발행 완료" 텔레그램)
        try:
            import subprocess
            subprocess.run(["bash", os.path.join(ROOT, "bin", "tg-send.sh"),
                            "📝 블로그 %d편 공개 (시의성 순 분산 발행)" % len(done)],
                           timeout=30)
        except Exception as e:
            print("[blog] 알림 실패(무해): %s" % str(e)[:80])
    left = svc.posts().list(blogId=bid, status="DRAFT", fetchBodies=False,
                            maxResults=1).execute()
    print("\n%d편 공개 · 남은 초안 있음: %s" % (len(done), bool(left.get("items"))))
    return len(done)


if __name__ == "__main__":
    n = PER_DAY
    for a in sys.argv[1:]:
        if a.isdigit():
            n = int(a)
    run(per_day=n, force="--force" in sys.argv, dry="--dry" in sys.argv)
