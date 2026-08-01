import subprocess, sys
video = "out/2026-08-01-day.mp4"
times = ["00:00:03", "00:00:25", "00:00:46"]
for i, t in enumerate(times):
    out = f"out/qa_frame_{i}.jpg"
    subprocess.run(["ffmpeg", "-y", "-ss", t, "-i", video, "-frames:v", "1", "-q:v", "2", out],
                   capture_output=True)
    print(f"Frame {i} at {t} → {out}")

# ffprobe duration
r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                     "-of", "default=noprint_wrappers=1:nokey=1", video],
                    capture_output=True, text=True)
print(f"Duration: {float(r.stdout.strip()):.2f}s")
