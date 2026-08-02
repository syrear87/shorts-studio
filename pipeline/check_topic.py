#!/usr/bin/env python3
"""기각 소재 기계 대조 게이트 (2026-08-02 디렉터 승인 — 프롬프트 전용 규칙 3회 실패로 기계화).

사용: .venv/bin/python3 pipeline/check_topic.py content/YYYY-MM-DD-슬롯.json

content/REJECTED.md의 '기계 대조 키워드' 절과 대본 json(+동명 .meta.json)을
대조해 일치하면 exit 1. make_short.py도 렌더 직전 같은 검사를 내장 호출한다.
키워드가 일치하는데 디렉터가 새로 허용한 소재라면 — 코드를 우회하지 말고
REJECTED.md에서 해당 키워드를 지우는 것이 올바른 경로다.
"""
import json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REJECTED = os.path.join(ROOT, "content", "REJECTED.md")
HEADER = "기계 대조 키워드"


def banned_keywords():
    """REJECTED.md의 '## 기계 대조 키워드' 절에서 '- kw1, kw2' 줄들을 파싱."""
    if not os.path.exists(REJECTED):
        return []
    kws, in_section = [], False
    for line in open(REJECTED, encoding="utf-8"):
        if line.startswith("#") and HEADER in line:
            in_section = True
            continue
        if in_section:
            if line.startswith("#"):
                break
            m = re.match(r"\s*-\s*(.+)", line)
            if m:
                kws += [k.strip() for k in m.group(1).split(",") if k.strip()]
    return kws


def check_text(text):
    return [kw for kw in banned_keywords() if kw in text]


def check_script(script_path):
    """대본 json + 동명 .meta.json 전체 텍스트에서 금지 키워드 검색 → 일치 목록."""
    text = open(script_path, encoding="utf-8").read()
    meta_p = os.path.splitext(script_path)[0] + ".meta.json"
    if os.path.exists(meta_p):
        text += open(meta_p, encoding="utf-8").read()
    return check_text(text)


def main():
    if len(sys.argv) < 2:
        sys.exit("사용: check_topic.py <content/대본.json>")
    hits = check_script(sys.argv[1])
    if hits:
        sys.exit("기각: 영구금지 소재 키워드 일치(%s) — content/REJECTED.md 참조. "
                 "각도를 바꿔도 금지다, 소재를 교체하라" % ", ".join(hits))
    print("기각 소재 대조 통과 (키워드 %d개 검사)" % len(banned_keywords()))


if __name__ == "__main__":
    main()
