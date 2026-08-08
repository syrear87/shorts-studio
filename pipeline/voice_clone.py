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
import re
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
    # 값 뒤 인라인 주석 금지 — load_keys가 값의 일부로 읽는다 (2026-08-04 실사고)
    lines.append("%s=%s" % (name, value))
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


_D = "영일이삼사오육칠팔구"


def _sino(n):
    """정수 → 한자어 수사 (조 단위까지). 42→사십이, 122→백이십이, 2026→이천이십육."""
    if n == 0:
        return "영"
    groups, out = ["", "만", "억", "조"], []
    gi = 0
    while n > 0:
        g, n = n % 10000, n // 10000
        if g:
            s = ""
            for unit, div in (("천", 1000), ("백", 100), ("십", 10)):
                q, g = g // div, g % div
                if q:
                    s += ("" if q == 1 else _D[q]) + unit
            if g:
                s += _D[g]
            out.append(s + groups[gi])
        gi += 1
    return "".join(reversed(out))


def normalize_numbers(text):
    """숫자를 한글 발음으로 (TTS 입력 전용 — 자막은 원문 유지).
    42.5도 → 사십이 점 오 도, 122년 → 백이십이년, 40% → 사십 퍼센트 (2026-08-04 디렉터: '42.5도' 발음 어색)"""
    def repl(m):
        whole, dec = m.group(1), m.group(2)
        s = _sino(int(whole))
        if dec:
            # 공백을 넣으면 TTS가 또박또박 끊어 읽음 (2026-08-04 디렉터) — 붙여서 '사십이쩜오' (디렉터 발음 습관: '쩜')
            s += "쩜" + "".join(_D[int(c)] for c in dec)
        return s
    # 월 이름 예외 (한자어 수사 규칙 밖): 6월=유월, 10월=시월
    text = re.sub(r"(?<!\d)6월", "유월", text)
    text = re.sub(r"(?<!\d)10월", "시월", text)
    text = re.sub(r"(\d+)(?:\.(\d+))?", repl, text)
    # 공백 없이 붙임 — 어절 수가 원문과 1:1로 유지돼야 자막 타이밍 fast path가 성립
    return text.replace("%", "퍼센트")


# 고유어 수사를 쓰는 단위 (2026-08-08 디렉터: "12개월을 열두개월로 읽어 어색" — TTS의 수사 선택을 운에 맡기지 않는다)
# 동음이의 위험 단위(대·번·시·장·편 등)는 제외 — 오변환이 미변환보다 나쁘다. 21 이상은 관용상 한자어로 간다.
_NATIVE = {1: "한", 2: "두", 3: "세", 4: "네", 5: "다섯", 6: "여섯", 7: "일곱", 8: "여덟", 9: "아홉",
           10: "열", 11: "열한", 12: "열두", 13: "열세", 14: "열네", 15: "열다섯", 16: "열여섯",
           17: "열일곱", 18: "열여덟", 19: "열아홉", 20: "스무"}
_NATIVE_UNITS = (r"가지|군데|번째|시간(?!대)|개(?!월|국|사|소|점)|마리|살(?!균|충)|명(?!령|예|단)|잔|병(?!원|사|력)"
                 r"|곳|채(?!널|용|취)|켤레|벌(?!금|레|집)|끼(?!리)|그루|송이|달(?!러|력|성)|배(?!송|달|경|추|정|출|당|율|수|관|터)"
                 r"|시(?=[ ,.!?에까부반쯤]|$)")   # 시각(9시=아홉시). 뒤에 조사·구두점이 올 때만 — 시장·시절 등 오폭 방지


def normalize_ko(text):
    """TTS 입력 전용 최종 정규화 — 단위별 수사 선택(고유어 1~20) 후 일반 한자어 변환.
    어절 수는 원문과 1:1 유지(공백 추가 금지) — 자막 타이밍 전제."""
    def native_repl(m):
        n = int(m.group(1))
        if 1 <= n <= 20:
            return _NATIVE[n] + m.group(2) + m.group(3)
        return m.group(0)   # 21+ 는 일반 패스(한자어)로
    text = re.sub(r"(?<![\d.])(\d+)(\s?)(%s)" % _NATIVE_UNITS, native_repl, text)
    return normalize_numbers(text)


SENT_PAUSE = 0.45  # 문장 사이 '추가' 쉼 (v3 자체 쉼 위에 얹힘; 2026-08-04 디렉터 "숨차는 느낌")


def _synth_whole(keys, vid, text):
    """씬 전체를 한 번에 합성 → (mp3 bytes, [(시작초, 어절)]).
    2026-08-04 실사고: 문장별 분할 합성은 문장마다 톤이 달라져 '다른 사람 같다' 지적 —
    반드시 통짜로 합성해 목소리 일관성을 지키고, 쉼은 후처리(무음 삽입)로 만든다."""
    r = requests.post(API + "/text-to-speech/%s/with-timestamps" % vid,
                      headers={"xi-api-key": keys["ELEVENLABS_API_KEY"]},
                      # 2026-08-04 디렉터 청음 확정: eleven_v3 (억양·호흡 자연) — 설정 기본값(Natural)
                      json={"text": text, "model_id": "eleven_v3"}, timeout=300)
    if r.status_code != 200:
        sys.exit("합성 실패 (%d): %s" % (r.status_code, r.text[:500]))
    j = r.json()
    import base64
    audio = base64.b64decode(j["audio_base64"])
    al = j["alignment"]
    words, cur, t0 = [], "", None
    for ch, st in zip(al["characters"], al["character_start_times_seconds"]):
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
    return audio, words


def tts(text, out_path, with_timestamps=False):
    """클론 목소리 합성 (씬 통짜 1회 호출 → 문장 경계에 무음 삽입).
    반환: (mp3경로, [(시작초, 어절)]) — 렌더러 자막 동기용."""
    import shutil
    import subprocess
    import tempfile
    keys = load_keys()
    vid = keys.get("ELEVEN_VOICE_ID")
    if not vid:
        sys.exit("ELEVEN_VOICE_ID 없음 — 먼저 create를 실행")
    text = normalize_numbers(text)
    audio, words = _synth_whole(keys, vid, text)
    # 문장 경계 = 마침표류로 끝나는 어절의 '다음 어절' 시작 시각
    cuts = [words[i + 1][0] for i in range(len(words) - 1)
            if words[i][1].rstrip('"\')').endswith((".", "?", "!"))]
    tmpd = tempfile.mkdtemp(prefix="vc_")
    try:
        raw = os.path.join(tmpd, "raw.mp3")
        open(raw, "wb").write(audio)
        if not cuts:
            wav = os.path.join(tmpd, "one.wav")
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", raw,
                            "-ar", "44100", "-ac", "1", wav], check=True)
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", wav,
                            "-codec:a", "libmp3lame", "-q:a", "2", out_path], check=True)
            return out_path, (words if with_timestamps else None)
        full = os.path.join(tmpd, "full.wav")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", raw,
                        "-ar", "44100", "-ac", "1", full], check=True)
        # 경계마다 자르고 사이에 무음 — 같은 오디오를 자르는 것이라 목소리 톤은 그대로
        bounds = [0.0] + cuts + [None]
        segs = []
        for i in range(len(bounds) - 1):
            seg = os.path.join(tmpd, "seg%03d.wav" % i)
            cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", full, "-ss", "%.3f" % bounds[i]]
            if bounds[i + 1] is not None:
                cmd += ["-to", "%.3f" % bounds[i + 1]]
            subprocess.run(cmd + [seg], check=True)
            segs.append(seg)
        sil = os.path.join(tmpd, "sil.wav")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                        "-i", "anullsrc=r=44100:cl=mono", "-t", str(SENT_PAUSE), sil], check=True)
        lst = os.path.join(tmpd, "list.txt")
        with open(lst, "w") as f:
            for i, sg in enumerate(segs):
                if i:
                    f.write("file '%s'\n" % sil)
                f.write("file '%s'\n" % sg)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                        "-i", lst, "-codec:a", "libmp3lame", "-q:a", "2", out_path], check=True)
        # 어절 시각 보정: k번째 경계 이후 어절은 +k*SENT_PAUSE
        shifted = []
        for t, w in words:
            k = sum(1 for c in cuts if t >= c)
            shifted.append((t + k * SENT_PAUSE, w))
        return out_path, (shifted if with_timestamps else None)
    finally:
        shutil.rmtree(tmpd, ignore_errors=True)


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
