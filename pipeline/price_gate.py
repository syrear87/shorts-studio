#!/usr/bin/env python3
"""카드 가격 게이트 — 훅에 박힌 국내 가격이 근거 없이 나가는 걸 막는다.

왜 있는가 (2026-09-04 실사고):
  「아이클라우드 2년 = 외장 SSD 1TB」 카드가 나갔다. 아이클라우드 105,600원은 맞았지만
  SSD 1TB를 10만원으로 잡은 건 **사양서 가격**이었다 — 실거래는 219,000~250,449원이라
  등식이 성립하지 않았다. 스레드 답글 20건 중 9건이 반박이었고 정정을 냈다.
  세션은 "가격을 확인했다"고 믿었다. 확인한 게 판매처가 아니라 스펙 문서였을 뿐이다.

무엇을 막는가 — **훅 층에 한정**한다:
  카드 116장 중 81장(70%)에 가격이 있다. 본문 전체를 막으면 첫 주에 결번으로 자폭한다.
  사람을 데려오는 건 훅이고, 훅에 박힌 숫자가 틀리면 그게 채널의 주장이 된다.
  훅 층 = topic · 훅 카드(title/body/sub) · caption 첫 줄 · threads_text 첫 줄.

기각 두 종류:
  ① **등가 훅** — "A값 = B값" 꼴. 두 값이 같다는 주장은 양쪽 실거래가 다 맞아야 성립하는데,
     한쪽만 틀려도 훅 전체가 거짓이 된다. SSD 편이 정확히 이 형태였다. 즉시 기각.
  ② **근거 없는 국내가** — 훅에 정밀 국내가가 있고 [구매가능]이나 대결 구도와 결합했는데
     `claims[]`에 판매처 근거가 없을 때.

무엇을 통과시키는가 (오탐이 결번을 만들면 게이트가 꺼진다):
  · 개략가 — "2만원이면", "만원 이상", "3만원대" (단정이 아니라 어림이다)
  · 해외가 — "$79", "129달러" (국내 실거래 주장이 아니다)
  · 본문·뒷 카드의 가격 — 훅이 아니면 검사하지 않는다

shadow 모드가 기본이다. `PRICE_GATE_ENFORCE=1`일 때만 실제로 막는다 —
오탐률을 먼저 재고 나서 켠다(2026-09-20 예정).
"""
import datetime
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 정밀 국내가 — 쉼표가 박힌 금액만 '확인했다는 주장'으로 본다.
# "19,900원"은 어느 판매처에서 본 값이지만 "2만원"은 어림이다.
PRECISE_KRW = re.compile(r"(\d{1,3}(?:,\d{3})+)\s*원")
# 어림 표현 — 뒤에 이런 말이 붙으면 단정이 아니다
HEDGE = ("이상", "부터", "안팎", "쯤", "정도", "내외", "대(", "대부터", "선", "가량", "남짓", "약")
# 해외가 — 국내 실거래 주장이 아니다
FOREIGN = re.compile(r"[$€£¥]|\bUSD\b|달러|유로|엔화|위안")
# 대결 구도 — 가격을 무기로 비교하는 훅
VERSUS = ("vs", "VS", "같은 돈이면", "보다 싸", "보다 비싸", "한 개 값", "값이다",
          "절반 값", "돈이면", "차이다", "차이난다")
# 등가 훅 — "A = B" 또는 "A값이 곧 B"
EQUATION = re.compile(r"[^\s=]{2,}\s*=\s*[^\s=]{2,}")

# 가격 맥락 낱말 — 등가 훅을 '값의 등식'으로 읽으려면 훅 층에 돈 얘기가 있어야 한다.
# 없으면 "하품 = 졸림?"·"8/8 = 88건반" 같은 수사적 등호까지 기각된다(2026-09-06 전수 오탐).
PRICE_WORD = ("원", "값", "가격", "요금", "구독료", "월정액", "할인", "정가", "출고가", "실거래")

BUYABLE = "[구매가능]"
BASIS_OK = ("판매처", "공식가", "해외가")


def hook_layer(d):
    """훅 층만 모은다 — 사람을 데려오는 문장들."""
    out = [("topic", d.get("topic", ""))]
    cards = d.get("cards") or []
    if cards:
        h = cards[0]
        for k in ("title", "body", "sub"):
            if h.get(k):
                out.append(("훅카드." + k, h[k]))
    for field in ("caption", "threads_text"):
        t = (d.get(field) or "").strip()
        if t:
            out.append((field + " 첫 줄", t.split("\n")[0]))
    return out


def _hedged(text, pos, end):
    """그 금액 바로 뒤에 어림 표현이 붙었는가."""
    tail = text[end:end + 6]
    return any(tail.lstrip().startswith(h) for h in HEDGE)


def domestic_prices(text):
    """훅 문장에서 '확인했다는 주장'으로 읽히는 국내가만 뽑는다."""
    if FOREIGN.search(text):
        return []
    out = []
    for m in PRECISE_KRW.finditer(text):
        if not _hedged(text, m.start(), m.end()):
            out.append(m.group(1))
    return out


def check_claims(d, prices):
    """훅에 쓴 금액마다 판매처 근거가 있는가."""
    claims = d.get("claims") or []
    missing = []
    for p in prices:
        hit = None
        for c in claims:
            if p.replace(",", "") in json.dumps(c, ensure_ascii=False).replace(",", ""):
                hit = c
                break
        if hit is None:
            missing.append("%s원 — claims[]에 근거 없음" % p)
            continue
        if hit.get("price_basis") not in BASIS_OK:
            missing.append("%s원 — price_basis가 %r (판매처/공식가/해외가 중 하나여야)"
                           % (p, hit.get("price_basis")))
        if not hit.get("price_checked"):
            missing.append("%s원 — price_checked(확인 날짜) 없음" % p)
        if not hit.get("source"):
            missing.append("%s원 — source(확인한 판매처 URL) 없음" % p)
    return missing


def check_rebuttals(d):
    """반박 예상 3개를 미리 적었는가 — 적어보면 훅의 약한 데가 드러난다."""
    rb = d.get("rebuttals") or []
    if len(rb) < 3:
        return ["rebuttals[]가 %d개 (3개 이상 필요)" % len(rb)]
    short = [r for r in rb if len(str(r).strip()) < 20]
    if short:
        return ["rebuttals[] 중 %d개가 20자 미만 — 한 줄로 성의 없이 적은 것" % len(short)]
    return []


def recent_conflicts(d, days=21):
    """같은 품목을 최근에 다른 값으로 말한 적 있는가."""
    topic = d.get("topic", "")
    key = [w for w in re.findall(r"[가-힣A-Za-z]{2,}", topic)[:4] if len(w) >= 2]
    if not key:
        return []
    mine = set()
    for _, t in hook_layer(d):
        mine |= set(domestic_prices(t))
    if not mine:
        return []
    cut = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    out = []
    for f in glob.glob(os.path.join(ROOT, "content", "cards-*.json")):
        base = os.path.basename(f)
        m = re.search(r"(\d{4}-\d{2}-\d{2})", base)
        if not m or m.group(1) < cut:
            continue
        try:
            o = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        if o.get("topic") == topic:
            continue
        if sum(1 for k in key if k in o.get("topic", "")) < 2:
            continue
        theirs = set()
        for _, t in hook_layer(o):
            theirs |= set(domestic_prices(t))
        diff = theirs - mine
        if theirs and diff:
            out.append("%s 에서 같은 품목을 %s원으로 말했다 (지금은 %s원)"
                       % (base, "·".join(sorted(diff)), "·".join(sorted(mine))))
    return out


def check(d):
    """(판정, 사유들). 판정은 'pass' | 'reject'."""
    fails, warns = [], []
    hooks = hook_layer(d)
    buyable = BUYABLE in d.get("topic", "")

    # ① 등가 훅 — 즉시 기각. 단 **훅 층에 돈 얘기가 있을 때만** 값의 등식으로 읽는다.
    hook_text = " ".join(t for _, t in hooks)
    money_ctx = bool(PRECISE_KRW.search(hook_text)) or any(w in hook_text for w in PRICE_WORD)
    for where, t in hooks:
        m = EQUATION.search(t)
        if m and money_ctx and not FOREIGN.search(t):
            fails.append("등가 훅 (%s): %r — 두 값이 같다는 주장은 양쪽 실거래가 "
                         "다 맞아야 성립한다. 한쪽만 틀리면 훅 전체가 거짓이 된다."
                         % (where, m.group(0)[:44]))

    # ② 근거 없는 국내가
    prices, versus_hit = [], False
    for where, t in hooks:
        p = domestic_prices(t)
        if p:
            prices += p
        if any(v in t for v in VERSUS):
            versus_hit = True
    prices = sorted(set(prices))
    if prices and (buyable or versus_hit):
        why = "[구매가능]" if buyable else "대결 구도"
        for msg in check_claims(d, prices):
            fails.append("훅 국내가 근거 미비 (%s 결합): %s" % (why, msg))
        for msg in check_rebuttals(d):
            fails.append("훅에 국내가가 있는데 %s" % msg)

    for msg in recent_conflicts(d):
        warns.append("21일 내 숫자 충돌: " + msg)
    return ("reject" if fails else "pass"), fails, warns


def enforcing():
    return os.environ.get("PRICE_GATE_ENFORCE") == "1"


SHADOW_LOG = os.path.join(ROOT, "logs", "price_gate.jsonl")


def record(topic, verdict, fails, warns, path=""):
    """shadow 기간의 판정을 남긴다 — 9/19에 오탐률을 세어 enforce를 결정한다.

    기록이 없으면 "느낌상 잘 도는 것 같다"로 켜게 된다. 그건 판정이 아니다.
    """
    try:
        with open(SHADOW_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "at": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                "file": os.path.basename(path), "topic": topic[:90],
                "verdict": verdict, "enforced": enforcing(),
                "fails": fails, "warns": warns,
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass


def report():
    """shadow 기간 판정 요약 — enforce 결정의 근거."""
    if not os.path.exists(SHADOW_LOG):
        print("아직 기록이 없다 — 카드를 렌더하면 쌓인다")
        return 0
    rows = []
    for line in open(SHADOW_LOG, encoding="utf-8"):
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    seen, uniq = set(), []
    for r in reversed(rows):          # 같은 파일은 마지막 판정만
        if r.get("file") in seen:
            continue
        seen.add(r.get("file"))
        uniq.append(r)
    rej = [r for r in uniq if r["verdict"] == "reject"]
    print("=== 가격 게이트 shadow — 카드 %d장 중 기각 %d장 (%.1f%%) ==="
          % (len(uniq), len(rej), len(rej) / max(1, len(uniq)) * 100))
    print()
    for r in rej:
        print("■ %s" % r["topic"])
        for f in r["fails"]:
            print("   · " + f.split(" — ")[0])
    print()
    print("※ enforce 판정(2026-09-20): 이 목록을 눈으로 훑어 **오탐이 0인지** 본다.")
    print("  오탐이란 '가격 근거가 실제로 충분한데 걸린 것'이다. 기각률이 낮은 게 아니라")
    print("  오탐이 없는 게 조건이다 — 하루 5장 중 1장 넘게 막히면 결번으로 자폭한다.")
    return 0


def main(argv):
    paths = argv[1:]
    if "--report" in paths:
        return report()
    if not paths:
        print("사용법: price_gate.py <cards-*.json> [...]  (--all 전수 / --report 요약)")
        return 2
    if paths == ["--all"]:
        paths = sorted(glob.glob(os.path.join(ROOT, "content", "cards-*.json")))
    bad = 0
    for p in paths:
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception as e:
            print("[price_gate] %s 읽기 실패: %s" % (os.path.basename(p), e))
            continue
        verdict, fails, warns = check(d)
        record(d.get("topic", ""), verdict, fails, warns, p)
        if verdict == "reject":
            bad += 1
            mode = "기각" if enforcing() else "경고(shadow)"
            print("[price_gate] ✗ %s — %s" % (os.path.basename(p), mode))
            for f in fails:
                print("    · " + f)
        for w in warns:
            print("[price_gate] ⚠ %s — %s" % (os.path.basename(p), w))
    if bad and enforcing():
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
