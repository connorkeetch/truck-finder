#!/usr/bin/env sh
# MotorSift launcher for macOS / Linux.  chmod +x run.sh && ./run.sh
cd "$(dirname "$0")" || exit 1
if command -v python3 >/dev/null 2>&1; then
  exec python3 launcher.py "$@"
else
  exec python launcher.py "$@"
fi
