#!/usr/bin/env python3
"""텍스트 글 게시 — CARD_PROMPT §스레드 텍스트 글(주 1~2회) 전용.

⚠️ 이 경로는 **이미지 실패의 폴백이 아니다** (2026-09-08 실사고).
  12:00 슬롯이 이미지 다운로드에 실패하자 세션이 이 파일을 스스로 만들어
  텍스트로 게시했고, 그 결과 make_cards의 게이트(판매어법·가격·문화·이미지 재사용)와
  blog_gate·blog_polish를 **전부 우회**했다. 블로그는 draft=False로 즉시 공개됐고
  라벨도 우리 체계 밖(["카드","테크"])이었다.

  **이미지를 못 구하면 소재를 바꾸거나 결번하라.** 카드 라인은 이미지가 주인공이고,
  텍스트 글은 주 1~2회 **의도적으로 고르는 형식**이지 사고 수습 수단이 아니다.

사용: DRY_RUN=1로 먼저 확인한 뒤 CARD_MODE=1 .venv/bin/python3 pipeline/publish_text_card.py <json>
"""
import datetime
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
os.chdir(ROOT)


def main():
    if len(sys.argv) < 2:
        sys.exit("사용: publish_text_card.py <cards.json>")
    path = sys.argv[1]
    with open(path, encoding="utf-8") as f:
        s = json.load(f)

    text = (s.get("threads_text") or "").strip()
    if not text:
        sys.exit("기각: threads_text가 없다")

    # ── 게이트 (make_cards와 같은 것을 여기서도 태운다) ──────────────────
    if (s.get("cards") or []):
        sys.exit("기각: cards[]가 있는 카드다 — 텍스트 경로가 아니라 make_cards.py로 렌더하라.\n"
                 "  이미지를 못 구했으면 소재를 바꾸거나 결번하라(§스레드 텍스트 글은 폴백이 아니다).")
    from price_gate import check as price_check, enforcing as price_enf
    v, fails, warns = price_check(s)
    for w in warns:
        print("가격 게이트 ⚠ %s" % w, flush=True)
    if v == "reject":
        msg = "가격 게이트: " + " / ".join(f[:90] for f in fails)
        if price_enf():
            sys.exit("기각: " + msg)
        print("가격 게이트 [경고·미차단] %s" % msg, flush=True)
    from hook_check import score as hook_score, MSG as HOOK_MSG
    g, notes = hook_score(s)
    print("훅 채점: %s — %s" % ({"strong": "◎", "weak": "△", "flat": "▽"}[g], HOOK_MSG[g]), flush=True)

    slug = os.path.splitext(os.path.basename(path))[0]

    # ① 스레드
    from upload_threads import publish_text
    url = publish_text(text)
    print("[threads] %s" % url, flush=True)

    # ② 블로그 — 게이트·후처리를 반드시 탄다
    blog_url = ""
    try:
        from blog_gate import judge
        ok, why = judge(s, is_card=True)
        if not ok:
            print("[blog] 보류 — %s" % why, flush=True)
        else:
            from blog_polish import polish
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            html = "\n".join("<p>%s</p>" % l for l in lines[1:])
            html, labels = polish(html, lines[0])
            from upload_blogger import publish as blog_publish
            r = blog_publish(lines[0], html, labels=labels, draft=True)   # 초안 — 공개는 publish_blog_daily가 한다
            blog_url = r.get("url") or ""
            print("[blog] 초안 저장 (라벨 %s) %s" % (" / ".join(labels), blog_url), flush=True)
    except Exception as e:
        print("[blog] 실패(무해): %s" % str(e)[:120], flush=True)

    if os.environ.get("DRY_RUN") in ("1", "true", "True"):
        print("[DRY_RUN] sent.log 기록 생략", flush=True)
        return 0
    with open(os.path.join(ROOT, "logs", "sent.log"), "a", encoding="utf-8") as f:
        f.write("%s THTEXT:%s\n" % (datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"), slug))
    return 0


if __name__ == "__main__":
    sys.exit(main())
