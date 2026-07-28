#!/bin/bash
# 숏츠 스튜디오 1회 셋업 — 터미널에서: cd ~/Dev/shorts-studio && bash setup.sh
set -e
cd "$(dirname "$0")"
mkdir -p logs
exec > >(tee logs/setup.log) 2>&1
trap 'echo "[실패] line $LINENO: $BASH_COMMAND"' ERR
echo "== setup.sh 시작: $(date) =="
echo "== 1/5 파이썬 가상환경(.venv) + 패키지 설치 =="
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
.venv/bin/python3 -m pip install -q --upgrade pip
.venv/bin/python3 -m pip install -q edge-tts pillow numpy google-api-python-client google-auth-oauthlib requests

echo "== 2/5 ffmpeg 확인 =="
if ! command -v ffmpeg >/dev/null; then
  if command -v brew >/dev/null; then
    echo "ffmpeg 없음 → brew로 설치합니다"
    brew install ffmpeg
  elif [ -x /opt/homebrew/bin/brew ]; then
    /opt/homebrew/bin/brew install ffmpeg
  else
    echo "[실패] ffmpeg도 Homebrew도 없습니다. 먼저: /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\" 후 다시 실행"
    exit 1
  fi
fi
export PATH="/opt/homebrew/bin:$PATH"

echo "== 3/5 한글 폰트 다운로드 =="
mkdir -p assets/fonts out reports logs analytics content
if [ ! -f assets/fonts/NotoSansCJKkr-Black.otf ]; then
  curl -sL -o assets/fonts/NotoSansCJKkr-Black.otf \
    "https://github.com/notofonts/noto-cjk/raw/main/Sans/OTF/Korean/NotoSansCJKkr-Black.otf" || true
  # 다운로드 실패 시 make_short.py가 AppleSDGothicNeo로 폴백
  if [ -f assets/fonts/NotoSansCJKkr-Black.otf ] && ! file assets/fonts/NotoSansCJKkr-Black.otf | grep -qi font; then
    rm -f assets/fonts/NotoSansCJKkr-Black.otf
  fi
fi

echo "== 4/5 유튜브 OAuth 인증 (브라우저 창이 뜹니다) =="
.venv/bin/python3 setup_auth.py

echo "== 5/5 데모 렌더 (TTS 포함 전체 파이프라인 검증) =="
.venv/bin/python3 pipeline/make_short.py content/sample_honey.json --out out/demo_honey.mp4
if [ -f bin/tg-send.sh ] && [ -f telegram.env ]; then
  bash bin/tg-send.sh "🎬 숏츠 스튜디오 셋업 완료 — 데모 렌더 성공 (out/demo_honey.mp4)"
fi

echo ""
echo "✅ 셋업 완료. 데일리 자동 실행 등록은:"
echo "   cp launchd/com.shorts-studio.daily.plist ~/Library/LaunchAgents/"
echo "   launchctl load ~/Library/LaunchAgents/com.shorts-studio.daily.plist"
