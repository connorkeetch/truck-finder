#!/usr/bin/env python3
"""MotorSift launcher (Windows, macOS, Linux).

First run: creates .venv and installs requirements. Later runs: reinstalls only when requirements.txt changes.
Then starts the app on 127.0.0.1 and opens your browser. If it is already running, just opens the browser.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import socket
import subprocess
import sys
import time
import urllib.request
import venv
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
REQS = ROOT / "requirements.txt"
PORT = int(os.environ.get("RIVIAN_FINDER_PORT", "8501"))
URL = f"http://127.0.0.1:{PORT}"
OPEN_BROWSER = os.environ.get("RIVIAN_FINDER_NO_BROWSER", "") != "1"


def data_dir() -> Path:
    """Same rule as the app: RIVIAN_FINDER_DATA_DIR (env or .env), else ./data."""
    value = os.environ.get("RIVIAN_FINDER_DATA_DIR", "")
    env_file = ROOT / ".env"
    if not value and env_file.exists():
        for line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.strip().startswith("RIVIAN_FINDER_DATA_DIR="):
                value = line.split("=", 1)[1].strip().strip('"')
    return Path(value) if value else ROOT / "data"


def lan_enabled() -> bool:
    try:
        return bool(json.loads((data_dir() / "app_access.json").read_text(encoding="utf-8")).get("lan"))
    except (OSError, ValueError):
        return False


def lan_ip() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return None


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if platform.system() == "Windows" else "bin/python")


def say(msg: str) -> None:
    print(f"[MotorSift] {msg}", flush=True)


def ensure_env() -> None:
    if sys.version_info < (3, 10):
        sys.exit("Python 3.10 or newer is required. Install it from https://www.python.org/downloads/")
    if not venv_python().exists():
        say(f"Creating virtual environment for {platform.system()} ...")
        venv.create(VENV, with_pip=True)
    stamp = VENV / ".requirements.sha1"
    digest = hashlib.sha1(REQS.read_bytes()).hexdigest()
    if not stamp.exists() or stamp.read_text().strip() != digest:
        say("Installing dependencies (first run takes a minute or two) ...")
        subprocess.check_call([str(venv_python()), "-m", "pip", "install", "--disable-pip-version-check", "-q",
                               "--upgrade", "pip"])
        subprocess.check_call([str(venv_python()), "-m", "pip", "install", "--disable-pip-version-check", "-q",
                               "-r", str(REQS)])
        stamp.write_text(digest)


def running() -> bool:
    try:
        with urllib.request.urlopen(f"{URL}/_stcore/health", timeout=1) as r:
            return r.status == 200
    except OSError:
        return False


def port_in_use() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", PORT)) == 0


def main() -> int:
    os.chdir(ROOT)
    if running():
        say(f"Already running — opening {URL}")
        if OPEN_BROWSER:
            webbrowser.open(URL)
        return 0
    if port_in_use():
        sys.exit(f"Port {PORT} is used by another program. Set RIVIAN_FINDER_PORT to a free port and try again.")
    ensure_env()
    address = "0.0.0.0" if lan_enabled() else "127.0.0.1"
    say(f"Starting on {URL} (close this window or press Ctrl+C to stop) ...")
    if address == "0.0.0.0":
        say(f"Phone access is ON: on your home Wi-Fi open http://{lan_ip() or '<this-PC-IP>'}:{PORT} (PIN required)")
    proc = subprocess.Popen([str(venv_python()), "-m", "streamlit", "run", str(ROOT / "app.py"),
                             "--server.address", address, "--server.port", str(PORT),
                             "--server.headless", "true", "--browser.gatherUsageStats", "false"])
    for _ in range(60):
        if running():
            if OPEN_BROWSER:
                webbrowser.open(URL)
            break
        if proc.poll() is not None:
            say("The app exited during startup. See the messages above; docs/TROUBLESHOOTING.md has fixes.")
            return proc.returncode or 1
        time.sleep(0.5)
    try:
        return proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        return 0


if __name__ == "__main__":
    sys.exit(main())
