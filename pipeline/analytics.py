#!/usr/bin/env python3
"""채널 성과 분석 (읽기 전용, 2026-08-02 신설).

사용: .venv/bin/python3 pipeline/analytics.py

토큰의 youtube.readonly / yt-analytics.readonly 스코프로 동작한다.
게시된 전 영상의 조회수·시청 지속률·구독자 증가·트래픽 소스를 뽑아
content/PERFORMANCE.md 갱신 근거로 쓴다.

⚠️ Analytics API는 처리 지연이 있다(실측 약 3일). 최근 며칠 영상은
   지속률·구독 데이터가 비어 있는 게 정상이다 — 버그로 오해하지 마라.
   조회수 실시간 값은 videos.list 쪽(아래 '실시간' 열)을 봐라.
"""
import datetime, json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build


def creds():
    c = Credentials.from_authorized_user_file(os.path.join(ROOT, "token.json"))
    if c.expired and c.refresh_token:
        c.refresh(Request())
        with open(os.path.join(ROOT, "token.json"), "w") as f:
            f.write(c.to_json())
    return c


def main():
    cr = creds()
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
        metrics="views,averageViewPercentage,subscribersGained",
        dimensions="video", filters="video==" + ",".join(vids), maxResults=200).execute()
    an = {r[0]: r[1:] for r in rep.get("rows", [])}

    print("\n%-11s %7s %7s %6s %6s  %s" % ("게시(KST)", "실시간", "처리분", "지속%", "구독+", "제목"))
    for vid, v in sorted(vids.items(), key=lambda x: x[1]["kst"]):
        a = an.get(vid)
        if a:
            print("%-11s %7d %7d %6.1f %6d  %s" % (
                v["kst"].strftime("%m-%d %H:%M"), v["views"], a[0], a[1], a[2], v["title"][:38]))
        else:
            print("%-11s %7d %7s %6s %6s  %s" % (
                v["kst"].strftime("%m-%d %H:%M"), v["views"], "-", "-", "-", v["title"][:38]))

    src = ya.reports().query(ids="channel==MINE", startDate=start, endDate=today,
                             metrics="views", dimensions="insightTrafficSourceType").execute()
    rows = sorted(src.get("rows", []), key=lambda x: -x[1])
    tot = sum(r[1] for r in rows) or 1
    print("\n트래픽 소스:", ", ".join("%s %d(%.1f%%)" % (r[0], r[1], r[1] / tot * 100) for r in rows[:5]))
    print("\n※ 처리분·지속%·구독+ 이 '-'인 영상은 Analytics 집계 대기 중(약 3일 지연)입니다.")


if __name__ == "__main__":
    main()
