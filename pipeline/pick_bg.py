#!/usr/bin/env python3
# 배경 영상 시각 선별 도우미 (2026-07-29 디렉터 피드백: 배경-소재 연관성 강화).
# content json의 bg_query로 Pexels를 검색해 후보 영상의 미리보기 이미지를 저장한다.
# 데일리 세션은 저장된 미리보기를 Read로 직접 보고, 소재의 시각적 대표물이 실제로
# 보이는 영상의 id를 content json에 "bg_id"로 기록한 뒤 렌더한다.
# 사용: python3 pipeline/pick_bg.py content/오늘날짜.json  (→ out/bg_candidates/에 저장)
import json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "out", "bg_candidates")
PER_QUERY = 4


def load_keys():
    kv = {}
    p = os.path.join(ROOT, "keys.env")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                kv[k.strip()] = v.strip()
    return kv


def main():
    if len(sys.argv) < 2:
        sys.exit("사용: pick_bg.py <content.json>")
    with open(sys.argv[1], encoding="utf-8") as f:
        script = json.load(f)
    queries = script.get("bg_query") or []
    if isinstance(queries, str):
        queries = [queries]
    key = load_keys().get("PEXELS_API_KEY") or os.environ.get("PEXELS_API_KEY")
    if not key or not queries:
        sys.exit("PEXELS_API_KEY 또는 bg_query 없음")

    import requests, shutil
    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(OUT, exist_ok=True)
    # 이미 다른 편에서 쓴 배경 표시 (2026-08-04 실사고: 배경 재탕 — 렌더러가 기계 기각하므로 여기서 미리 보여줌)
    import re as _re, glob as _glob
    def _norm(p):
        return _re.sub(r"\d+$", "", os.path.splitext(os.path.basename(p))[0])
    me = _norm(sys.argv[1])
    used = set()
    for p in _glob.glob(os.path.join(ROOT, "content", "2026-*.json")):
        if p.endswith(".meta.json") or _norm(p) == me:
            continue
        try:
            s = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        ids = s.get("bg_ids") or ([s["bg_id"]] if s.get("bg_id") else [])
        used.update(int(v) for v in ids)
    seen, rows = set(), []
    for qi, q in enumerate(queries):
        try:
            r = requests.get("https://api.pexels.com/videos/search",
                             params={"query": q, "per_page": 15},
                             headers={"Authorization": key}, timeout=20)
            r.raise_for_status()
            vids = [v for v in r.json().get("videos", [])
                    if any(min(f.get("width") or 0, f.get("height") or 0) >= 1080
                           for f in v.get("video_files", []))]
        except Exception as e:
            print("검색 실패(%s): %s" % (q, e))
            continue
        for v in vids[:PER_QUERY]:
            if v["id"] in seen or not v.get("image"):
                continue
            seen.add(v["id"])
            name = "q%d_%s.jpg" % (qi, v["id"])
            try:
                img = requests.get(v["image"], timeout=20)
                img.raise_for_status()
                with open(os.path.join(OUT, name), "wb") as fh:
                    fh.write(img.content)
                portrait = any((f.get("height") or 0) > (f.get("width") or 0)
                               for f in v.get("video_files", []))
                mark = "  ⚠️ 이미 사용된 배경 — 선택 금지(렌더러가 기각함)" if v["id"] in used else ""
                rows.append((name, q, v.get("duration", 0), "세로" if portrait else "가로", mark))
            except Exception:
                continue
    # 사진 후보 (2026-08-04 디렉터 승인 — 켄 번즈 배경): 영상 스톡이 없는 역사·유래·개념 장면용
    for qi, q in enumerate(queries):
        try:
            r = requests.get("https://api.pexels.com/v1/search",
                             params={"query": q, "per_page": 6, "orientation": "portrait"},
                             headers={"Authorization": key}, timeout=20)
            r.raise_for_status()
            photos = r.json().get("photos", [])
        except Exception as e:
            print("사진 검색 실패(%s): %s" % (q, e))
            continue
        for ph in photos[:3]:
            if ph["id"] in seen:
                continue
            seen.add(ph["id"])
            name = "p%d_%s.jpg" % (qi, ph["id"])
            try:
                img = requests.get(ph["src"]["medium"], timeout=20)
                img.raise_for_status()
                with open(os.path.join(OUT, name), "wb") as fh:
                    fh.write(img.content)
                mark = "  ⚠️ 이미 사용된 배경 — 선택 금지(렌더러가 기각함)" if ("photo:%s" % ph["id"]) in used else ""
                rows.append((name, q, 0, "사진(켄번즈)", mark))
            except Exception:
                continue

    for name, q, dur, ori, mark in rows:
        print("%s  | query=%s | %ds | %s%s" % (name, q, dur, ori, mark))
    print("후보 %d개 저장 → %s" % (len(rows), OUT))
    print("다음 단계: 미리보기를 Read로 직접 보고 서로 다른 그림 2~3개를 골라 content json에 기록 —")
    print('  영상(q*.jpg)은 숫자 그대로, 사진(p*.jpg)은 "photo:<id>" 문자열로: 예) "bg_ids": [12345, "photo:67890"]')
    print("  사진은 렌더러가 켄 번즈(느린 줌)로 살린다 — 실사 영상이 없는 역사·유래·개념 씬에 쓰라")


if __name__ == "__main__":
    main()
