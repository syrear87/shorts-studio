#!/usr/bin/env python3
# 배경 사용 이력 (2026-08-23 리뷰: pick_bg가 used_bg_ids를 쓰려고 렌더러(make_short) 전체를
# 임포트하면 numpy·PIL·폰트 검사까지 끌려온다 — 순수 stdlib 함수라 작은 공유 모듈로 분리).
# make_short와 pick_bg가 함께 쓴다. 여기엔 무거운 의존을 절대 추가하지 마라.
import glob
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def used_bg_ids(exclude_script=None):
    """이미 다른 편에서 쓴 배경 id 집합 (2026-08-04 실사고: 에어컨 유래 편이
    한전 편과 같은 배경을 써서 피드에서 재탕처럼 보임 — 디렉터가 커버를 수동 교체).
    대체본(같은 날짜-슬롯의 재제작, 예: am ↔ am2)끼리는 공유를 허용한다."""
    def norm(p):
        return re.sub(r"\d+$", "", os.path.splitext(os.path.basename(p))[0])
    me = norm(exclude_script) if exclude_script else None
    used = set()
    for p in glob.glob(os.path.join(ROOT, "content", "2026-*.json")):
        if p.endswith(".meta.json") or (me and norm(p) == me):
            continue
        try:
            s = json.load(open(p, encoding="utf-8"))
        except Exception:
            print("경고: %s 파싱 실패 — 배경 재사용 게이트에서 제외됨" % p, flush=True)
            continue
        ids = s.get("bg_ids") or ([s["bg_id"]] if s.get("bg_id") else [])
        used.update(str(v) for v in ids)   # 영상은 "123", 사진은 "photo:123" 문자열로 통일
        # 2026-08-14 감사(critical): 씬별 bg 지정이 표준이 된 뒤 이 게이트가 죽어 있었다 —
        # scenes[].bg도 수집한다. file: 로컬 자산은 제외(디렉터 승인 재사용분, 예: 유성우 실사진)
        for sc in s.get("scenes", []) or []:
            b = sc.get("bg") or sc.get("bg_id")   # bg_id 별칭도 수집 (2026-08-20 정규화와 짝)
            # "file!:"(고정 배경, 2026-08-15 추가)도 같은 로컬 자산이다 — 제외 목록에서 빠져
            # 있어 자체 제작 도판(비교 도판·문제 화면) 재사용이 기각되던 것을 정정 (2026-08-25 감사)
            if b and not (isinstance(b, str) and b.startswith(("file:", "file!:"))):
                used.add(str(b))
    return used
