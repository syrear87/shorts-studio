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
    # 무방어 인덱싱 3곳이 이 스크립트를 즉사시켰고, dm_tick은 rc!=0을 버리므로
    # **댓글DM이 무증상으로 영구 정지**할 수 있었다 (2026-08-25 재감사).
    try:
        rules = json.load(open(RULES, encoding="utf-8"))
    except Exception as e:
        print("[comment_dm] 규칙 파일 파손 — 중단:", str(e)[:150])
        try:
            import subprocess as _sp
            _sp.run(["bash", os.path.join(ROOT, "bin", "tg-send.sh"),
                     "⚠️ content/dm_rules.json 파손으로 댓글DM 중단 — 파일 확인 필요: %s" % str(e)[:120]],
                    check=False, timeout=30)
        except Exception:
            pass
        return 0
    if not rules:
        return 0
    rules = [r for r in rules if isinstance(r, dict) and r.get("keyword")]   # keyword 없는 항목은 건너뛴다
    if not rules:
        print("[comment_dm] 유효한 규칙 없음 — 종료")
        return 0
    kv = load_keys()
    tok = kv.get("IG_ACCESS_TOKEN")
    if not tok:
        print("[comment_dm] keys.env에 IG_ACCESS_TOKEN 없음 — 중단")
        return 0
    st = _state()
    # 삽입 순서 보존 — set이면 list(set)[-2000:]가 "최근 2000개"가 아니라 임의 부분집합이 돼
    # 상한 로직이 무의미해지고, 탈락한 id가 폴링 창에 남아 있으면 DM이 재발송된다 (2026-08-25 감사)
    replied = dict.fromkeys(st.get("replied", []))
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
            if events:
                # ⚠️ /events는 파괴적 읽기다 — 워커가 반환과 동시에 KV에서 지운다.
                #    _save는 이 함수 맨 끝이라, 그 사이 어디서 죽으면(절전 SIGTERM·ffmpeg 행·
                #    미방어 KeyError) 이 댓글들은 어디에도 남지 않는다. 처리 전에 먼저 영속화한다.
                #    (2026-08-25 감사: 복구 경로가 0인 유일한 지점이었다)
                st["inbox"] = (st.get("inbox") or []) + events
                _save(st)
    except Exception as e:
        print("[comment_dm] 이벤트 조회 실패:", str(e)[:120])
    # 지난 실행이 처리하지 못하고 남긴 이벤트를 함께 소비한다(중복은 replied가 막는다)
    _inbox = st.get("inbox") or []
    if _inbox:
        _seen_ids = {e.get("id") for e in events}
        events = [e for e in _inbox if e.get("id") not in _seen_ids] + events
    def _alert(msg):
        try:
            import subprocess
            subprocess.run(["bash", os.path.join(ROOT, "bin", "tg-send.sh"), msg],
                           check=False, timeout=30)
        except Exception:
            pass

    # 설정 동기화 — 워커 실시간 응답용 (토큰 갱신·규칙 변경 반영).
    # 변경이 없으면 보내지 않는다 — 하루 144회 토큰 전송은 낭비이자 노출면이다 (2026-08-25 감사).
    # 그리고 조용한 실패가 이어지면 워커가 낡은 토큰을 들고 DM이 무증상 사망하므로 연속 실패는 경보한다.
    try:
        if cnt and key:
            import hashlib as _hl
            cfg = json.dumps({"token": tok, "rules": rules}).encode()
            _sig = _hl.sha1(cfg).hexdigest()
            _age = time.time() - float(st.get("cfg_at") or 0)
            if st.get("cfg_sig") != _sig or _age > 86400:   # 하루 1회는 무조건 재전송(워커 KV 재배포 대비)
                rq = urllib.request.Request("%s/dm_config?k=%s" % (cnt, key), data=cfg,
                                            headers={"User-Agent": "Mozilla/5.0 (studio-bot)",
                                                     "Content-Type": "application/json"}, method="POST")
                urllib.request.urlopen(rq, timeout=20).read()
                st["cfg_sig"] = _sig
                st["cfg_at"] = time.time()
                st["cfg_fail"] = 0
                _save(st)
                if verbose:
                    print("[comment_dm] 설정 동기화 완료(변경 감지)")
    except Exception as e:
        st["cfg_fail"] = int(st.get("cfg_fail") or 0) + 1
        _save(st)   # 즉시 저장 — 안 하면 카운터가 1에 고정돼 연속 실패 경보가 영원히 안 울린다
        print("[comment_dm] 설정 동기화 실패(%d회째):" % st["cfg_fail"], str(e)[:100])
        if st["cfg_fail"] in (3, 30):   # 30분·5시간 지점에서만 알린다(경보 폭주 방지)
            _alert("⚠️ 댓글DM 설정 동기화가 %d회 연속 실패 — 워커가 낡은 토큰을 들고 있을 수 있습니다: %s"
                   % (st["cfg_fail"], str(e)[:120]))

    for ev in events:
        cid = ev.get("id")
        if not cid or cid in replied:
            continue
        if ev.get("handled"):
            replied[cid] = None
            if verbose:
                print("[comment_dm] (워커 즉답 처리됨) %s" % cid[:24])
            continue
        # ─ 버튼 탭 (messages 웹훅, quick_reply payload = "SEND_LINK|<media_id>") → 이미지 카드 템플릿
        if ev.get("type") == "message":
            payload = ev.get("payload") or ""
            if not payload.startswith("SEND_LINK|"):
                replied[cid] = None   # 일반 DM은 자동 응답하지 않는다
                continue
            emid = payload.split("|", 1)[1]
            r = next((x for x in rules if x.get("media") == emid), None)
            if not r:
                replied[cid] = None
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
                replied[cid] = None
                # 발송 직후 즉시 영속화 — 300초 캡의 kill -KILL은 finally도 안 준다.
                # 기록이 유실되면 수신자 지정(버튼) DM이 다음 틱에 중복 발송된다 (2026-08-25 재감사).
                st["replied"] = list(replied)
                _save(st)
                if verbose:
                    print("[comment_dm] (버튼) 카드 템플릿 발송 → %s" % ev.get("from_id"))
                time.sleep(2)
            except Exception as e:
                print("[comment_dm] 템플릿 발송 실패: %s" % str(e)[:200])
                _alert("⚠️ 버튼DM(카드 템플릿) 발송 실패: %s" % str(e)[:150])
                replied[cid] = None
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
                    replied[cid] = None
                    st["replied"] = list(replied)   # 발송 즉시 영속화 (위와 동일 사유)
                    _save(st)
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
                    replied[cid] = None
                break
    # 2차 소스(REST 폴링 — 검수 승인 후 데이터가 열리면 자동으로 같이 동작)
    # ⚠️ 2026-08-25 감사: 여기서 /me/media?limit=15로 최근 15편을 받아 규칙과 대조했는데,
    #    계정이 하루 4~6편을 올려 제휴 태깅된 편은 약 3일이면 창 밖으로 밀려난다.
    #    실측 교집합 0 — 즉 "백업 폴러"가 존재하지 않으면서 하루 144회 호출만 낭비했고,
    #    로그는 성공/고장 모두 "발송 0건"으로 같았다. 규칙의 미디어 ID를 직접 순회한다.
    _mids = [r.get("media") for r in rules if r.get("media") and r.get("media") != "any"]
    if any(r.get("media") == "any" for r in rules):
        # "any" 규칙이 있으면 최근 게시물도 함께 훑는다 — 안 그러면 그 규칙이 폴링에서 통째로 빠진다
        try:
            _mids += [m["id"] for m in api("GET", "/me/media", params={
                "fields": "id", "limit": 15, "access_token": tok}).get("data", []) if m.get("id")]
        except Exception as e:
            print("[comment_dm] 최근 게시물 조회 실패(any 규칙 폴링 생략):", str(e)[:100])
    media = [{"id": mid} for mid in dict.fromkeys(_mids)]
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
                        replied[cid] = None
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
                        replied[cid] = None   # 같은 댓글로 무한 재시도 방지 (수동 확인 후 상태 파일에서 제거)
                    break
    _before_inbox = st.get("inbox") or []   # 비우기 '전에' 캡처 — 아래 조건의 근거다
    st["inbox"] = []          # 이번 실행이 events를 끝까지 처리했다 — 재처리 대기분 비움
    _before = st.get("replied") or []
    st["replied"] = list(replied)[-2000:]
    # 실제로 바뀐 게 있을 때만 쓴다 — 매 틱 재작성하면 dm_state.json의 mtime이
    # "마지막 처리 시각"이 아니라 "마지막 틱 시각"이 돼 생존 신호로 쓸 수 없다 (2026-08-25 감사).
    # ⚠️ _before_inbox를 봐야 한다 — st["inbox"]는 이미 비웠으니 항상 falsy라
    #    키워드 미매칭 이벤트만 온 틱에서 저장이 스킵돼 inbox가 영구 누적됐다 (재감사).
    if st["replied"] != _before or _before_inbox or sent:
        _save(st)
    if verbose:
        print("[comment_dm] 완료 — 발송 %d건" % sent)
    return sent


if __name__ == "__main__":
    run_once()
