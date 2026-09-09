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

2026-09-10부터 **막는 것이 기본이다.** shadow로 147장을 재서 기각 4장(2.7%),
그중 오탐 0건이었다 — 전환 기준("목록에 오탐이 0인가")을 이미 만족했고, 9/20까지
기다리는 동안 같은 사고가 또 날 이유가 없다. 실제로 SSD 편은 이 게이트가 잡아내는
카드였는데 하루 차이로 게이트보다 먼저 나갔고, 답글 25건 중 11건이 반박이었다.
끄려면 `PRICE_GATE_ENFORCE=0` — 오탐으로 결번이 나면 그때 끄고 규칙을 고친다.
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
# 어림 금액 — "10만원"·"2만원"·"3만 원". 단정이 아니라 어림이므로 **혼자서는** 걸지 않지만,
# 등가 훅·대결 구도와 결합하면 근거를 요구한다. 2026-09-04 SSD 사고의 원문이 정확히
# 「2년이면 10만원 나간다」였다 — 쉼표가 없어 종전 게이트를 그대로 통과했다.
ROUND_KRW = re.compile(r"(\d{1,4})\s*만\s*원")
# 등호 없는 등가 표현 — "="만 찾으면 사고 원문 「한 개 값이다」가 빠져나간다
EQ_WORDS = ("＝", "≒", "≈", "한 개 값", "값이다", "같은 값", "똑같다", "맞먹", "와 같다", "과 같다")
# 어림 표현 — 뒤에 이런 말이 붙으면 단정이 아니다
HEDGE = ("이상", "부터", "안팎", "쯤", "정도", "내외", "대(", "대부터", "선", "가량", "남짓", "약")
# 해외가 — 국내 실거래 주장이 아니다
FOREIGN = re.compile(r"[$€£¥]|\bUSD\b|달러|유로|엔화|위안")
# 대결 구도 — 가격을 무기로 비교하는 훅
VERSUS = ("vs", "VS", "같은 돈이면", "보다 싸", "보다 비싸", "절반 값", "돈이면",
          "차이다", "차이난다")   # '한 개 값'·'값이다'는 EQ_WORDS로 옮겼다 — 등가는 대결의 강한 형태
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


_HEDGE_TAIL = re.compile(r"\s*(이상|부터|안팎|쯤|정도|내외|가량|남짓|대(?![가-힣])|선(?![가-힣]))")
_HEDGE_HEAD = re.compile(r"(약|대략|어림잡아|한)\s*$")


def _hedged(text, pos, end):
    """그 금액 앞뒤에 어림 표현이 붙었는가. 낱말 경계를 본다 —
    종전엔 접두 검사만 해서 '19,900원 선착순'의 '선'을 어림으로 읽고(미탐),
    '약 19,900원'은 앞의 '약'을 못 봐 정밀가로 읽었다(오탐). 2026-09-06 감사."""
    return bool(_HEDGE_TAIL.match(text[end:]) or _HEDGE_HEAD.search(text[:pos]))


def domestic_prices(text, rough=False):
    """훅 문장의 국내가. rough=True면 어림 금액("10만원")도 포함한다.

    기본은 정밀가(쉼표)만이다 — 어림가에 매번 판매처 근거를 요구하면 결번이 난다.
    다만 **등가·대결 훅과 결합할 때는 어림가도 주장**이다. SSD 편이 그랬다."""
    if FOREIGN.search(text):
        return []
    out = []
    for m in PRECISE_KRW.finditer(text):
        if not _hedged(text, m.start(), m.end()):
            out.append(m.group(1))
    if rough:
        for m in ROUND_KRW.finditer(text):
            if not _hedged(text, m.start(), m.end()):
                out.append(m.group(0).replace(" ", ""))
    return out


def _won(p):
    """어림가는 이미 '원'을 달고 온다 — '10만원원'이 되지 않게."""
    return p if p.endswith("원") else p + "원"


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
            missing.append("%s — claims[]에 근거 없음" % _won(p))
            continue
        if hit.get("price_basis") not in BASIS_OK:
            missing.append("%s — price_basis가 %r (판매처/공식가/해외가 중 하나여야)"
                           % (_won(p), hit.get("price_basis")))
        if not hit.get("price_checked"):
            missing.append("%s — price_checked(확인 날짜) 없음" % _won(p))
        if not hit.get("source"):
            missing.append("%s — source(확인한 판매처 URL) 없음" % _won(p))
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
    # '원'을 부분문자열로 보면 원래·원인·직원·원룸·복원이 전부 돈 얘기가 된다(훅 층 13장 오탐).
    money_ctx = bool(PRECISE_KRW.search(hook_text) or ROUND_KRW.search(hook_text)
                     or re.search(r"[\d만천억]\s*원(?![가-힣])", hook_text)
                     or any(w in hook_text for w in PRICE_WORD if w != "원"))
    for where, t in hooks:
        if FOREIGN.search(t):
            continue
        m = EQUATION.search(t)
        eqw = next((w for w in EQ_WORDS if w in t), None)
        if (m or eqw) and money_ctx:
            shown = m.group(0)[:44] if m else eqw
            fails.append("등가 훅 (%s): %r — 두 값이 같다는 주장은 양쪽 실거래가 "
                         "다 맞아야 성립한다. 한쪽만 틀리면 훅 전체가 거짓이 된다."
                         % (where, shown))

    # ② 근거 없는 국내가
    versus_hit = any(any(v in t for v in VERSUS) or any(w in t for w in EQ_WORDS)
                     or EQUATION.search(t) for _, t in hooks)
    # 대결·등가 훅이면 어림가("10만원")도 주장으로 본다 — SSD 편의 오류가 정확히 거기 있었다.
    prices = sorted(set(p for _, t in hooks for p in domestic_prices(t, rough=versus_hit)))
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
    """막을 것인가. 기본 True — 끄려면 PRICE_GATE_ENFORCE=0 (2026-09-10 전환)."""
    return os.environ.get("PRICE_GATE_ENFORCE") != "0"


SHADOW_LOG = os.path.join(ROOT, "logs", "price_gate.jsonl")


def record(topic, verdict, fails, warns, path=""):
    """판정을 남긴다 — 오탐이 쌓이는지 계속 본다.

    기록이 없으면 "느낌상 잘 도는 것 같다"로 판단하게 된다. 그건 판정이 아니다.
    enforce로 켠 뒤에도 계속 적는다 — 결번이 나면 여기서 원인을 센다.
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
    """판정 요약 — 오탐 감시용."""
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
    print("=== 가격 게이트 — 카드 %d장 중 기각 %d장 (%.1f%%) ==="
          % (len(uniq), len(rej), len(rej) / max(1, len(uniq)) * 100))
    print()
    for r in rej:
        print("■ %s" % r["topic"])
        for f in r["fails"]:
            print("   · " + f.split(" — ")[0])
    print()
    print("※ 2026-09-10부터 막는다. 이 목록에 **오탐**이 보이면 규칙을 고쳐라 —\n"
          "   오탐 하나가 결번 하나다. 끄려면 PRICE_GATE_ENFORCE=0.")
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
