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
    "추석", "한가위", "설날", "정월대보름", "단오", "한식", "동지", "동짓날", "삼짇날", "칠석",
    # 의식주·전통
    "한복", "한옥", "온돌", "장독", "한지", "국악", "판소리", "사물놀이", "탈춤", "씨름",
    "제사", "차례", "세배", "성묘", "돌잔치", "궁궐", "경복궁", "창덕궁", "종묘", "서낭",
    # 음식
    "김치", "송편", "떡국", "비빔밥", "불고기", "막걸리", "된장", "고추장", "삼계탕",
    # 국가상징·역사
    "태극기", "무궁화", "애국가", "한글", "훈민정음", "광복절", "삼일절", "개천절", "현충일",
    "독립운동", "임진왜란", "조선시대", "고려시대", "신라", "백제", "고구려",
    "세종대왕", "이순신", "안중근", "유관순", "김구",
)

# 2026-08-28 실사고로 확대 — **중국·일본만 찾다가 아프리카·동남아를 통과시켰다.**
#   농어촌 기본소득(한국 제도) 편 배경에 동남아 농부(룽기·모내기)와 **아프리카 시장**(사롱·노점)이
#   들어갔는데 게이트가 foreign=false로 통과시켰다. 프롬프트가 "특히 중국과 일본의 요소를
#   찾아라"라고 지시했고, 판정 대상을 **전통 요소**로 한정했기 때문이다.
#   아프리카 시장은 '전통 의상'이 아니라 그냥 일상 풍경이라 어느 조건에도 안 걸렸다.
#   → ①나라를 한정하지 않는다 ②전통뿐 아니라 **일상 풍경의 지역색**(건축·복장·간판·인물 외양·
#     식생·거리)까지 본다 ③기준을 "외국 전통이 있는가"에서 **"한국으로 보이는가"**로 뒤집는다.
_PROMPT = (
    "이 이미지는 한국 소재 영상(한국의 제도·명절·역사·지역)의 배경으로 쓰인다. "
    "**특정 외국의 문화·지역색이 드러나는지** 판정하라. 나라를 중국·일본으로 한정하지 마라. "
    "위험으로 볼 것: ①전통 요소 — 중국(한푸·치파오·홍등·한자 간판)·일본(기모노·도리이·일본어 간판)·"
    "인도/동남아(사리·룽기·삿갓 쓴 모내기)·중동·아프리카(사롱·부부·현지 시장 노점) 등 **어느 나라든**, "
    "②그 지역 사람임이 드러나는 옷차림·외양, ③한국이 아닌 곳임이 드러나는 건축 양식·간판 문자·"
    "거리 풍경·상점 진열·식생. "
    "**건물은 용도로 갈라라**: 주택가·상점가·거리·시장처럼 **사람이 사는 동네**가 보이면 "
    "지붕·담장·창틀·간판·골목 형태가 한국과 다른지 따져 위험으로 판정하라(한국 주택가는 "
    "회색 콘크리트·평지붕·붉은 벽돌·아파트가 흔하다). 반면 발사대·공장·실험실·항만·데이터센터 같은 "
    "**산업·과학 시설**은 어느 나라나 비슷하므로 국적 표식이 없으면 안전이다. "
    "**안전으로 볼 것**: 국적을 특정할 수 없는 것 — 자연물(하늘·들판·벼·곡식·산·바다), 사물 클로즈업, "
    "문화색 없는 산업·과학 시설, 어둠·추상 배경. "
    "**'한국인지 알 수 없다'는 위험이 아니다.** 특정 외국임이 드러날 때만 위험(foreign=true)이다 — "
    "국적 불명은 안전(foreign=false)으로 판정하라. "
    "사람이 등장하고 그 외양·복장이 한국인과 뚜렷이 다르면 위험으로 판정하라. "
    'JSON만 출력: {"foreign":true/false,"country":"중국|일본|동남아|남아시아|중동|아프리카|서양|기타|없음","reason":"한 문장"}'
)


# 부분문자열이면 오탐이 나는 낱말 — 어절 경계를 요구한다 (2026-08-25 감사 실측:
#   "4차례 강진"(피사의 사탑)·"동지 열두 명"(안중근)·"세 차례 검사"(중국산 배추) 등
#   228편 중 16편 발동에 6편이 오탐이었다. 외국 소재 편에 한국 기준을 적용하면
#   정상 배경이 기각되고, 기각 산출물이 자동 게시로 이어질 수 있었다).
_AMBIGUOUS = {"한식", "신라", "백제", "차례", "동지"}

# ⚠️ 한국어는 낱말 뒤에 조사가 붙는다. 후행을 `(?![가-힣])`로 막으면 "신라의"·"백제가"·
#    "한식은"·"동지에"가 전부 미발동해 **게이트가 사실상 꺼진다** (2026-08-25 재감사 실측).
#    → 뒤에는 조사를 허용하고, 오탐은 아래 콜로케이션으로만 걷어낸다.
_JOSA = r"(?=$|[^가-힣]|[은는이가을를의에도와과로만라며야여])"
# "차례"의 오탐은 횟수 용법이다("4차례", "세 차례"). "동지"는 동료 용법("동지 열두 명").
_FALSE_CTX = {
    "차례": r"(?:\d+\s*차례|[한두세네다섯여섯일곱여덟아홉열몇여러]\s*차례|차례로|차례차례)",
    # 동료 용법: "동지 열두 명"·"동지들"·"독립 동지" — 사람을 세는 문맥이면 절기가 아니다
    "동지": r"(?:동지\s*[가-힣\d]*\s*명|동지\s*(?:여러분|들)|독립\s*동지|혁명\s*동지)",
}


def is_korean_topic(*texts):
    """제목·대본 등에 한국 고유 소재 낱말이 있으면 True.

    - 모호한 낱말은 앞이 한글이 아니고 뒤가 조사/경계일 때 인정한다.
    - 알려진 오탐 용법(횟수 '차례', 동료 '동지')은 그 매치만 제외한다.
    - content json에 `"culture_gate": false` 를 두면 옵트아웃한다 —
      소재국이 한국이 아님이 명백한 편(중국산 배추·피사의 사탑 등)에 쓴다.
    """
    blob = " ".join(t for t in texts if t)
    for k in KOREAN_TOPICS:
        if k not in _AMBIGUOUS:
            if k in blob:
                return True
            continue
        pat = r"(?<![가-힣])%s%s" % (re.escape(k), _JOSA)
        false_pat = _FALSE_CTX.get(k)
        for m in re.finditer(pat, blob):
            seg = blob[max(0, m.start() - 6):m.end() + 6]
            if false_pat and re.search(false_pat, seg):
                continue          # 알려진 오탐 용법 — 이 매치만 건너뛴다
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


def judge_image(path, timeout=90, _retry=1):
    """이미지 1장 판정. 반환: (foreign: bool|None, 사유 문자열).
    foreign=None 은 '판정 불가'다 — 한국 소재 편에서 호출자는 **기각**한다(fail-closed).
    씬 수만큼 호출하므로 429·일시 오류 한 번에 슬롯이 죽지 않도록 1회 재시도한다."""
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
            _resp = json.load(r)
        # 200이어도 candidates/parts가 없을 수 있다(SAFETY·MAX_TOKENS 등) — 인덱싱 전에 확인
        _cands = _resp.get("candidates") or []
        _parts = (_cands[0].get("content", {}).get("parts") or []) if _cands else []
        if not _parts:
            return None, "모델이 판정을 반환하지 않음(%s)" % str(
                _cands[0].get("finishReason") if _cands else _resp.get("promptFeedback"))[:60]
        txt = _parts[0].get("text") or ""
        m = re.search(r"\{.*\}", txt, re.S)
        d = json.loads(m.group(0)) if m else {}
        if "foreign" not in d:
            # 모델이 산문·거부·절단 응답을 냈다 — 이건 "깨끗한 프레임"이 아니라
            # "판정하지 못한 상태"다. 통과로 분류하면 fail-closed를 우회한다 (2026-08-25 재감사).
            return None, "판정 파싱 실패: %s" % txt.strip()[:80]
        return bool(d.get("foreign")), "%s — %s" % (d.get("country", "?"), d.get("reason", ""))
    except Exception as e:
        if _retry > 0:
            import time as _t
            _t.sleep(3)
            return judge_image(path, timeout=timeout, _retry=_retry - 1)
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
