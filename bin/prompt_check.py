#!/usr/bin/env python3
"""프롬프트 정합성 검사 — 정본이 둘로 갈라지는 걸 기계가 막는다.

왜 필요한가 (2026-09-05):
  같은 규칙이 DAILY_PROMPT와 CARD_PROMPT에 복사돼 있었다. 9/2에 디렉터가 영상을
  5편→3편으로 되돌렸을 때 DAILY만 고쳐졌고, **카드 세션은 사흘 동안 이미 없어진
  "영상 5편 / 15:20·19:00 슬롯"을 읽고 있었다.** 카드 발수(5장인데 본문 6장),
  카드 게시처(스레드인데 본문 "인스타에 게시")도 같은 식으로 어긋나 있었다.
  사람이 두 파일을 동시에 고치기를 기대하면 언젠가 반드시 한쪽이 낡는다.

검사 항목:
  1. 절 중복 — 같은 '## 제목'이 두 파일에 있으면 실패 (공통 규칙은 RULES.md에만)
  2. 편성 모순 — RULES.md §편성 정본의 편수·슬롯과 다른 숫자가 본문에 있으면 실패
  3. 게시처 모순 — 카드가 인스타로 간다는 서술이 남아 있으면 실패
  4. 정본 존재 — RULES.md가 비었거나 편성 표를 못 읽으면 실패

이력 서술은 통과시킨다 — '이력', '폐지', '종전', '~~취소선~~', '→'가 있는 줄은
과거를 적은 것이지 지시가 아니다.
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RULES, DAILY, CARD = "RULES.md", "DAILY_PROMPT.md", "CARD_PROMPT.md"
HISTORY = ("이력", "폐지", "종전", "~~", "→", "복원 시", "당시", "그때")


def _read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


def _is_history(line):
    return any(h in line for h in HISTORY)


def canon():
    """RULES.md §편성 정본 표에서 편수·슬롯을 읽는다. 검사의 기준점."""
    t = _read(RULES)
    m = re.search(r"\|\s*\*\*영상\*\*\s*\|\s*\*\*(\d+)편\*\*\s*\|\s*([^|]+)\|", t)
    c = re.search(r"\|\s*\*\*카드\*\*\s*\|\s*\*\*(\d+)장\*\*\s*\|\s*([^|]+)\|", t)
    if not (m and c):
        raise SystemExit("[prompt_check] ✗ RULES.md에서 편성 정본 표를 못 읽었다 — 표 형식이 바뀌었나?")
    slots = lambda s: re.findall(r"\d{1,2}:\d{2}|\d{1,2}:00", s)
    return {"video_n": int(m.group(1)), "card_n": int(c.group(1)),
            "video_slots": slots(m.group(2)), "card_slots": slots(c.group(2))}


def check_duplicate_sections(fails):
    heads = {}
    for name in (RULES, DAILY, CARD):
        for line in _read(name).splitlines():
            if line.startswith("## "):
                # 제목 '머리'만 비교한다 — 부제·괄호는 파일마다 다르게 적혀 있어서
                # 통째로 비교하면 같은 규칙의 복사본을 못 잡는다(2026-09-05 검사기 자체 회귀).
                key = re.split(r"\s*[—((]", line[3:].strip())[0].strip()
                heads.setdefault(key, []).append(name)
    for key, where in heads.items():
        if len(where) > 1:
            fails.append("절 중복: '%s' 가 %s 에 함께 있다 — 공통 규칙은 %s 에만 둬라"
                         % (key, " / ".join(where), RULES))


def check_schedule(fails, c):
    # ⚠️ '하루 총량'을 말하는 표현만 검사한다. '하루 1장까지'(유출 쿼터), '2장은 공유형'
    # 같은 **항목별 쿼터**는 총량이 아니다 — 여기서 걸면 정상 규칙이 전부 오탐된다.
    pats = [(r"영상[ *]{0,3}(\d+)편", c["video_n"], "영상 편수"),
            (r"하루 (\d+)편 배분", c["video_n"], "영상 편수"),
            (r"(\d+)편 체제", c["video_n"], "영상 편수"),
            (r"하루 (\d+)장 중", c["card_n"], "카드 장수"),
            (r"하루 (\d+)장에", c["card_n"], "카드 장수"),
            (r"하루 (\d+)발", c["card_n"], "카드 장수")]
    # ('카드 40장 전수 실측' 같은 **표본 수**는 편성이 아니다 — 패턴에서 뺐다)
    for name in (RULES, DAILY, CARD):
        for i, line in enumerate(_read(name).splitlines(), 1):
            if _is_history(line):
                continue
            for pat, want, label in pats:
                for got in re.findall(pat, line):
                    if int(got) != want:
                        fails.append("%s:%d %s 모순 — 정본 %d인데 '%s' (%s)"
                                     % (name, i, label, want, got, line.strip()[:70]))
    # 폐지된 슬롯 시각이 현행 편성처럼 적혀 있는가
    live = set(c["video_slots"]) | set(c["card_slots"])
    for name in (DAILY, CARD):
        for i, line in enumerate(_read(name).splitlines(), 1):
            if _is_history(line) or "현행" not in line:
                continue
            for t in re.findall(r"\d{1,2}:\d{2}", line):
                if t not in live:
                    fails.append("%s:%d 폐지 슬롯 %s 가 현행 편성처럼 적혀 있다" % (name, i, t))


def check_destination(fails):
    bad = re.compile(r"카드[^\n]{0,40}(인스타|IG)[^\n]{0,12}(게시|올리|업로드)"
                     r"|(인스타|IG)[^\n]{0,12}게시[^\n]{0,20}카드")
    for name in (RULES, DAILY, CARD):
        for i, line in enumerate(_read(name).splitlines(), 1):
            # 서술(인용·사고 기록)과 금지문은 지시가 아니다
            if (_is_history(line) or line.lstrip().startswith(">")
                    or any(k in line for k in ("않는다", "말라", "마라", "금지", "사고"))):
                continue
            if bad.search(line):
                fails.append("%s:%d 카드→인스타 서술 — 카드는 스레드·블로그 전용이다: %s"
                             % (name, i, line.strip()[:70]))


def main():
    fails = []
    c = canon()
    check_duplicate_sections(fails)
    check_schedule(fails, c)
    check_destination(fails)
    if fails:
        print("[prompt_check] ✗ %d건" % len(fails), flush=True)
        for f in fails:
            print("   · " + f, flush=True)
        if "--alert" not in sys.argv:      # 손으로 돌릴 땐 조용히 (dm_tick만 --alert)
            return 1
        try:
            subprocess.run(["bash", os.path.join(ROOT, "bin", "tg-send.sh"),
                            "⚠️ 프롬프트 정합성 %d건 — 정본과 본문이 어긋났습니다\n\n%s"
                            % (len(fails), "\n".join("· " + f[:120] for f in fails[:5]))],
                           timeout=30, check=False)
        except Exception:
            pass
        return 1
    print("[prompt_check] ✓ 영상 %d편 %s · 카드 %d장 %s — 모순 없음"
          % (c["video_n"], "/".join(c["video_slots"]),
             c["card_n"], "/".join(c["card_slots"])), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
