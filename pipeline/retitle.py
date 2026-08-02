#!/usr/bin/env python3
"""무긴장 제목 구제 — 게시된 영상의 제목 교체 (2026-08-02 디렉터 승인 프로토콜).

사용: .venv/bin/python3 pipeline/retitle.py <video_id> "새 제목"

프로토콜 (DAILY_PROMPT '무긴장 제목 구제' 항목 참조):
- 대상: 게시 3~4시간 경과 + 실시간 조회 300 미만 + 제목에 긴장(모순·반전·통념뒤집기) 없음
- 새 제목은 제목 규칙 ①~④를 전부 통과해야 한다
- 교체 내역은 content/RETITLES.md에 자동 기록된다 (전후 조회 비교 = 제목 인과의 준실험 표본)
- 필요 스코프: youtube.force-ssl (없으면 setup_auth.py로 재인증)
"""
import datetime, os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(ROOT, "content", "RETITLES.md")


def main():
    if len(sys.argv) < 3:
        sys.exit('사용: retitle.py <video_id> "새 제목"')
    vid, new_title = sys.argv[1], sys.argv[2].strip()
    if not (5 <= len(new_title) <= 100):
        sys.exit("제목 길이 이상: %d자" % len(new_title))
    if "#shorts" in new_title.lower():
        sys.exit("제목에 #shorts 금지 (채널 규약)")

    from googleapiclient.discovery import build
    from google_creds import load_creds

    # 2026-08-02 리뷰 [A13]: 토큰 로드+스코프 검사+refresh 원자 저장 — 공용 헬퍼로 통일
    creds = load_creds(require_scope="https://www.googleapis.com/auth/youtube.force-ssl")
    yt = build("youtube", "v3", credentials=creds)

    r = yt.videos().list(part="snippet,statistics", id=vid).execute()
    if not r.get("items"):
        sys.exit("영상 없음: " + vid)
    v = r["items"][0]
    old_title = v["snippet"]["title"]
    views = v["statistics"].get("viewCount", "?")
    if old_title == new_title:
        sys.exit("제목이 이미 동일함")

    snip = v["snippet"]
    snip["title"] = new_title
    yt.videos().update(part="snippet", body={"id": vid, "snippet": snip}).execute()

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    if not os.path.exists(LOG):
        with open(LOG, "w", encoding="utf-8") as f:
            f.write("# 제목 교체 기록 — 전후 조회 비교로 제목 인과 검증 (준실험 표본)\n\n"
                    "| 교체 시각 | video_id | 교체시점 조회 | 구제목 | 신제목 | 교체 +48h 조회(추후 기입) |\n"
                    "|---|---|---|---|---|---|\n")
    with open(LOG, "a", encoding="utf-8") as f:
        # 2026-08-02 리뷰 [A17]: 제목 속 '|'가 마크다운 표 열을 깨는 것 방지
        f.write("| %s | %s | %s | %s | %s |  |\n" % (
            now, vid, views, old_title.replace("|", "\\|"), new_title.replace("|", "\\|")))

    print("교체 완료: %s\n  구: %s\n  신: %s (교체시점 조회 %s)" % (vid, old_title, new_title, views))
    subprocess.run(["bash", os.path.join(ROOT, "bin", "tg-send.sh"),
                    "✏️ 제목 교체(구제 프로토콜)\n구: %s\n신: %s\n교체시점 조회: %s" % (old_title, new_title, views)],
                   check=False)


if __name__ == "__main__":
    main()
