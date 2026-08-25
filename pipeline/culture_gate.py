#!/usr/bin/env python3
"""한국 고유 소재에 외국(중국·일본) 이미지가 섞이는 것을 막는 기계 게이트.

왜 있는가 (2026-08-25 실사고):
  추석 편 훅 배경에 **중국 한푸 + 홍등 + 상운 문양** 사진이 들어가 게시됐다.
  bg_query에 "korean hanbok"을 넣었지만 Pexels가 중국 중추절 사진을 반환했고,
  세션의 프레임 QA는 "통과"로 기록됐다 — 눈으로 보면서 국적을 묻지 않았기 때문이다.
  디렉터: "우리나라 고유 명절인데 중국 한푸나 해외 배경은 나락 한순간에 간다."

설계:
  ①`is_korean_topic()` — 대본·제목에 한국 고유 소재 키워드가 있는지 (싸다, 항상 실행)
  ②`judge_image()` — Gemini 비전으로 외국 전통 요소 판정 (한국 소재일 때만 호출)
  판정 실패(네트워크·키 부재)는 **통과**로 처리한다 — 게이트 고장이 슬롯을 죽이면 안 된다.
  대신 호출자가 경고를 남긴다(fail-open 가시화).

실측 검증(2026-08-25): 문제의 한푸 사진 → {"foreign":true,"country":"중국"},
  교체한 황금 벼 사진 → {"foreign":false}. 둘 다 정확히 판정했다.
"""
import base64
import json
import os
import re
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 한국 고유 소재 — 이 낱말이 제목·대본에 있으면 배경 국적을 검사한다.
KOREAN_TOPICS = (
    # 명절·절기
    "추석", "한가위", "설날", "정월대보름", "단오", "한식", "동짓날", "삼짇날", "칠석",
    # 의식주·전통
    "한복", "한옥", "온돌", "장독", "한지", "국악", "판소리", "사물놀이", "탈춤", "씨름",
    "제사", "차례상", "차롓상", "세배", "성묘", "돌잔치", "궁궐", "경복궁", "창덕궁", "종묘", "서낭",
    # 음식
    "김치", "송편", "떡국", "비빔밥", "불고기", "막걸리", "된장", "고추장", "삼계탕",
    # 국가상징·역사
    "태극기", "무궁화", "애국가", "한글", "훈민정음", "광복절", "삼일절", "개천절", "현충일",
    "독립운동", "임진왜란", "조선시대", "고려시대", "신라", "백제", "고구려",
    "세종대왕", "이순신", "안중근", "유관순", "김구",
)

_PROMPT = (
    "이 이미지에 한국이 아닌 나라의 전통·문화 요소가 보이는가? "
    "특히 중국(한푸·치파오·홍등·상운 문양·중국 매듭·한자 간판·용 문양·중국식 정자)과 "
    "일본(기모노·유카타·도리이·다다미·일본어 간판·사쿠라 축제 장식)의 요소를 찾아라. "
    "한국 고유 소재(명절·한복·전통·역사) 영상의 배경으로 쓸 이미지이므로 "
    "조금이라도 의심되면 위험(foreign=true)으로 판정하라. "
    "단 자연물(달·하늘·들판·벼·산·바다)만 있고 사람·건축·문자가 없으면 안전하다. "
    'JSON만 출력: {"foreign":true/false,"country":"중국|일본|기타|없음","reason":"한 문장"}'
)


# 부분문자열이면 오탐이 나는 낱말 — 어절 경계를 요구한다 (2026-08-25 감사 실측:
#   "4차례 강진"(피사의 사탑)·"동지 열두 명"(안중근)·"세 차례 검사"(중국산 배추) 등
#   228편 중 16편 발동에 6편이 오탐이었다. 외국 소재 편에 한국 기준을 적용하면
#   정상 배경이 기각되고, 기각 산출물이 자동 게시로 이어질 수 있었다).
_AMBIGUOUS = {"한식", "신라", "백제"}   # "차례"·"동지"는 낱말 자체를 좁혀 해결(차례상·동짓날)


def is_korean_topic(*texts):
    """제목·대본 등에 한국 고유 소재 낱말이 있으면 True.

    - 모호한 낱말(차례·동지 등)은 앞뒤가 한글로 이어지지 않을 때만 인정한다.
    - content json에 `"culture_gate": false` 를 두면 옵트아웃한다 —
      소재국이 한국이 아님이 명백한 편(중국산 배추·피사의 사탑 등)에 쓴다.
    """
    blob = " ".join(t for t in texts if t)
    for k in KOREAN_TOPICS:
        if k in _AMBIGUOUS:
            if re.search(r"(?<![가-힣])%s(?![가-힣])" % re.escape(k), blob):
                return True
        elif k in blob:
            return True
    return False


_KEY_CACHE = []   # 이미지마다 keys.env를 다시 열지 않는다 (2026-08-25 감사)


def _key():
    if _KEY_CACHE:
        return _KEY_CACHE[0]
    for line in open(os.path.join(ROOT, "keys.env"), encoding="utf-8"):
        line = line.strip()
        if line.startswith("GEMINI_API_KEY="):
            _KEY_CACHE.append(line.split("=", 1)[1].strip().strip('"'))
            return _KEY_CACHE[0]
    return None


def judge_image(path, timeout=90):
    """이미지 1장 판정. 반환: (foreign: bool|None, 사유 문자열).
    foreign=None 은 '판정 불가'(게이트 고장) — 호출자는 통과시키되 경고를 남겨라."""
    try:
        key = _key()   # try 안 — keys.env 부재·권한 오류가 계약을 깨고 예외로 튀면
        if not key:    #          호출부의 광범위 except가 "무해 통과"로 뭉갠다 (2026-08-25 감사)
            return None, "GEMINI_API_KEY 없음"
        b = base64.b64encode(open(path, "rb").read()).decode()
        body = json.dumps({"contents": [{"parts": [
            {"text": _PROMPT},
            {"inline_data": {"mime_type": "image/jpeg", "data": b}}]}]}).encode()
        req = urllib.request.Request(
            "https://generativelanguage.googleapis.com/v1beta/models/"
            "gemini-2.5-flash:generateContent?key=" + key,
            data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            txt = json.load(r)["candidates"][0]["content"]["parts"][0]["text"]
        m = re.search(r"\{.*\}", txt, re.S)
        d = json.loads(m.group(0)) if m else {}
        return bool(d.get("foreign")), "%s — %s" % (d.get("country", "?"), d.get("reason", ""))
    except Exception as e:
        return None, "판정 실패: %s" % str(e)[:120]


def check_frames(paths):
    """프레임 여러 장 검사. 반환: (위험 목록, 판정불가 목록).
    위험 목록이 비어 있지 않으면 게시하면 안 된다."""
    bad, unknown = [], []
    for p in paths:
        foreign, why = judge_image(p)
        if foreign is True:
            bad.append((p, why))
        elif foreign is None:
            unknown.append((p, why))
    return bad, unknown
