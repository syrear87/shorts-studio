import subprocess
import sys

video = sys.argv[1]
times = ["00:00:03", "00:00:25", "00:00:42"]

for t in times:
    tag = t.replace(":", "")
    out_name = "out/qa_" + tag + ".jpg"
    subprocess.run([
        "ffmpeg", "-y", "-ss", t, "-i", video,
        "-frames:v", "1", out_name
    ], capture_output=True)
    print("frame at " + t + " saved -> " + out_name)
