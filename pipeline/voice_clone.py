#!/usr/bin/env python3
# 디렉터 목소리 클론 (ElevenLabs, 2026-08-04 디렉터 지시 "내 목소리 클론 해보자")
# 사용:
#   1) keys.env에 ELEVENLABS_API_KEY=... 추가
#   2) 샘플 등록:  .venv/bin/python3 pipeline/voice_clone.py create assets/voice/sample1.m4a [sample2.m4a ...]
#      → voice_id 발급, keys.env에 ELEVEN_VOICE_ID로 자동 기록
#   3) 시청 테스트: .venv/bin/python3 pipeline/voice_clone.py test "안녕하세요, 1일 1지식입니다."
#      → out/voice_test.mp3 생성 (들어보고 승인/재녹음 판단)
# 본편 연동(make_long) 은 테스트 승인 후 별도 커밋으로.
import json
import os
import sys

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = "https://api.elevenlabs.io/v1"


def load_keys():
    kv = {}
    p = os.path.join(ROOT, "keys.env")
    for line in open(p, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            kv[k.strip()] = v.strip()
    return kv


def save_key(name, value):
    p = os.path.join(ROOT, "keys.env")
    lines = open(p, encoding="utf-8").read().splitlines()
    lines = [l for l in lines if not l.startswith(name + "=")]
    lines.append("%s=%s   # ElevenLabs 디렉터 목소리 (voice_clone.py가 기록)" % (name, value))
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, p)


def api_key():
    k = load_keys().get("ELEVENLABS_API_KEY")
    if not k:
        sys.exit("keys.env에 ELEVENLABS_API_KEY가 없음 — 디렉터가 elevenlabs.io 가입 후 키를 넣어야 함")
    return k


def create(samples):
    for s in samples:
        if not os.path.exists(s):
            sys.exit("샘플 파일 없음: %s" % s)
    files = [("files", (os.path.basename(s), open(s, "rb"), "audio/mpeg")) for s in samples]
    r = requests.post(API + "/voices/add",
                      headers={"xi-api-key": api_key()},
                      data={"name": "director-ko",
                            "description": "1일 1지식 디렉터 본인 목소리 (본인 동의, 롱폼 내레이션용)"},
                      files=files, timeout=120)
    if r.status_code != 200:
        sys.exit("클론 생성 실패 (%d): %s" % (r.status_code, r.text[:500]))
    vid = r.json()["voice_id"]
    save_key("ELEVEN_VOICE_ID", vid)
    print("클론 생성 완료 — voice_id=%s (keys.env에 기록)" % vid)


def tts(text, out_path, with_timestamps=False):
    """클론 목소리로 합성. with_timestamps=True면 (mp3경로, 어절 경계 리스트) 반환 — 렌더러 자막 동기용."""
    keys = load_keys()
    vid = keys.get("ELEVEN_VOICE_ID")
    if not vid:
        sys.exit("ELEVEN_VOICE_ID 없음 — 먼저 create를 실행")
    url = API + "/text-to-speech/%s%s" % (vid, "/with-timestamps" if with_timestamps else "")
    body = {"text": text, "model_id": "eleven_multilingual_v2",
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.8}}
    r = requests.post(url, headers={"xi-api-key": keys["ELEVENLABS_API_KEY"]}, json=body, timeout=300)
    if r.status_code != 200:
        sys.exit("합성 실패 (%d): %s" % (r.status_code, r.text[:500]))
    if not with_timestamps:
        open(out_path, "wb").write(r.content)
        return out_path, None
    j = r.json()
    import base64
    open(out_path, "wb").write(base64.b64decode(j["audio_base64"]))
    # 문자 타임스탬프 → 어절(공백 단위) 경계로 변환: (시작초, 어절)
    al = j["alignment"]
    chars, starts = al["characters"], al["character_start_times_seconds"]
    words, cur, t0 = [], "", None
    for ch, st in zip(chars, starts):
        if ch.isspace():
            if cur:
                words.append((t0, cur))
                cur, t0 = "", None
        else:
            if not cur:
                t0 = st
            cur += ch
    if cur:
        words.append((t0, cur))
    return out_path, words


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in ("create", "test"):
        sys.exit(__doc__ or "사용: voice_clone.py create <샘플...> | test \"문장\"")
    if sys.argv[1] == "create":
        if len(sys.argv) < 3:
            sys.exit("사용: voice_clone.py create assets/voice/sample1.m4a [...]")
        create(sys.argv[2:])
    else:
        text = sys.argv[2] if len(sys.argv) > 2 else \
            "안녕하세요, 1일 1지식입니다. 오늘은 2026년 여름, 42.5도의 비밀을 파헤쳐 보겠습니다."
        out = os.path.join(ROOT, "out", "voice_test.mp3")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        p, w = tts(text, out, with_timestamps=True)
        print("합성 완료: %s (어절 %d개 타임스탬프 확보 — 자막 동기 가능 확인)" % (p, len(w or [])))
