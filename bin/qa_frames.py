import subprocess, os, sys

video = sys.argv[1] if len(sys.argv) > 1 else "out/2026-08-02-noon.mp4"
times = ["00:00:03", "00:00:25", "00:00:48"]
for i, t in enumerate(times):
    out = f"out/qa_frame_{i}.png"
    subprocess.run(
        ["ffmpeg", "-y", "-ss", t, "-i", video, "-frames:v", "1", out],
        capture_output=True,
    )
    sz = os.path.getsize(out) if os.path.exists(out) else 0
    print(f"frame {i}: {out} ({sz} bytes)")
