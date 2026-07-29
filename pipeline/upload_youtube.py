#!/usr/bin/env python3
# YouTube 업로더 어댑터. config.json의 upload_mode에 따라 동작.
#  - phase0_telegram: API 업로드 금지(미감사 프로젝트 = private 잠금) → 텔레그램으로 완성본 발송
#  - api_public: 감사 통과 후 videos.insert 공개 게시
# 사용: python3 pipeline/upload_youtube.py out/2026-07-29.mp4 content/2026-07-29.meta.json
import json, os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)

# 디렉터 지정 포맷(2026-07-29): 제목엔 #shorts 금지, 태그는 채널 공통 태그 제외한 소재 태그만
COMMON_TAGS = {"지식", "상식", "1일1지식", "쇼츠"}

def clean_title(meta):
    return meta["title"].replace("#shorts", "").replace("#Shorts", "").strip()

def topic_tags(meta, limit=None):
    tags = [t for t in meta.get("tags", []) if t not in COMMON_TAGS]
    return tags[:limit] if limit else tags

def phase0(video, meta):
    # 1) 영상 파일 자체를 텔레그램으로 발송 (봇 API 한도 50MB)
    size_mb = os.path.getsize(video) / 1e6
    caption = "🎬 오늘의 숏츠 완성 — 이 영상을 저장해서 YouTube 앱 → + → Shorts로 올려주세요\n\n제목: %s" % meta["title"]
    if size_mb < 49:
        subprocess.run(["bash", os.path.join(ROOT, "bin", "tg-send-video.sh"), video, caption], check=True)
    else:
        subprocess.run(["bash", os.path.join(ROOT, "bin", "tg-send.sh"),
                        "⚠️ 영상이 %dMB로 텔레그램 한도 초과 — 파일: %s" % (size_mb, os.path.abspath(video))], check=True)
    # 2) 제목·설명·태그는 복사하기 좋게 별도 메시지로 (헤더 없음)
    msg = "%s\n\n%s\n\n태그: %s" % (clean_title(meta), meta["description"], ", ".join(topic_tags(meta)))
    subprocess.run(["bash", os.path.join(ROOT, "bin", "tg-send.sh"), msg], check=True)
    print("phase0: 텔레그램으로 영상+메타데이터 발송 완료 (API 업로드 안 함)")

def api_public(video, meta):
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    token = os.path.join(ROOT, "token.json")
    if not os.path.exists(token):
        sys.exit("token.json 없음 — setup_auth.py를 먼저 실행하세요")
    creds = Credentials.from_authorized_user_file(token)
    if creds.expired and creds.refresh_token:
        from google.auth.transport.requests import Request
        creds.refresh(Request())
        with open(token, "w") as f:
            f.write(creds.to_json())
    yt = build("youtube", "v3", credentials=creds)
    # 디렉터 지정 매핑(2026-07-29): 제목=#shorts 없는 제목 / 설명=제목+본문 / 태그=소재 태그 5개
    #                             / 아동용 아님 / 공개
    title = clean_title(meta)
    body = {
        "snippet": {
            "title": title[:100],
            "description": ("%s\n\n%s" % (title, meta["description"]))[:4900],
            "tags": topic_tags(meta, 5),
            "categoryId": "27",  # 교육
            "defaultLanguage": "ko",
        },
        "status": {
            "privacyStatus": meta.get("privacy", "public"),   # 기본 "공개"
            "selfDeclaredMadeForKids": False,                 # "아니요, 아동용이 아닙니다"
        },
    }
    media = MediaFileUpload(video, chunksize=8 * 1024 * 1024, resumable=True, mimetype="video/mp4")
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    resp = None
    while resp is None:
        status, resp = req.next_chunk()
        if status:
            print("업로드 %d%%" % int(status.progress() * 100), flush=True)
    vid = resp["id"]
    url = "https://youtube.com/shorts/" + vid
    print("업로드 완료:", url)
    subprocess.run(["bash", os.path.join(ROOT, "bin", "tg-send.sh"),
                    "✅ 오늘의 숏츠 게시 완료\n%s\n%s" % (title, url)], check=False)
    return vid

def main():
    if len(sys.argv) < 3:
        sys.exit("사용: upload_youtube.py <video.mp4> <meta.json>")
    video, meta_p = sys.argv[1], sys.argv[2]
    meta = load(meta_p)
    cfg = load(os.path.join(ROOT, "config.json"))
    mode = cfg.get("upload_mode", "phase0_telegram")
    if mode == "api_public":
        api_public(video, meta)
    else:
        phase0(video, meta)
    # 인스타 릴스는 감사 관문이 없어 config만 켜면 즉시 완전 자동 (실패해도 유튜브 게시는 유지)
    if cfg.get("instagram") == "on":
        try:
            import upload_instagram
            upload_instagram.upload(video, meta)
        except Exception as e:
            print("릴스 업로드 실패: %s" % e)
            subprocess.run(["bash", os.path.join(ROOT, "bin", "tg-send.sh"),
                            "⚠️ 인스타 릴스 자동 업로드 실패 — 수동 업로드 필요\n%s" % str(e)[:300]], check=False)

if __name__ == "__main__":
    main()
