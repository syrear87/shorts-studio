#!/usr/bin/env python3
"""YouTube OAuth 재인증 — 브라우저 동의 1회 필요.

사용: .venv/bin/python3 pipeline/setup_auth.py
기본 브라우저가 열리면 syrear87@gmail.com 계정으로 동의를 완료하라.

스코프 이력:
- 2026-07-29 최초: upload + readonly + yt-analytics.readonly
- 2026-08-02 확장: youtube.force-ssl 추가 — 무긴장 제목 구제 프로토콜의
  videos.update(제목 교체)에 필요 (디렉터 승인).
"""
import os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]

def main():
    from google_auth_oauthlib.flow import InstalledAppFlow
    cred = os.path.join(ROOT, "credentials.json")
    if not os.path.exists(cred):
        sys.exit("credentials.json 없음")
    flow = InstalledAppFlow.from_client_secrets_file(cred, SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent")
    tmp = os.path.join(ROOT, "token.json.tmp")
    with open(tmp, "w") as f:
        f.write(creds.to_json())
    os.replace(tmp, os.path.join(ROOT, "token.json"))
    print("token.json 갱신 완료. 스코프:")
    for s in creds.scopes or SCOPES:
        print(" -", s)

if __name__ == "__main__":
    main()
