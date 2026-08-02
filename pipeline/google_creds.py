#!/usr/bin/env python3
"""token.json 공용 헬퍼 (2026-08-02 리뷰 [A13] 신설).

analytics/retitle/upload_youtube 3곳에서 제각각이던(스코프 검사·저장 유무·원자성)
토큰 로드→스코프 검사→만료 refresh→저장 보일러플레이트를 함수 하나로 통일.
저장은 tmp에 쓰고 chmod 600 후 os.replace — 원자성·퍼미션을 동시에 보장.
사용: from google_creds import load_creds  (pipeline/ 스크립트 직접 실행 시 sys.path[0]이 pipeline/)
"""
import os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKEN = os.path.join(ROOT, "token.json")


def load_creds(require_scope=None):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    if not os.path.exists(TOKEN):
        sys.exit("token.json 없음 — pipeline/setup_auth.py를 먼저 실행하세요")
    creds = Credentials.from_authorized_user_file(TOKEN)
    if require_scope and require_scope not in (creds.scopes or []):
        sys.exit("토큰에 %s 스코프 없음 — pipeline/setup_auth.py로 재인증하라" % require_scope)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        tmp = TOKEN + ".tmp"
        with open(tmp, "w") as f:
            f.write(creds.to_json())
        os.chmod(tmp, 0o600)
        os.replace(tmp, TOKEN)
    return creds
