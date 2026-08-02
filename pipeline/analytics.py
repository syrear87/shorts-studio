#!/usr/bin/env python3
"""채널 성과 분석 (읽기 전용, 2026-08-02 신설).

사용: .venv/bin/python3 pipeline/analytics.py

토큰의 youtube.readonly / yt-analytics.readonly 스코프로 동작한다.
게시된 전 영상의 조회수·시청 지속률·구독자 증가·트래픽 소스를 뽑아
content/PERFORMANCE.md 갱신 근거로 쓴다.

⚠️ Analytics API는 처리 지연이 있다(실측 약 3일). 최근 며칠 영상은
   지속률·구독 데이터가 비어 있는 게 정상이다 — 버그로 오해하지 마라.
   조회수 실시간 값은 videos.list 쪽(아래 '실시간' 열)을 봐라.

📐 KPI 정의 (2026-08-02 심층 분석으로 확정):
   - eng% = engagedViews/views. 피드에서 스와이프 안 당하고 실제 시청된 비율.
     조회수와 r=0.878 — 조회수는 여기서 결정된다. 30% 미만이면 훅 첫 줄·첫
     프레임을 부검하라.
   - subs/1kE = engagedViews 1천 회당 구독 증가. **유일한 전환 KPI다.**
     좋아요율은 구독 예측 지표가 아니다(실측 반례: 좋아요율 상위 편 구독 0).
   - YPP 유효 조회수는 engagedViews 기준이다. '실시간' 열은 배치 갱신
     캐시라(한 번에 +324 점프 실측) 분당 속도 비교·YPP 진척 계산에 쓰지 마라.
"""
import datetime, json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from googleapiclient.discovery import build
from google_creds import load_creds  # 2026-08-02 리뷰 [A13]: 토큰 취급 공용 헬퍼로 통일


def main():
    cr = load_creds()
    yt = build("youtube", "v3", credentials=cr)
    ya = build("youtubeAnalytics", "v2", credentials=cr)

    ch = yt.channels().list(part="contentDetails,statistics,snippet", mine=True).execute()["items"][0]
    print("채널: %s | 구독자 %s | 처리완료 총조회 %s" % (
        ch["snippet"]["title"], ch["statistics"].get("subscriberCount"),
        ch["statistics"].get("viewCount")))

    ids, token = [], None
    up = ch["contentDetails"]["relatedPlaylists"]["uploads"]
    while True:
        r = yt.playlistItems().list(part="contentDetails", playlistId=up,
                                    maxResults=50, pageToken=token).execute()
        ids += [i["contentDetails"]["videoId"] for i in r["items"]]
        token = r.get("nextPageToken")
        if not token:
            break

    vids = {}
    for i in range(0, len(ids), 50):
        for v in yt.videos().list(part="snippet,statistics,status",
                                  id=",".join(ids[i:i + 50])).execute()["items"]:
            if v["status"]["privacyStatus"] != "public":
                continue
            kst = datetime.datetime.fromisoformat(
                v["snippet"]["publishedAt"].replace("Z", "+00:00")) + datetime.timedelta(hours=9)
            vids[v["id"]] = {"title": v["snippet"]["title"], "kst": kst,
                             "views": int(v["statistics"].get("viewCount", 0)),
                             "likes": int(v["statistics"].get("likeCount", 0))}
    if not vids:
        sys.exit("공개 영상이 없습니다")

    # Analytics는 태평양시(PT) 기준으로 날짜를 자른다. KST 게시일을 그대로 시작일로 쓰면
    # 첫날 조회수가 통째로 빠진다(실측: 코스피 편 1457 → 26으로 누락). 넉넉히 3일 당긴다.
    start = (min(v["kst"] for v in vids.values()).date() - datetime.timedelta(days=3)).strftime("%Y-%m-%d")
    today = datetime.date.today().strftime("%Y-%m-%d")
    rep = ya.reports().query(
        ids="channel==MINE", startDate=start, endDate=today,
        metrics="views,engagedViews,averageViewPercentage,subscribersGained",
        dimensions="video", filters="video==" + ",".join(vids), maxResults=200).execute()
    an = {r[0]: r[1:] for r in rep.get("rows", [])}

    print("\n%-11s %7s %7s %5s %6s %5s %7s  %s" % (
        "게시(KST)", "실시간", "처리분", "eng%", "지속%", "구독+", "subs/1kE", "제목"))
    for vid, v in sorted(vids.items(), key=lambda x: x[1]["kst"]):
        a = an.get(vid)
        if a:
            views, engaged, avp, subs = a[0], a[1], a[2], a[3]
            engp = engaged / views * 100 if views else 0.0
            spk = subs / engaged * 1000 if engaged else 0.0
            flag = " ⚠️훅부검" if engp < 30 and views >= 100 else ""
            print("%-11s %7d %7d %5.1f %6.1f %5d %7.1f  %s%s" % (
                v["kst"].strftime("%m-%d %H:%M"), v["views"], views, engp, avp, subs,
                spk, v["title"][:36], flag))
        else:
            print("%-11s %7d %7s %5s %6s %5s %7s  %s" % (
                v["kst"].strftime("%m-%d %H:%M"), v["views"], "-", "-", "-", "-", "-",
                v["title"][:36]))

    src = ya.reports().query(ids="channel==MINE", startDate=start, endDate=today,
                             metrics="views", dimensions="insightTrafficSourceType").execute()
    rows = sorted(src.get("rows", []), key=lambda x: -x[1])
    tot = sum(r[1] for r in rows) or 1
    print("\n트래픽 소스:", ", ".join("%s %d(%.1f%%)" % (r[0], r[1], r[1] / tot * 100) for r in rows[:5]))
    print("\n※ 처리분·지속%·구독+ 이 '-'인 영상은 Analytics 집계 대기 중(약 3일 지연)입니다.")


if __name__ == "__main__":
    main()
