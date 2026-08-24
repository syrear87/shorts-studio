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
from disclosure import DISCLOSURE  # noqa: E402  — 법정 고지 문구 단일 정본 (2026-08-25)

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
    with open(tmp, "w", encoding="utf-8") as f:   # flush 보장 후 교체 (2026-08-25 감사)
        json.dump(s, f, ensure_ascii=False)
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
    # 1차 소스: 웹훅 이벤트 (2026-08-21 — 개발 모드에서 REST 댓글 읽기가 차단돼 워커 푸시로 우회)
    import urllib.request   # 이벤트 조회·설정 동기화 공용 (2026-08-23 감사: 중복 import·키 계산 통합)
    cnt = (kv.get("HUB_COUNTER_URL") or "").rstrip("/")
    key = kv.get("HUB_STATS_KEY") or ""
    events = []
    try:
        if cnt and key:
            req = urllib.request.Request("%s/events?k=%s" % (cnt, key),
                                         headers={"User-Agent": "Mozilla/5.0 (studio-bot)"})
            with urllib.request.urlopen(req, timeout=20) as r:
                events = json.load(r)
    except Exception as e:
        print("[comment_dm] 이벤트 조회 실패:", str(e)[:120])
    def _alert(msg):
        try:
            import subprocess
            subprocess.run(["bash", os.path.join(ROOT, "bin", "tg-send.sh"), msg],
                           check=False, timeout=30)
        except Exception:
            pass

    # 설정 동기화 — 워커 실시간 응답용 (토큰 갱신·규칙 변경 반영)
    try:
        if cnt and key:
            cfg = json.dumps({"token": tok, "rules": rules}).encode()
            rq = urllib.request.Request("%s/dm_config?k=%s" % (cnt, key), data=cfg,
                                        headers={"User-Agent": "Mozilla/5.0 (studio-bot)",
                                                 "Content-Type": "application/json"}, method="POST")
            urllib.request.urlopen(rq, timeout=20).read()
    except Exception as e:
        print("[comment_dm] 설정 동기화 실패(무해):", str(e)[:100])

    for ev in events:
        cid = ev.get("id")
        if not cid or cid in replied:
            continue
        if ev.get("handled"):
            replied.add(cid)
            if verbose:
                print("[comment_dm] (워커 즉답 처리됨) %s" % cid[:24])
            continue
        # ─ 버튼 탭 (messages 웹훅, quick_reply payload = "SEND_LINK|<media_id>") → 이미지 카드 템플릿
        if ev.get("type") == "message":
            payload = ev.get("payload") or ""
            if not payload.startswith("SEND_LINK|"):
                replied.add(cid)   # 일반 DM은 자동 응답하지 않는다
                continue
            emid = payload.split("|", 1)[1]
            r = next((x for x in rules if x.get("media") == emid), None)
            if not r:
                replied.add(cid)
                continue
            try:
                el = {"title": (r.get("name") or "추천 상품")[:80],
                      "subtitle": "쿠팡에서 최저가 확인하기",
                      "buttons": [{"type": "web_url", "url": r.get("url") or "",
                                   "title": "상품 보러가기 🛒"}]}
                if r.get("img"):
                    el["image_url"] = r["img"]
                api("POST", "/me/messages", data={
                    "recipient": json.dumps({"id": ev.get("from_id")}),
                    "message": json.dumps({"attachment": {"type": "template",
                        "payload": {"template_type": "generic", "elements": [el]}}}),
                    "access_token": tok})
                api("POST", "/me/messages", data={
                    "recipient": json.dumps({"id": ev.get("from_id")}),
                    "message": json.dumps({"text": "프로필 링크의 허브에서도 언제든 다시 볼 수 있어요 🙂\n\n" + DISCLOSURE}),
                    "access_token": tok})
                sent += 1
                replied.add(cid)
                if verbose:
                    print("[comment_dm] (버튼) 카드 템플릿 발송 → %s" % ev.get("from_id"))
                time.sleep(2)
            except Exception as e:
                print("[comment_dm] 템플릿 발송 실패: %s" % str(e)[:200])
                _alert("⚠️ 버튼DM(카드 템플릿) 발송 실패: %s" % str(e)[:150])
                replied.add(cid)
            continue
        # ─ 키워드 댓글 → 인사 + 빠른답장 버튼
        if (ev.get("from") or "") == ME_USERNAME:
            continue
        text = (ev.get("text") or "").strip().lower()
        emid = ev.get("media") or ""
        for r in rules:
            if r.get("media") not in ("any", emid):
                continue
            if r["keyword"].lower() in text:
                try:
                    greet = "안녕하세요 👋 댓글 남겨주신 거 봤어요!\n%s 정보를 보내드릴게요 — 아래 버튼을 눌러주세요 ⬇️" % (r.get("name") or "요청하신 상품")
                    btn_msg = {"attachment": {"type": "template", "payload": {
                        "template_type": "button", "text": greet[:600],
                        "buttons": [{"type": "postback", "title": "네! 받을래요 🙌",
                                     "payload": "SEND_LINK|%s" % emid}]}}}
                    try:
                        api("POST", "/me/messages", data={
                            "recipient": json.dumps({"comment_id": cid}),
                            "message": json.dumps(btn_msg), "access_token": tok})
                    except Exception:
                        # 버튼 템플릿 미지원 시 빠른답장 폴백
                        api("POST", "/me/messages", data={
                            "recipient": json.dumps({"comment_id": cid}),
                            "message": json.dumps({"text": greet[:900],
                                "quick_replies": [{"content_type": "text",
                                                   "title": "네! 받을래요 🙌",
                                                   "payload": "SEND_LINK|%s" % emid}]}),
                            "access_token": tok})
                    sent += 1
                    replied.add(cid)
                    if verbose:
                        print("[comment_dm] (웹훅) 버튼DM 발송 → @%s (%s)" % (ev.get("from"), r["keyword"]))
                    if r.get("ack"):
                        try:
                            api("POST", "/%s/replies" % cid, data={
                                "message": r["ack"][:300], "access_token": tok})
                        except Exception as e2:
                            print("[comment_dm] 공개 답글 실패(무해):", str(e2)[:120])
                    time.sleep(2)
                except Exception as e:
                    print("[comment_dm] (웹훅) DM 실패 @%s: %s" % (ev.get("from"), str(e)[:200]))
                    _alert("⚠️ 댓글DM 발송 실패 — @%s의 '%s' 댓글. 원인: %s" % (
                        ev.get("from"), r["keyword"], str(e)[:150]))
                    replied.add(cid)
                break
    # 2차 소스(REST 폴링 — 검수 승인 후 데이터가 열리면 자동으로 같이 동작)
    # ⚠️ 이 시점엔 위 웹훅 경로가 이미 DM을 발송하고 replied에 기록했지만 _save는 아직이다.
    #    여기서 5xx/429로 죽으면 상태가 저장되지 않아 다음 틱에 같은 사람에게 DM이 재발송된다.
    #    아래 /comments 호출과 동일하게 방어한다 (2026-08-25 감사).
    try:
        media = api("GET", "/me/media", params={
            "fields": "id,caption,timestamp", "limit": 15, "access_token": tok}).get("data", [])
    except Exception as e:
        print("[comment_dm] 미디어 조회 실패(무해 — 웹훅 경로는 이미 처리됨):", str(e)[:120], flush=True)
        media = []
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
                        _alert("⚠️ 댓글DM 발송 실패 — @%s의 '%s' 댓글. 원인: %s" % (
                            c.get("username"), r["keyword"], str(e)[:150]))
                        replied.add(cid)   # 같은 댓글로 무한 재시도 방지 (수동 확인 후 상태 파일에서 제거)
                    break
    st["replied"] = list(replied)[-2000:]
    _save(st)
    if verbose:
        print("[comment_dm] 완료 — 발송 %d건" % sent)
    return sent


if __name__ == "__main__":
    run_once()
