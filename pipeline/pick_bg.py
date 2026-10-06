#!/usr/bin/env python3
# 배경 영상 시각 선별 도우미 (2026-07-29 디렉터 피드백: 배경-소재 연관성 강화).
# content json의 bg_query로 Pexels를 검색해 후보 영상의 미리보기 이미지를 저장한다.
# 데일리 세션은 저장된 미리보기를 Read로 직접 보고, 소재의 시각적 대표물이 실제로
# 보이는 영상의 id를 content json에 "bg_id"로 기록한 뒤 렌더한다.
# 사용: .venv/bin/python3 pipeline/pick_bg.py content/오늘날짜.json  (→ out/bg_candidates/에 저장)
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
    # 2026-08-23 감사: 자체 사본이 드리프트해 scenes[].bg 수집이 누락됐었다 — 정본 함수를 공유한다.
    # (bg_history는 stdlib 전용 — 렌더러의 numpy·PIL·폰트 의존을 여기로 끌고 오지 않는다. 2026-08-23 리뷰)
    from bg_history import used_bg_ids
    used = used_bg_ids(exclude_script=sys.argv[1])
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
                mark = "  ⚠️ 이미 사용된 배경 — 선택 금지(렌더러가 기각함)" if str(v["id"]) in used else ""
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

    # 🚨 문화 사전 필터 (2026-08-25 실사고) — 한국 고유 소재면 후보 단계에서 미리 걸러
    #   세션이 애초에 위험한 그림을 고를 수 없게 한다(렌더 후 게이트는 마지막 방어선일 뿐).
    #   사진 후보(p*.jpg)만 검사한다 — 영상 후보는 정지 프레임이 없어 여기선 판정 불가.
    try:
        from culture_gate import is_korean_topic, judge_image
        # 2026-08-28 감사: title+자막만 보면 한국 소재 낱말이 나레이션·topic·chip에만 있는
        # 편은 사전 필터가 발동하지 않았다 — 판정 재료를 넓힌다.
        _blob = " ".join([str(script.get(k) or "") for k in ("title", "topic", "chip")] +
                         [str(sc.get("voice") or "") for sc in script.get("scenes", [])] +
                         [ln for sc in script.get("scenes", []) for ln, _ in sc.get("lines", [])])
        if is_korean_topic(_blob):
            print("\n🚨 한국 고유 소재 감지 — 사진 후보의 외국 전통 요소를 미리 검사합니다", flush=True)
            checked = []
            for i, (name, q, dur, ori, mark) in enumerate(rows):
                # 영상 후보(q*.jpg)도 검사한다 — 미리보기 JPEG가 이미 저장돼 있고 형식도 같다.
                # 8/25 사고의 원인은 "bg_query에 korean을 넣었는데 Pexels가 중국 사진을 반환"인데,
                # 정작 그 검색 경로(영상)를 건너뛰면 게이트에 구멍이 남는다 (2026-08-25 감사).
                foreign, why = judge_image(os.path.join(OUT, name))
                if foreign is True:
                    mark += "  ⛔ 외국·타국 요소 감지 — 선택 금지(%s)" % why[:110]
                elif foreign is None:
                    mark += "  ❔ 문화 판정 불가 — 직접 눈으로 확인"
                checked.append((name, q, dur, ori, mark))
            rows = checked
    except Exception as _e:
        print("경고: 문화 사전 필터 실행 실패(무해):", str(_e)[:120], flush=True)

    # 🎯 실물 후보를 **먼저** 보여준다 (2026-09-29). 9/28 규칙에 "커먼즈 먼저"를 넣었는데도
    #   첫 적용 슬롯(스타십 편)이 Pexels만 돌려 훅 화면에 우주왕복선이 나갔다 — 세션은 기본
    #   도구의 출력만 본다. 그래서 기본 도구가 실물 후보를 같이 내놓게 했다.
    #   검색어: 대본의 real_query(고유명사·영문명 — "SpaceX Starship", "Jingwansa Taegukgi")가
    #   정본이고, 없으면 bg_query 앞 3개로 대신한다(일반 검색어라 적중률이 낮다).
    real_q = script.get("real_query") or queries[:3]
    if isinstance(real_q, str):
        real_q = [real_q]
    try:
        from fetch_commons import search as _cs, _get as _cget
        import re as _re
        print("\n🎯 실물 후보 (위키미디어 커먼즈 — 자유 라이선스, 먼저 검토하라)", flush=True)
        _n = 0
        for qi, rq in enumerate(real_q[:4]):
            found, _sk = _cs(rq, n=3)
            for i, it in enumerate(found):
                name = "c%d_%d.jpg" % (qi, i)
                try:
                    with _cget(_re.sub(r"/\d+px-", "/480px-", it["url"]), timeout=60) as r_, \
                            open(os.path.join(OUT, name), "wb") as f_:
                        f_.write(r_.read())
                except Exception:
                    continue
                _n += 1
                print('%s  | query=%s | %s | %s  →  "bg": "commons:%s"'
                      % (name, rq, it["license"], it["title"][5:50], it["title"]))
        if not _n:
            print("  (실물 후보 없음 — real_query에 고유명사·영문명을 넣어 다시 돌려라. 그래도 없으면 "
                  "Pexels는 **같은 대상**일 때만 쓰고, 아니면 소재를 바꿔라)")
        print()
    except Exception as _e:
        print("경고: 커먼즈 후보 조회 실패(무해):", str(_e)[:120], flush=True)

    # 📸 실제 장면 후보 (2026-10-07 디렉터: "손흥민 골장면 스틸샷이나 경기 장면을 넣어야지").
    #   커먼즈는 '그 선수'까지고 '어제 그 골'은 뉴스 사진에만 있다. scene_query(사건+날짜·경기명)가
    #   정본, 없으면 제목으로 검색한다. 인물·경기·사건 소재의 훅은 이 후보에서 골라라.
    scene_q = script.get("scene_query") or [str(script.get("title") or "")[:40]]
    if isinstance(scene_q, str):
        scene_q = [scene_q]
    try:
        from fetch_scene import news_search, og_image, naver_images, _get as _sget
        print("📸 실제 장면 후보 (뉴스 사진 — 그 경기·그 장면이면 이걸 훅에 써라)", flush=True)
        _k, _seen = 0, set()
        for rq in scene_q[:3]:
            cands = []
            try:
                for title, link, _ in news_search(rq, n=8):
                    img, art = og_image(link)
                    if img and img not in _seen:
                        cands.append((img, art, title))
            except Exception:
                pass
            if len(cands) < 3:
                try:
                    for img in naver_images(rq, n=6):
                        if img not in _seen:
                            cands.append((img, img, "(네이버 이미지 검색)"))
                except Exception:
                    pass
            for img, ref, title in cands[:6]:
                _seen.add(img)
                name = "s%d.jpg" % _k
                try:
                    with _sget(img, timeout=30) as r_, open(os.path.join(OUT, name), "wb") as f_:
                        f_.write(r_.read())
                except Exception:
                    continue
                _k += 1
                print('%s  | query=%s | %s  →  "bg": "scene:%s"' % (name, rq[:20], title[:40], ref))
        if not _k:
            print("  (장면 후보 없음 — scene_query에 경기명·사건명+날짜를 넣어 다시)")
        print()
    except Exception as _e:
        print("경고: 장면 후보 조회 실패(무해):", str(_e)[:120], flush=True)

    for name, q, dur, ori, mark in rows:
        print("%s  | query=%s | %ds | %s%s" % (name, q, dur, ori, mark))
    print("후보 %d개 저장 → %s" % (len(rows), OUT))
    print("다음 단계: 미리보기를 Read로 직접 보고 서로 다른 그림 2~3개를 골라 content json에 기록 —")
    print('  영상(q*.jpg)은 숫자 그대로, 사진(p*.jpg)은 "photo:<id>" 문자열로: 예) "bg_ids": [12345, "photo:67890"]')
    print("  사진은 렌더러가 켄 번즈(느린 줌)로 살린다 — 실사 영상이 없는 역사·유래·개념 씬에 쓰라")


if __name__ == "__main__":
    main()
