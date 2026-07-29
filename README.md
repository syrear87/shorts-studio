# shorts-studio

A personal, non-commercial automation pipeline that produces and uploads
short (30–50s) Korean educational "knowledge" Shorts to the developer's
own YouTube channel — currently 4 videos/day on weekdays and 5/day on
weekends, one per scheduled slot.

## How it works
1. **Script** — a daily studio session drafts a fact-checked 35-second
   script (hook → 3 facts → twist → CTA). Every factual claim requires
   two independent sources before production (see
   `SHORTS_STUDIO_PROTOCOL.md`).
2. **Render** — `pipeline/make_short.py` synthesizes Korean narration
   (edge-tts), fetches licensed background footage (Pexels API, Pexels
   License), and renders 1080×1920 kinetic subtitles synced to the
   narration, mixed with self-generated BGM.
3. **Upload** — `pipeline/upload_youtube.py` uploads each finished video
   to the developer's own channel via the YouTube Data API
   (`videos.insert`), at most 5 videos/day (~8,000 quota units — within
   the default 10,000-unit quota; no quota increase requested).
4. **Analytics** — `pipeline/fetch_analytics.py` reads the developer's
   own channel statistics (YouTube Analytics API) to inform the next
   day's topic selection.

## Scope & privacy
- Single user: the developer. No third-party users, no monetization of
  the tool, no data collection from anyone. See [PRIVACY.md](PRIVACY.md).
- OAuth credentials and tokens are stored locally and are excluded from
  this repository (`.gitignore`).

## Stack
Python 3 · edge-tts · Pillow · numpy · ffmpeg · google-api-python-client
· launchd (daily schedule) · Claude (script drafting & QA)
