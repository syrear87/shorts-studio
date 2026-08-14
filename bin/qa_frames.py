#!/usr/bin/env python3
# QA 프레임 추출 — 게시 전 육안 검사용.
# 2026-08-14 감사: 고정 시각(3/25/48s)은 48초 미만 영상에서 마지막 프레임이 조용히 실패하고
# CTA 자막 겹침 검사에 필요한 마지막 씬이 보장되지 않았다 → 길이 기준 상대 시각으로 교체.
import os
import subprocess
import sys

video = sys.argv[1] if len(sys.argv) > 1 else "out/2026-08-02-noon.mp4"
probe = subprocess.run(["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                        "-of", "csv=p=0", video], capture_output=True, text=True)
try:
    dur = float(probe.stdout.strip())
except ValueError:
    sys.exit("길이 판독 불가: %s" % video)
# 훅(5%) / 본문 1/3 / 본문 2/3 / CTA(끝 1.2초 전 — 구독 표시·자막 겹침 검사)
times = [max(0.5, dur * 0.05), dur / 3, dur * 2 / 3, max(0.5, dur - 1.2)]
for i, t in enumerate(times):
    out = f"out/qa_frame_{i}.png"
    subprocess.run(["ffmpeg", "-y", "-ss", "%.2f" % t, "-i", video, "-frames:v", "1", out],
                   capture_output=True)
    sz = os.path.getsize(out) if os.path.exists(out) else 0
    status = "" if sz > 0 else "  ⚠️ 추출 실패"
    print(f"frame {i} ({t:.1f}s): {out} ({sz} bytes){status}")
