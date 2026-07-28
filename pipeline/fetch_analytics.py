#!/usr/bin/env python3
# 전일 채널 성과 수집 → analytics/YYYY-MM-DD.json
import json, os, sys
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def main():
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    token = os.path.join(ROOT, "token.json")
    if not os.path.exists(token):
        sys.exit("token.json 없음 — setup_auth.py 먼저")
    creds = Credentials.from_authorized_user_file(token)
    if creds.expired and creds.refresh_token:
        from google.auth.transport.requests import Request
        creds.refresh(Request())
    yta = build("youtubeAnalytics", "v2", credentials=creds)
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=6)
    resp = yta.reports().query(
        ids="channel==MINE",
        startDate=start.isoformat(), endDate=end.isoformat(),
        metrics="views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,subscribersGained",
        dimensions="day", sort="day",
    ).execute()
    out = {"range": [start.isoformat(), end.isoformat()],
           "headers": [h["name"] for h in resp.get("columnHeaders", [])],
           "rows": resp.get("rows", [])}
    os.makedirs(os.path.join(ROOT, "analytics"), exist_ok=True)
    p = os.path.join(ROOT, "analytics", "%s.json" % end.isoformat())
    with open(p, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("저장:", p)
    if not out["rows"]:
        print("데이터 없음 (신규 채널이면 정상)")

if __name__ == "__main__":
    main()
