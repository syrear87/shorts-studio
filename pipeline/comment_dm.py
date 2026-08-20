#!/usr/bin/env python3
"""댓글 키워드 → 자동 DM (2026-08-20 디렉터: "A로 해보고, 팔로우 안 해도 그냥 링크 보내자")
살룸연구소류 '댓글에 ○○ 적으면 DM' 패턴의 자체 구현 — Manychat 없이 Meta 공식 API만 사용.

흐름: 최근 게시물 댓글 폴링 → content/dm_rules.json의 키워드 매칭 →
      ①해당 댓글에 Private Reply(DM) ②댓글에 공개 답글("DM 보냈어요") → 중복 방지 기록.

규칙 파일 content/dm_rules.json:
  [{"keyword": "몬스터볼", "media": "any" 또는 미디어ID,
    "dm": "DM 본문(링크 포함)", "ack": "댓글 공개 답글(선택, 없으면 생략)"}]

사용: .venv/bin/python3 pipeline/comment_dm.py --once
상태: logs/dm_state.json (답장한 댓글 id — 재발송 방지)
주의: Private Reply는 댓글 7일 이내·댓글당 1회 제한(Meta 규정). 실패는 무해하게 기록만.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from upload_instagram import load_keys, api  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RULES = os.path.join(ROOT, "content", "dm_rules.json")
STATE = os.path.join(ROOT, "logs", "dm_state.json")
ME_USERNAME = "syusyu_channel"   # 자기 댓글엔 답하지 않는다


def _state():
    try:
        return json.load(open(STATE, encoding="utf-8"))
    except Exception:
        return {"replied": []}


def _save(s):
    tmp = STATE + ".tmp"
    json.dump(s, open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
    os.replace(tmp, STATE)


def run_once(verbose=True):
    if not os.path.exists(RULES):
        print("[comment_dm] 규칙 파일 없음 — 종료")
        return 0
    rules = json.load(open(RULES, encoding="utf-8"))
    if not rules:
        return 0
    kv = load_keys()
    tok = kv["IG_ACCESS_TOKEN"]
    st = _state()
    replied = set(st.get("replied", []))
    sent = 0
    media = api("GET", "/me/media", params={
        "fields": "id,caption,timestamp", "limit": 15, "access_token": tok}).get("data", [])
    for m in media:
        mid = m["id"]
        applicable = [r for r in rules if r.get("media") in ("any", mid)]
        if not applicable:
            continue
        try:
            comments = api("GET", "/%s/comments" % mid, params={
                "fields": "id,text,username,timestamp", "limit": 50,
                "access_token": tok}).get("data", [])
        except Exception as e:
            print("[comment_dm] 댓글 조회 실패 %s: %s" % (mid, str(e)[:120]))
            continue
        for c in comments:
            cid = c["id"]
            if cid in replied or (c.get("username") or "") == ME_USERNAME:
                continue
            text = (c.get("text") or "").strip().lower()
            for r in applicable:
                if r["keyword"].lower() in text:
                    try:
                        api("POST", "/me/messages", data={
                            "recipient": json.dumps({"comment_id": cid}),
                            "message": json.dumps({"text": r["dm"][:900]}),
                            "access_token": tok})
                        sent += 1
                        replied.add(cid)
                        if verbose:
                            print("[comment_dm] DM 발송 → @%s (%s)" % (c.get("username"), r["keyword"]))
                        if r.get("ack"):
                            try:
                                api("POST", "/%s/replies" % cid, data={
                                    "message": r["ack"][:300], "access_token": tok})
                            except Exception as e2:
                                print("[comment_dm] 공개 답글 실패(무해):", str(e2)[:120])
                        time.sleep(2)
                    except Exception as e:
                        # 권한 부족(instagram_business_manage_messages 미승인)이면 여기서 드러난다
                        print("[comment_dm] DM 실패 @%s: %s" % (c.get("username"), str(e)[:200]))
                        replied.add(cid)   # 같은 댓글로 무한 재시도 방지 (수동 확인 후 상태 파일에서 제거)
                    break
    st["replied"] = list(replied)[-2000:]
    _save(st)
    if verbose:
        print("[comment_dm] 완료 — 발송 %d건" % sent)
    return sent


if __name__ == "__main__":
    run_once()
