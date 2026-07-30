#!/usr/bin/env python3
"""Extract 3 QA frames from a rendered video."""
import subprocess, sys, os

video = sys.argv[1]
out_dir = os.path.join("out", "qa_frames")
os.makedirs(out_dir, exist_ok=True)

for sec in [3, 25, 48]:
    out_path = os.path.join(out_dir, f"frame_{sec}s.png")
    subprocess.run([
        "ffmpeg", "-y", "-ss", str(sec), "-i", video,
        "-frames:v", "1", "-q:v", "2", out_path
    ], capture_output=True)
    print(f"Extracted frame at {sec}s -> {out_path}")
