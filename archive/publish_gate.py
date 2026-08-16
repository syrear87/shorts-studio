#!/usr/bin/env python3
# 게시 승인 게이트 (2026-08-14 디렉터 지시: "앞으로 바로 올리지 말고 텔레그램으로 영상 확인 후 올려.
#   통과/반려 버튼 있는 대화 보내. 통과 눌렀을 때만 게시해")
#
# 흐름: 슬롯 세션이 렌더를 마치면 게시 대신 이 스크립트를 부른다 →
#       영상 + [✅ 통과] [❌ 반려] 인라인 버튼이 텔레그램으로 감 →
#       상주 봇(affiliate_bot)이 버튼 응답을 감지 →
#         통과: upload_instagram.py 실행 후 결과 보고
#         반려: 게시하지 않고 대기 해제 (디렉터가 사유를 텍스트로 회신)
#
# 사용: .venv/bin/python3 pipeline/publish_gate.py <video.mp4> <meta.json> ["한 줄 메모"]
import json
import os
import sys
import time
import urllib.parse
import urllib.request
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUEUE_F = os.path.join(ROOT, "logs", "publish_queue.json")


def env(path, keys):
    out = {}
    for line in open(os.path.join(ROOT, path), encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            if k.strip() in keys:
                out[k.strip()] = v.strip().strip('"')
    return out


TG = env("telegram.env", {"STUDIO_TG_TOKEN", "STUDIO_TG_CHAT_ID"})


def queue_load():
    try:
        return json.load(open(QUEUE_F, encoding="utf-8"))
    except Exception:
        return {}


def queue_save(d):
    tmp = QUEUE_F + ".tmp"
    json.dump(d, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, QUEUE_F)


def send_for_approval(video, meta_path, note=""):
    meta = json.load(open(meta_path, encoding="utf-8"))
    job = uuid.uuid4().hex[:8]
    title = meta.get("title", os.path.basename(video))
    caption = "🎬 게시 승인 요청\n\n%s\n\n%s%s" % (
        title, (note + "\n\n") if note else "",
        "아래 버튼으로 판정해주세요. 통과를 누르면 인스타에 게시합니다.")
    kb = {"inline_keyboard": [[
        {"text": "✅ 통과 (게시)", "callback_data": "ok:%s" % job},
        {"text": "❌ 반려", "callback_data": "no:%s" % job},
    ]]}
    import mimetypes
    boundary = uuid.uuid4().hex
    fields = {"chat_id": TG["STUDIO_TG_CHAT_ID"], "caption": caption,
              "supports_streaming": "true", "reply_markup": json.dumps(kb, ensure_ascii=False)}
    body = b""
    for k, v in fields.items():
        body += ("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (boundary, k, v)).encode()
    body += ("--%s\r\nContent-Disposition: form-data; name=\"video\"; filename=\"%s\"\r\nContent-Type: video/mp4\r\n\r\n"
             % (boundary, os.path.basename(video))).encode()
    body += open(video, "rb").read() + b"\r\n"
    body += ("--%s--\r\n" % boundary).encode()
    req = urllib.request.Request(
        "https://api.telegram.org/bot%s/sendVideo" % TG["STUDIO_TG_TOKEN"], data=body, method="POST")
    req.add_header("Content-Type", "multipart/form-data; boundary=%s" % boundary)
    with urllib.request.urlopen(req, timeout=300) as r:
        res = json.load(r)
    if not res.get("ok"):
        sys.exit("승인 요청 발송 실패: %s" % str(res)[:200])
    q = queue_load()
    # 같은 영상의 이전 대기 건은 자동 무효화 — 수정본 재발송 시 옛 버튼으로 구버전이 게시되는 사고 방지
    # (2026-08-15: 태극기·안중근 재수정 중 pending 4건이 쌓여 수동 정리했다)
    base = os.path.basename(video).split("-fix")[0]
    for k, v in q.items():
        if v.get("status") == "pending" and os.path.basename(v.get("video", "")).split("-fix")[0] == base:
            v["status"] = "superseded"
    q[job] = {"video": os.path.abspath(video), "meta": os.path.abspath(meta_path),
              "title": title, "ts": time.time(),
              "msg_id": res["result"]["message_id"], "status": "pending"}
    queue_save(q)
    print("승인 요청 발송 완료 (job=%s) — 디렉터가 '통과'를 누르면 봇이 게시한다" % job)
    return job


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit("사용: publish_gate.py <video.mp4> <meta.json> [\"메모\"]")
    send_for_approval(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "")
