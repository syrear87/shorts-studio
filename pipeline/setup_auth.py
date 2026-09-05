#!/usr/bin/env python3
"""구글 OAuth 재인증 (YouTube + Blogger) — 브라우저 동의 1회 필요.

사용: .venv/bin/python3 pipeline/setup_auth.py
기본 브라우저가 열리면 syrear87@gmail.com 계정으로 동의를 완료하라.

스코프 이력:
- 2026-07-29 최초: upload + readonly + yt-analytics.readonly
- 2026-08-02 확장: youtube.force-ssl 추가 — 무긴장 제목 구제 프로토콜의
  videos.update(제목 교체)에 필요 (디렉터 승인).
- 2026-08-27 확장: blogger 추가 — 블로그 자동 발행. 티스토리는 오픈API가 2024-02에
  완전 종료돼 자동화가 불가능했고, 브라우저 자동화는 세션에 묶여 무인 운영이 안 된다.
  Blogger API v3는 현역(최신 rev 2026-07)이고 같은 구글 OAuth를 그대로 쓴다.

**주의**: 이 스크립트는 token.json을 통째로 교체한다. 실패하면 YouTube 업로드가 죽어
  다음 날 07시 슬롯부터 전부 실패한다. 그래서 교체 전에 백업을 남기고, 새 토큰이
  기존 스코프를 모두 포함하는지 검사한 뒤에만 바꾼다.
"""
import os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/blogger",
]

# 이 스코프들이 빠지면 기존 파이프라인이 죽는다 — 교체 전에 반드시 확인한다
REQUIRED = [s for s in SCOPES if "youtube" in s or "yt-analytics" in s]

def main():
    from google_auth_oauthlib.flow import InstalledAppFlow
    cred = os.path.join(ROOT, "credentials.json")
    if not os.path.exists(cred):
        sys.exit("credentials.json 없음")
    token = os.path.join(ROOT, "token.json")
    # 기존 토큰 백업 — 동의 화면에서 체크를 하나라도 빠뜨리면 되돌려야 한다
    if os.path.exists(token):
        import shutil, time as _t
        bak = os.path.join(ROOT, "token.json.bak-%s" % _t.strftime("%Y%m%d-%H%M%S"))
        shutil.copy2(token, bak)
        os.chmod(bak, 0o600)
        print("기존 토큰 백업:", os.path.basename(bak))
    flow = InstalledAppFlow.from_client_secrets_file(cred, SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent")
    got = set(creds.scopes or [])
    missing = [s for s in REQUIRED if s not in got]
    if missing:
        print("\n⛔ 기존 스코프가 빠졌다 — token.json을 바꾸지 않는다:")
        for m in missing:
            print("   -", m)
        print("동의 화면에서 모든 항목에 체크하고 다시 실행하라.")
        sys.exit(1)
    tmp = os.path.join(ROOT, "token.json.tmp")
    with open(tmp, "w") as f:
        f.write(creds.to_json())
    os.chmod(tmp, 0o600)  # 2026-08-02 리뷰 [A13]: 0644로 남던 토큰 퍼미션을 발급 시점에 봉인
    os.replace(tmp, token)
    print("token.json 갱신 완료. 스코프:")
    for s in creds.scopes or SCOPES:
        print(" -", s)

if __name__ == "__main__":
    main()
