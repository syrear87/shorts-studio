#!/usr/bin/env python3
"""새 카드 원고 → 블로그 초안 자동 생성 (2026-08-27 신설).

왜 필요한가: 초기 65편은 배치로 만든 것이고, 러너에는 **발행**만 붙어 있었다.
  그대로 두면 초안이 소진되는 순간 블로그가 멈춘다. 디렉터 지적:
  "5편씩 공개를 해도 매일 테크 카드는 쌓이는데" — 공급 쪽이 자동이어야 구조가 스스로 돈다.

무엇을 만드나: content/cards-*.json 중 **아직 블로그 글이 없는** 테크 카드를 골라
  make_blog로 초안을 만든다. 발행은 하지 않는다(publish_blog_daily가 시의성 순으로 내보낸다).

생성 이력은 logs/blog_generated.txt에 남긴다 — 같은 카드로 두 번 만들지 않기 위해서다.
  블로그 쪽 제목으로 대조하지 않는 이유: 모델이 매번 다른 제목을 지어 대조가 불안정하다.
"""
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
DONE_F = os.path.join(ROOT, "logs", "blog_generated.txt")
FAIL_F = os.path.join(ROOT, "logs", "blog_gen_fail.json")
MAX_FAIL = 3             # 이만큼 실패하면 포기 — 원고가 짧아 게이트에 막히는 카드는 계속 실패한다
MAX_PER_RUN = 2          # 한 슬롯에서 최대 몇 편까지 만들지 — Gemini 쿼터와 슬롯 시간 보호
                         # 2026-09-06: 3→2. blog_gate에 검색 의도 판정이 붙어 카드의 52%만
                         # 통과한다(종전엔 테크면 거의 전부). 후보가 절반이 됐는데 상한을
                         # 그대로 두면 게이트에 막힌 카드를 매 슬롯 다시 시도하며 헛돈다.


def _done():
    try:
        with open(DONE_F, encoding="utf-8") as f:
            return {l.strip() for l in f if l.strip()}
    except Exception:
        return set()


def _fails():
    try:
        with open(FAIL_F, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _bump_fail(name):
    d = _fails()
    d[name] = d.get(name, 0) + 1
    os.makedirs(os.path.dirname(FAIL_F), exist_ok=True)
    tmp = FAIL_F + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, FAIL_F)
    return d[name]


def _mark(name):
    os.makedirs(os.path.dirname(DONE_F), exist_ok=True)
    with open(DONE_F, "a", encoding="utf-8") as f:
        f.write(name + "\n")


def _rendered_ok():
    p = os.path.join(ROOT, "logs", "cards_ok.txt")
    try:
        return set(l.strip() for l in open(p, encoding="utf-8") if l.strip())
    except Exception:
        return set()


def pending():
    """아직 블로그 글이 없는 테크 카드 목록 (최신순)."""
    from blog_gate import judge
    done = _done()
    fails = _fails()
    out = []
    for f in sorted(glob.glob(os.path.join(ROOT, "content", "cards-*.json")), reverse=True):
        name = os.path.basename(f)
        if name in done or fails.get(name, 0) >= MAX_FAIL:
            continue
        # 2026-09-06부터의 카드는 make_cards 게이트를 **통과한 것만** 블로그로 간다(logs/cards_ok.txt).
        # 그 전 카드는 정본이 없어 그대로 둔다 — 없는 기록으로 과거를 막으면 공급이 끊긴다.
        m = re.search(r"(\d{4}-\d{2}-\d{2})", name)
        if m and m.group(1) >= "2026-09-06" and name not in _rendered_ok():
            continue
        try:
            with open(f, encoding="utf-8") as fh:
                meta = json.load(fh)
        except Exception:
            continue
        if not judge(meta, is_card=True)[0]:
            continue
        # 가격 게이트 (2026-09-13). 카드는 make_cards 렌더 때 이 게이트를 지나지만, 여기서
        # 되살리는 **옛 카드**(게이트 도입 전)는 안 지났다. 9/4 SSD 편 — 답글 25건 중 11건이
        # 반박이었고 가격 게이트가 6개 사유로 기각하는 카드 — 이 틈으로 블로그 글이 됐다.
        # 블로그는 검색에 오래 남아 회수가 더 어렵다. 카드로 못 나갈 소재는 블로그로도 안 간다.
        try:
            from price_gate import check as _pcheck
            if _pcheck(meta)[0] == "reject":
                continue
        except Exception:
            pass
        out.append(f)
    return out


def existing_titles():
    """이미 있는 글의 제목 + 본문 앞부분 — 중복 판정 기준.

    제목만 비교하면 표현이 다른 같은 사건을 놓친다 (2026-08-28 실사고: 카메라 에어팟 유출이
    「애플 차세대 에어팟 유출: 카메라 탑재 Visual Intelligence」와 「에어팟에 카메라가 달린다 —
    macOS 업데이트에서 포착」 두 편으로 나갔는데, 제목끼리는 겹치는 낱말이 0개였다).
    본문 앞부분까지 넣어 사건의 실체가 비교되게 한다.
    """
    from upload_blogger import _service, resolve_blog_id
    svc = _service()
    bid = resolve_blog_id()
    out = []
    for status in ("LIVE", "DRAFT"):
        tok = None
        while True:
            kw = {"blogId": bid, "status": status, "fetchBodies": False, "maxResults": 100}
            if tok:
                kw["pageToken"] = tok
            d = svc.posts().list(**kw).execute()
            for p in d.get("items", []):
                # 제목만 — 본문 비교는 활용형 오탐으로 실물 카드를 죽였다 (2026-08-28 감사)
                out.append((p.get("title") or "").strip())
            tok = d.get("nextPageToken")
            if not tok:
                break
    return out


def run(limit=MAX_PER_RUN):
    from make_blog import build
    from upload_blogger import publish
    from blog_dedup import is_dup
    todo = pending()[:limit]
    if not todo:
        return 0
    # 카드 쪽 쿨다운이 뚫리면 중복 카드가 그대로 넘어온다 (2026-08-28: 픽셀11 HiLight가
    # 카드 8/21·8/27 두 장 → 블로그 글 두 편). 블로그 단계에서도 스스로 막는다.
    titles = existing_titles()
    made = 0
    for path in todo:
        name = os.path.basename(path)
        try:
            with open(path, encoding="utf-8") as f:
                meta = json.load(f)
            probe = " ".join(str(meta.get(k) or "") for k in ("topic", "caption"))[:300]
            dup, hit, words = is_dup(probe, titles)
            if dup:
                _mark(name)          # 다시 시도하지 않는다 — 소재가 이미 다뤄졌다
                print("[blog_autogen] 중복 건너뜀: %s ↔ '%s' (%s)"
                      % (name[6:-5], hit.split("  ")[0][:34], ", ".join(words[:5])), flush=True)
                continue
            r = build(meta)
            # 원본 카드 표식 — 발행 단계가 옛 초안에 이미지를 소급할 때 이걸로 원고를 되찾는다
            # (2026-09-15: 9/9 옛 게이트로 만든 HDMI 초안이 9/15 사진 없이 그대로 공개됨)
            html = r["html"] + "\n<!-- src:%s -->" % name
            publish(r["title"], html, labels=r.get("labels") or ["IT·테크"], draft=True)
            _mark(name)                       # 성공한 것만 기록 — 실패는 다음 슬롯에서 재시도
            titles.append(r["title"])         # 같은 실행 안에서도 중복이 나지 않게
            made += 1
            warn = (" ⚠️새숫자:%s" % ",".join(r["new_numbers"][:6])) if r["new_numbers"] else ""
            print("[blog_autogen] 초안 생성: %s → %s%s"
                  % (name[6:-5], r["title"][:40], warn), flush=True)
        except Exception as e:
            # 일시 장애(환경·네트워크·쿼터)는 소재 탓이 아니다 — 카운트를 올리면 정상 카드가
            # 영구 제외된다 (2026-08-28 실사고: venv 환경 오류 3회로 픽셀·맥세이프 카드가
            # 부당 제외됐다). 내용 문제(짧은 원고 등 RuntimeError/ValueError)만 카운트한다.
            msg = str(e)
            transient = (isinstance(e, (ImportError, OSError, ConnectionError))
                         or "No module" in msg or "timed out" in msg
                         or "HttpError 5" in msg or "quota" in msg.lower()
                         or "RESOURCE_EXHAUSTED" in msg)
            if transient:
                print("[blog_autogen] 일시 장애(%s): %s — 카운트 안 올림, 다음 슬롯 재시도"
                      % (name, msg[:100]), flush=True)
            else:
                n = _bump_fail(name)
                tail = " — %d회 실패, 더 시도하지 않는다" % n if n >= MAX_FAIL else ""
                print("[blog_autogen] 실패(%s): %s%s" % (name, msg[:120], tail), flush=True)
    return made


if __name__ == "__main__":
    n = MAX_PER_RUN
    for a in sys.argv[1:]:
        if a.isdigit():
            n = int(a)
    if "--list" in sys.argv:
        p = pending()
        print("생성 대기 %d편:" % len(p))
        for x in p[:20]:
            print("  ", os.path.basename(x)[6:-5])
    else:
        print("생성 %d편" % run(limit=n))
