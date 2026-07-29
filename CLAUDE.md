# 1일 1지식 — 숏츠 스튜디오 (Claude Code 운영 가이드)

> 이 저장소는 **하루 3회(07:30/11:00/18:00) 지식 숏폼을 자동 생산해 텔레그램으로 발송하는 자율 스튜디오**다.
> 전체 히스토리·사고 이력·미해결 과제는 `HANDOVER.md`, 운영 규약은 `SHORTS_STUDIO_PROTOCOL.md`, 매 세션 지침은 `DAILY_PROMPT.md` 참조.
> 디렉터(사용자)는 아침·점심·저녁 텔레그램으로 영상을 받아 폰으로 YouTube Shorts/인스타 릴스에 수동 업로드한다(API 감사 통과 전까지).

## 시스템 구조
- `DAILY_PROMPT.md` — 데일리 세션의 전체 지침 (트렌드 리서치 → 기획자 A/B 경쟁 제안 → 적대 토론 → 팩트체크(출처 2개) → 대본(90~110단어) → 렌더 → 프레임 QA → 게시 → 리포트·커밋)
- `pipeline/make_short.py` — 렌더러: edge-tts(단어 타이밍 동기, `narrator: male|female`), Pexels 배경영상(`bg_query` 배열, 세로 우선·가로 폴백), 키네틱 자막(긴 줄 자동 축소), 프리렌더 배너, 자체 BGM. 실행: `.venv/bin/python3 pipeline/make_short.py content/파일.json`
- `pipeline/upload_youtube.py` — `config.json`의 `upload_mode`: `phase0_telegram`(현재: 영상+메타를 텔레그램 발송) / `api_public`(감사 통과 후 완전 자동 게시)
- `pipeline/fetch_analytics.py` — 채널 성과 수집(계정 연동 후)
- `bin/daily_runner.py` — launchd가 하루 3회 실행. **반드시 로그인 셸(zsh -l) 경유로 claude를 띄운다** (launchd 빈 PATH에서 node를 못 찾는 사고 이력)
- `bin/ondemand_runner.py` — 1분마다 `logs/.run_request` 폴링, 화이트리스트 작업 실행 (원격 세션용 채널이었음 — 로컬에서는 그냥 직접 실행하면 됨)
- `launchd/` — `com.shorts-studio.daily`(3회 스케줄), `com.shorts-studio.ondemand`(폴링). 수정 시 `~/Library/LaunchAgents`에 복사 후 unload/load
- `content/` — 대본 JSON(형식은 `sample_honey.json`), `BACKLOG.md`(탈락했지만 좋은 소재), `topics_used.md` 중복 방지
- `assets/brand/` — 프로필·배너·워터마크 (다크 네이비 #0B1020~#181C36 + 앰버 #FFB627 + 화이트, Noto Sans CJK Black)
- 비밀(커밋 금지, .gitignore 처리됨): `credentials.json`, `token.json`(YouTube OAuth), `telegram.env`(봇 토큰), `keys.env`(PEXELS_API_KEY)

## 철칙 (규약 요약)
1. **소재는 반드시 "오늘" 화제에서 출발** — 언제 올려도 되는 지식 금지. 슬롯별 각도(아침=밤사이/점심=오전 이슈/저녁=하루 정리), 당일 앞 슬롯과 소재·계열 중복 금지
2. **QA 하드게이트**: 사실 주장마다 독립 출처 2개 실측, 렌더 후 프레임 3장 직접 보기(자막·배너·배경 적합성), 길이 20~50초, 위반 시 게시 중단
3. 민감한 날(폭락·재난) 밈 톤 금지, **투자·의료 조언 문장 금지**, 결론은 훅 회수(수미상관) 또는 다음 화 예고 — 밋밋한 마무리 금지
4. 저작권: 자체 생성물 + Pexels/Pixabay 라이선스만. git push는 사용자 승인 필요(원격: github.com/syrear87/shorts-studio)
5. 성우: 시사·역사·차분 = male(InJoon), 생활·심리·밝음 = female(SunHi)

## 자주 하는 일
- 지금 슬롯 수동 실행: `/usr/bin/python3 bin/daily_runner.py`
- 특정 대본만 재렌더: `.venv/bin/python3 pipeline/make_short.py content/파일.json` → `.venv/bin/python3 pipeline/upload_youtube.py out/파일.mp4 content/파일.meta.json`
- 스케줄 변경: `launchd/com.shorts-studio.daily.plist` 수정 → cp → `launchctl unload/load`
