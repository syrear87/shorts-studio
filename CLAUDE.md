# 1일 1지식 — 숏츠 스튜디오 (Claude Code 운영 가이드)

> 이 저장소는 **매일 영상 6회(07:00/10:20/13:20/15:20/19:00/21:00)·테크 카드 6회(09/10/12/14/16/20시) 지식 콘텐츠를 자동 생산·게시하는 자율 스튜디오**다 (편성 v12.1, 2026-08-24 — 디렉터: "공격적으로 가자" + 카드 9→6 감축, 영상은 공유성 지식 위주).
> 전체 히스토리·사고 이력은 `HANDOVER.md`, 운영 규약은 `SHORTS_STUDIO_PROTOCOL.md`, 매 세션 지침은 `DAILY_PROMPT.md` 참조.
> 디렉터(사용자)는 텔레그램으로 영상을 받아 폰으로 YouTube Shorts/인스타 릴스에 수동 업로드한다(YouTube API 감사 통과 전까지 — 2026-07-29 감사 제출 완료, 심사 대기).

## 시스템 구조
- `DAILY_PROMPT.md` — 데일리 세션의 전체 지침 (트렌드 리서치 → 기획 5렌즈 경쟁(A뉴스/B스포츠·밈/C커뮤니티/D플랫폼/E증시) → 적대 토론 → 중간보고(텔레그램 2건) → 팩트체크(출처 2개, 제목·설명 포함) → 대본(70~90단어) → 배경 시각 선별(pick_bg) → 렌더 → 프레임 QA → 게시 → 리포트·커밋). **이 요약은 참고용 — 절차 정본은 DAILY_PROMPT.md다**
- `pipeline/make_short.py` — 렌더러: **Azure Speech TTS**(SSML·단어 타이밍 동기, 키 없으면 edge-tts 폴백 — 같은 보이스, `narrator: male|female`, 성우별 속도 보정 여+8%/남+18%), 배경은 `bg_id`(pick_bg로 시각 선별) 우선·`bg_query` 검색 폴백, 키네틱 자막, 자체 BGM. **기계 게이트**: 길이 20~55초(50초 초과 시 경고), CTA 자막 2줄, WordBoundary 동기, 메타데이터 차단(-map_metadata -1)
- `pipeline/pick_bg.py` — Pexels 후보 미리보기 저장 → 세션이 Read로 보고 `bg_id` 선택
- `pipeline/upload_youtube.py` — preflight(길이·해상도 기계검증) 후 `config.json`의 `upload_mode`: `phase0_telegram`(현재) / `api_public`(감사 통과 후). `instagram: on`이면 릴스 업로드 체인(`upload_instagram.py`, 토큰은 keys.env)
- `pipeline/threads_stats.py` — 스레드 성과 조회(읽기 전용): 7일 누적 지표·전일 대비 증감·상위 글. **결산 요청 시 반드시 포함**(2026-08-24 디렉터 지시). 스냅샷은 dm 틱이 매일 22시 이후 자동 1회 수집. 스냅샷은 logs/threads_stats.jsonl. ⚠️ 앱 인사이트는 **팔로워 100명까지 전면 잠금**(앱에 '100명이 되면 다시 방문하세요' 표시) — 그때까지 이 스크립트가 유일한 창구다. 조회 출처(추천/프로필/검색)는 100명 해금 후 앱에서 확인.
- `pipeline/analytics.py` — 채널 성과 조회(읽기 전용): eng%·subs/1kE KPI, 훅부검 플래그. 근거 문서는 `content/PERFORMANCE.md`
- `pipeline/retitle.py` — 무긴장 제목 구제(2026-08-02 승인): 게시 3~4h + 조회<300 + 무긴장이면 제목 교체, `content/RETITLES.md` 자동 기록
- `pipeline/affiliate_bot.py` — 제휴 배선(허브 갱신·스토리 스티커 킷·허브 통계). **상주하지 않는다** — 링크 회신과 `허브`/`스티커`/`취소` 명령은 launchd dm 틱(bin/dm_tick.sh)이 10분마다 `--once`로 처리한다(2026-08-21 이관 — 슬롯 세션 폴링을 다시 얹지 마라, 이중 처리된다).
- `pipeline/upload_threads.py` — 스레드 동시 게시(2026-08-16). 인스타 업로드가 만든 **R2 공개 URL을 재사용**하므로 R2 정리 전에 호출된다. 토큰은 `keys.env`의 `THREADS_TOKEN`(60일, 만료 7일 전 자동 갱신 — 시크릿 불필요). **실패해도 릴스 게시엔 영향 없음**(경고만).
- **⛔ 상주 세션 크론은 전면 폐지 (2026-08-25 디렉터: "그냥 그것도 내가 필요할 때 직접 요청하면 안 되나?")**: CronCreate로 사냥·결산 크론을 걸지 마라 — 실행 중 작업이 화면에 상시 표시돼 디렉터에게 부담이었고, REPL이 대화 중이면 발화하지도 않아 신뢰성이 낮았다(8/25 카드 사냥 미발화 실측). 대체 방식:
  - **결산·스레드 전용 글** = 디렉터가 요청할 때 세션이 수행한다("결산" 한 마디). 절차: `threads_stats.py` + `grep $(date +%F) logs/sent.log` + IG/YT 팔로워 → 텔레그램 1건. 스레드 글은 그날 카드 소재를 발견·정보 공유 톤 반말 리스트로 재조립해 `upload_threads.publish_text` — **출처 괄호로 끝낸다**(2026-08-25 디렉터: 2인칭·권유·공유요구·예고 전부 금지. 정본 예시는 CARD_PROMPT의 스레드 본문 항목).
  - **지표 스냅샷** = `bin/dm_tick.sh`가 매일 **22시 이후 첫 틱**에 `threads_stats.py`를 1회 실행해 `logs/threads_stats.jsonl`에 남긴다(가드: `logs/.threads_snap_date`). 이게 끊기면 전일 대비 증감이 죽으므로 자동으로 돌린다.
  - **소재 사냥** = 슬롯 세션이 절차 2단계(트렌드 리서치)에서 스스로 한다. 디렉터가 미리 지정하길 원하면 `content/CALENDAR.md` 당일 지시란에 세션이 기록.
- `archive/` — 폐지된 코드·프롬프트 보관소(삭제 아님). 구 자막 카드 렌더러(현행 테크 카드 make_cards.py는 별개·라이브)·롱폼·PIL 도해·승인 게이트·서치부·트렌드워치·워치독. **되살릴 땐 왜 폐지됐는지 DECISIONS부터 읽어라.**
- `bin/daily_runner.py` — launchd가 슬롯마다 실행. **반드시 로그인 셸(zsh -l) 경유로 claude를 띄운다** (launchd 빈 PATH 사고 이력). 조용한 죽음 경보 + 산출물 실측 대조 내장
- `launchd/` — **3개: daily(영상 07:00/10:20/13:20/15:20/19:00/21:00)·card(카드 09/10/12/14/16/20시)·dm(10분 틱, 편성 v12.1)**. 러너에 카드 일일 쿼터 가드(6장, sent.log 실측) 내장 — 초과 슬롯은 자동 결번. 저장소 사본은 설치본(~/Library/LaunchAgents)과 동기화해 둔다 — 수정 시 복사 후 unload/load. **2026-08-21 이후 상주 프로세스는 없다** — 워치독·트렌드워치·서치부 정리(SD-007/008), 제휴 봇은 pm2 부활 사고 후 SD-015로 최종 폐지. 댓글DM·제휴 링크 폴링은 launchd dm 틱(bin/dm_tick.sh)이 담당한다.
- `content/` — 대본 JSON(형식은 `sample_honey.json`), `BACKLOG.md`(탈락했지만 좋은 소재), `topics_used.md`(**정본은 content/ 쪽** — 루트 동명 파일은 폐지 스텁), `REJECTED.md`(영구금지), `PERFORMANCE.md`(실측 성과)
- `assets/brand/` — 프로필·배너·워터마크 (다크 네이비 #0B1020~#181C36 + 앰버 #FFB627 + 화이트, Noto Sans CJK Black)
- 비밀(커밋 금지, .gitignore 처리됨): `credentials.json`, `token.json`(YouTube OAuth), `telegram.env`(봇 토큰), `keys.env`(PEXELS_API_KEY, AZURE_SPEECH_KEY — aitutor와 공유·교체 시 양쪽 갱신, IG 토큰)

## 철칙 (규약 요약)
0-A. **🚨 한국 고유 소재에 중국·외국 이미지 절대 금지 (2026-08-25 실사고 — 최상위 동급)**: 명절·한복·한옥·한글·국가상징·전통음식·역사 소재의 배경/이미지에 중국·일본풍 요소(홍등·상운 문양·한푸·기모노·한자 간판)가 들어가면 **채널 정체성이 부정당한다 — 정정으로 수습이 안 된다.** 스톡 검색어에 "korean"을 넣어도 중국 이미지가 섞여 오니 **반드시 사진을 직접 보고 판별**하고, 애매하면 버리고 **국적이 드러나지 않는 자연물**(보름달·황금 들녘·추수)로 가라. 단 "중국 김치" 같은 **비판 소재를 다루는 것**은 무관하다 — 금지는 우리 것을 외국 이미지로 그리는 것이다.
0. **중립 원칙 (2026-08-03 디렉터 확정 — 최상위)**: 정당·정치인·진영 언급 금지. 정책은 "당신 고지서" 프레임으로. 단 잘못은 잘못, 잘한 건 잘했다고 사실·숫자로 말한다 — 잣대는 진영 무관 한 개.
1. **소재는 반드시 "오늘" 화제에서 출발** — 언제 올려도 되는 지식 금지. 슬롯별 테마(DAILY_PROMPT 상단), 당일 앞 슬롯과 소재·계열 중복 금지. *단 일상유래 에버그린("매일 직접 겪지만 유래를 모르는 것", 2026-08-02 승인)은 트렌드 출발 의무 면제*
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
