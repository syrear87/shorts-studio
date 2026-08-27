#!/usr/bin/env python3
"""카드 이미지 재사용 이력 — 같은 사진이 피드에 반복되는 것을 막는다. (2026-08-27 실사고로 신설)

사고: 8/27 아이폰 카드가 `iphone_event.jpg`(8/20 사용)와 `iphone18promax_1.jpg`(8/23 사용)를
  **두 장 모두 재사용**했다. 소재 각도까지 "아이폰 지금 사면 N일 뒤 후회"로 8/20과 같아서
  디렉터가 피드에서 바로 알아봤다: "1주전 거랑 이미지 같은 거 썼는데?"

왜 여태 없었나: 영상 배경에는 재사용 게이트(bg_history.py)가 있었는데 **카드에는 없었다.**
  카드가 이미지가 주인공인 포맷인데 정작 이미지 중복 검사가 없던 비대칭이다.

stdlib 전용 — make_cards가 PIL 없이도 임포트할 수 있게 한다(bg_history.py 선례).
"""
import glob
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTENT = os.path.join(ROOT, "content")


def used_card_images(exclude=None, days=None):
    """이미 게시된 카드가 쓴 이미지 경로 집합.

    exclude: 이번에 렌더하는 json 경로(자기 자신은 제외)
    days: None이면 전체, 숫자면 파일명 날짜 기준 최근 N일치만
    """
    ex = os.path.abspath(exclude) if exclude else None
    used = {}
    for p in glob.glob(os.path.join(CONTENT, "cards-*.json")):
        if ex and os.path.abspath(p) == ex:
            continue
        base = os.path.basename(p)
        if days:
            # cards-YYYY-MM-DD-이름.json 에서 날짜를 뽑아 최근 N일만
            parts = base.split("-")
            if len(parts) >= 4:
                stamp = "-".join(parts[1:4])
                try:
                    import datetime
                    d = datetime.date.fromisoformat(stamp)
                    if (datetime.date.today() - d).days > days:
                        continue
                except ValueError:
                    pass
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        for c in data.get("cards", []) or []:
            img = (c or {}).get("img")
            if img:
                used.setdefault(os.path.basename(str(img)), base)
    return used


def check(script_path, cards, days=30):
    """중복 이미지 목록을 돌려준다. [(파일명, 이전에 쓴 카드 json), ...]"""
    used = used_card_images(exclude=script_path, days=days)
    hits = []
    for c in cards or []:
        img = (c or {}).get("img")
        if not img:
            continue
        name = os.path.basename(str(img))
        if name in used:
            hits.append((name, used[name]))
    return hits
