#!/usr/bin/env sh
# Creates "MotorSift.command" on the macOS Desktop (double-click to start the app).
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$HOME/Desktop/MotorSift.command"
printf '#!/bin/sh\ncd "%s" && ./run.sh\n' "$ROOT" > "$OUT"
chmod +x "$OUT" "$ROOT/run.sh"
echo "Created $OUT"
