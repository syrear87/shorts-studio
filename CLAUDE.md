# 1일 1지식 — 숏츠 스튜디오 (Claude Code 운영 가이드)

> 이 저장소는 **평일 4회(08/11/17/20시)·주말 5회(09/12/15/18/21시) 지식 숏폼을 자동 생산해 텔레그램으로 발송하는 자율 스튜디오**다.
> 전체 히스토리·사고 이력은 `HANDOVER.md`, 운영 규약은 `SHORTS_STUDIO_PROTOCOL.md`, 매 세션 지침은 `DAILY_PROMPT.md` 참조.
> 디렉터(사용자)는 텔레그램으로 영상을 받아 폰으로 YouTube Shorts/인스타 릴스에 수동 업로드한다(YouTube API 감사 통과 전까지 — 2026-07-29 감사 제출 완료, 심사 대기).

## 시스템 구조
- `DAILY_PROMPT.md` — 데일리 세션의 전체 지침 (트렌드 리서치 → 기획자 A/B 경쟁 → 적대 토론 → 중간보고(텔레그램 2건) → 팩트체크(출처 2개, 제목·설명 포함) → 대본(70~90단어) → 배경 시각 선별(pick_bg) → 렌더 → 프레임 QA → 게시 → 리포트·커밋)
- `pipeline/make_short.py` — 렌더러: edge-tts(단어 타이밍 동기, `narrator: male|female`, 성우별 속도 보정 여+8%/남+18%), 배경은 `bg_id`(pick_bg로 시각 선별) 우선·`bg_query` 검색 폴백, 키네틱 자막, 자체 BGM. **기계 게이트**: 길이 15~55초, CTA 자막 2줄, WordBoundary 동기, 메타데이터 차단(-map_metadata -1)
- `pipeline/pick_bg.py` — Pexels 후보 미리보기 저장 → 세션이 Read로 보고 `bg_id` 선택
- `pipeline/upload_youtube.py` — preflight(길이·해상도 기계검증) 후 `config.json`의 `upload_mode`: `phase0_telegram`(현재) / `api_public`(감사 통과 후). `instagram: on`이면 릴스 업로드 체인(`upload_instagram.py`, 토큰은 keys.env)
- `pipeline/fetch_analytics.py` — 채널 성과 수집 (아직 자동 배선 없음 — 수동 실행)
- `bin/daily_runner.py` — launchd가 슬롯마다 실행. **반드시 로그인 셸(zsh -l) 경유로 claude를 띄운다** (launchd 빈 PATH 사고 이력). 조용한 죽음 경보 + 산출물 실측 대조 내장
- `bin/watchdog.py` — 매일 22:30 슬롯 누락 대조 + 텔레그램 하트비트 (메시지 부재 = 장애 신호)
- `bin/ondemand_runner.py` — 1분마다 `logs/.run_request` 폴링, 화이트리스트 작업 실행 (로컬에서는 그냥 직접 실행하면 됨)
- `launchd/` — daily(요일분기 스케줄)·ondemand·watchdog. 수정 시 `~/Library/LaunchAgents`에 복사 후 unload/load
- `content/` — 대본 JSON(형식은 `sample_honey.json`), `BACKLOG.md`(탈락했지만 좋은 소재), `topics_used.md` 중복 방지
- `assets/brand/` — 프로필·배너·워터마크 (다크 네이비 #0B1020~#181C36 + 앰버 #FFB627 + 화이트, Noto Sans CJK Black)
- 비밀(커밋 금지, .gitignore 처리됨): `credentials.json`, `token.json`(YouTube OAuth), `telegram.env`(봇 토큰), `keys.env`(PEXELS_API_KEY, IG 토큰)

## 철칙 (규약 요약)
1. **소재는 반드시 "오늘" 화제에서 출발** — 언제 올려도 되는 지식 금지. 슬롯별 테마(DAILY_PROMPT 상단), 당일 앞 슬롯과 소재·계열 중복 금지
2. **실용팁·생활정보형 소재 원칙 배제** (디렉터 취향) — '몰랐던 사실의 반전'이 중심일 때만. 스몰토크 테스트("남에게 말하고 싶은가") 필수
3. **QA 하드게이트**: 사실 주장(제목·설명 포함)마다 독립 출처 2개 실측, 렌더 후 프레임 3장 직접 보기(자막·배너·배경에 소재의 시각적 대표물), 길이 20~50초 목표(55 초과는 렌더러가 기각)
4. 상시: 의료는 "연구가 있다" 선까지·금융 인접은 면책 1줄 의무. 민감한 날(폭락·재난) 밈 톤 금지, 결론은 훅 회수(수미상관) 또는 다음 화 예고
5. 저작권: 자체 생성물 + Pexels 스톡만(업로더가 설명에 Pexels 크레딧 자동 첨부). git push는 사용자 승인 필요(공개 저장소 github.com/syrear87/shorts-studio — 시크릿 절대 금지)
6. 성우: 시사·역사·차분 = male(InJoon), 생활·심리·밝음 = female(SunHi). 해시태그는 소재 태그 5개만, 제목에 #shorts 금지

## 자주 하는 일
- 지금 슬롯 수동 실행: `/usr/bin/python3 bin/daily_runner.py`
- 특정 대본만 재렌더: `.venv/bin/python3 pipeline/make_short.py content/파일.json` → `.venv/bin/python3 pipeline/upload_youtube.py out/파일.mp4 content/파일.meta.json`
- 배경 후보 보기: `.venv/bin/python3 pipeline/pick_bg.py content/파일.json` → `out/bg_candidates/` 확인 → json에 `"bg_id"` 기록
- 스케줄 변경: `launchd/com.shorts-studio.daily.plist` 수정 → cp → `launchctl unload/load`
