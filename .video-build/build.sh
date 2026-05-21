#!/usr/bin/env bash
# Build the gemini-elastic-agent hackathon demo video end-to-end.
# Produces .video-build/demo.mp4 (~2:40, 1920x1080, H.264, no audio).
#
# Re-run idempotently. Requires: ffmpeg, python3 with Pillow + playwright.
# Run from repo root:  bash .video-build/build.sh

set -euo pipefail

cd "$(dirname "$0")/.."
REPO_ROOT="$(pwd)"
OUT="$REPO_ROOT/.video-build"
PY="$REPO_ROOT/.venv/bin/python"

if [ ! -x "$PY" ]; then
    PY="$(command -v python3)"
fi

mkdir -p "$OUT"

echo "[1/4] rendering title card..."
"$PY" "$OUT/render_title.py"

echo "[2/4] rendering terminal scene..."
"$PY" "$OUT/render_terminal.py"

echo "[3/4] rendering browser scene..."
"$PY" "$OUT/render_browser.py"

echo "[4/4] concatenating scenes into demo.mp4..."
cat > "$OUT/scenes.txt" <<EOF
file 'scene1_title.mp4'
file 'scene2_terminal.mp4'
file 'scene3_browser.mp4'
EOF

ffmpeg -y -loglevel error \
    -f concat -safe 0 -i "$OUT/scenes.txt" \
    -c copy "$OUT/demo.mp4"

DUR="$(ffprobe -v error -show_entries format=duration \
    -of default=noprint_wrappers=1:nokey=1 "$OUT/demo.mp4")"
SZ="$(du -h "$OUT/demo.mp4" | cut -f1)"
echo "DONE: $OUT/demo.mp4 ($SZ, ${DUR}s)"
