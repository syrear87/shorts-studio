#!/usr/bin/env python3
"""keys.env 재작성 직렬화 — 토큰 갱신 경쟁(lost update) 방지. (2026-08-25 감사로 신설)

왜 있는가:
  upload_threads._save_token()과 upload_instagram.refresh_token_if_due()가 각각
  **파일 전체를 읽어 한 줄만 바꿔 os.replace** 한다. 개별 교체는 원자적이지만
  read-modify-write라 동시에 실행되면 나중에 쓴 쪽이 상대의 갱신을 덮어쓴다.

  겹치는 창이 상시적이다: 21:00 영상 슬롯은 타임아웃 75분이라 22:15까지 살 수 있고
  그 세션이 IG·스레드 토큰을 갱신한다. 같은 시각 dm_tick의 22시 스냅샷이
  threads_stats → upload_threads.token()을 호출해 역시 keys.env를 재작성한다.

  IG 쪽이 더 나쁘다 — 갱신을 잃은 쪽도 logs/.ig_token_refreshed를 갱신해버려
  REFRESH_AFTER(7일) 게이트가 닫히고, 버려진 갱신을 일주일간 재시도하지 않는다.
  60일 만료가 다가와서야 드러난다.

사용:
    from keyfile import locked
    with locked():
        ... keys.env 읽기 → 수정 → os.replace ...

읽기 전용 경로는 감쌀 필요 없다 — os.replace 덕에 항상 온전한 파일을 본다.
"""
import contextlib
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCK_PATH = os.path.join(ROOT, "logs", "keys.env.lock")


@contextlib.contextmanager
def locked(timeout=30):
    """keys.env 재작성 구간을 프로세스 간 직렬화한다.
    락 획득 실패(플랫폼 미지원 등)는 통과시킨다 — 잠금 실패가 토큰 갱신 자체를
    막으면 만료로 전 채널이 죽는다. 경쟁은 드물고 만료는 확실하다."""
    f = None
    try:
        os.makedirs(os.path.dirname(LOCK_PATH), exist_ok=True)
        f = open(LOCK_PATH, "w")
        try:
            # 논블로킹 + 재시도 — signal.alarm은 메인 스레드에서만 동작해 취약하다
            # (2026-08-25 자체 검증에서 스레드 경합이 직렬화되지 않는 것을 확인해 교체)
            import fcntl
            import time as _t
            _deadline = _t.time() + timeout
            while True:
                try:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if _t.time() >= _deadline:
                        print("[keyfile] 락 대기 %d초 초과 — 잠금 없이 진행" % timeout, flush=True)
                        break
                    _t.sleep(0.05)
        except Exception as e:
            print("[keyfile] 락 획득 실패(계속 진행): %s" % str(e)[:100], flush=True)
        yield
    finally:
        if f is not None:
            try:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
            f.close()
