#!/usr/bin/env python3
# 최초 1회 OAuth 인증 — 브라우저 창이 뜨면 본인 구글 계정으로 로그인.
# "확인되지 않은 앱" 경고가 나오면: 고급 → shorts-studio(안전하지 않음)으로 이동.
import os, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]

def main():
    cred = os.path.join(ROOT, "credentials.json")
    if not os.path.exists(cred):
        sys.exit("credentials.json이 없습니다 — Google Cloud에서 OAuth 데스크톱 클라이언트 JSON을 받아 넣어주세요")
    from google_auth_oauthlib.flow import InstalledAppFlow
    flow = InstalledAppFlow.from_client_secrets_file(cred, SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
    with open(os.path.join(ROOT, "token.json"), "w") as f:
        f.write(creds.to_json())
    print("인증 완료 — token.json 저장됨 (refresh token 포함: %s)" % bool(creds.refresh_token))

if __name__ == "__main__":
    main()
