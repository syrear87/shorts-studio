# YouTube API 감사 회신 초안 (2026-08-05)

받은 요청(7/30): "script / screencast demonstrating how the API services are used to upload videos"
기한: 7영업일 (~8/10). 아래 본문을 해당 메일 스레드에 **답장**으로 붙여넣고, 첨부 2개를 달아 보낼 것.

## 첨부
1. `out/yt_api_screencast.mp4` — 업로드 데모 스크린캐스트 (36초)
2. `pipeline/upload_youtube.py` — 실제 업로드 스크립트 원본

## 메일 본문 (영문)

---

Hello,

Thank you for the review. Please find attached the requested materials:

1. **Screencast (yt_api_screencast.mp4)** — demonstrates our upload flow end-to-end:
   the upload code (videos.insert with resumable upload), a real terminal run uploading
   a test video, and an API verification (videos.list) showing the uploaded video on our
   channel with privacyStatus=private. The demo video is live on our channel as a private
   video: https://youtube.com/shorts/UXyOrvCKvKc

2. **Script (upload_youtube.py)** — the actual Python script used. It reads video metadata
   (title, description, tags, privacy status, madeForKids=False) from a local JSON file and
   calls videos.insert with a resumable MediaFileUpload.

About our API client:

- **Purpose**: a personal, single-user automation tool that uploads short-form educational
  videos (rendered by our own local pipeline) to our own YouTube channel
  "1일 1지식" (@daily1know, channel ID UC5OWO6-bpF8LYPet-rySbjg).
- **Users**: only ourselves (the channel owner). The tool is not distributed and serves
  no third-party users.
- **Data**: we do not access, collect, or store any data belonging to other users or
  channels. The only scopes used are for uploading to and reading our own channel.
- **Volume**: 4–5 uploads per day (well within default quota).

This is the correct contact email (syrear87@gmail.com).

Please let us know if any further information is needed.

Best regards,
Kim Minsoo
1일 1지식 (@daily1know)

---

## 상태
- [ ] 디렉터가 Gmail 스레드에 답장 발송 (첨부 2개 포함)
- 발송 후: DECISIONS.md S-005 갱신, 승인 회신 오면 config upload_mode=api_public 전환
