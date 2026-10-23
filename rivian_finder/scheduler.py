"""Optional scheduled search via Windows Task Scheduler (per-user tasks; runs only while you're logged in)."""
from __future__ import annotations

import csv
import io
import platform
import re
import subprocess
import sys
from pathlib import Path

from . import config

FOLDER = "RivianFinder"


def runner() -> tuple[Path, Path]:
    """(pythonw, script) used by the scheduled task. pythonw runs without a console window."""
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    return (pyw if pyw.exists() else exe), config.PROJECT_ROOT / "run_alerts.pyw"


def task_name(hhmm: str) -> str:
    return f"{FOLDER}\\Search {hhmm.replace(':', '')}"


def create_commands(times: list[str]) -> list[list[str]]:
    pyw, script = runner()
    cmds = []
    for t in times:
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", t):
            raise ValueError(f"time must be HH:MM (got {t!r})")
        cmds.append(["schtasks", "/Create", "/F", "/SC", "DAILY", "/ST", t, "/TN", task_name(t),
                     "/TR", f'"{pyw}" "{script}"'])
    return cmds


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30,
                          creationflags=0x08000000 if platform.system() == "Windows" else 0)


def supported() -> bool:
    return platform.system() == "Windows"


def installed(run=_run) -> list[dict]:
    """Rivian Finder tasks with their next run time."""
    if not supported():
        return []
    r = run(["schtasks", "/Query", "/FO", "CSV", "/NH"])
    out = []
    for row in csv.reader(io.StringIO(r.stdout or "")):
        if len(row) >= 3 and row[0].startswith(f"\\{FOLDER}\\"):
            out.append({"name": row[0].strip("\\"), "next_run": row[1], "status": row[2]})
    return out


def install(times: list[str], run=_run) -> tuple[bool, str]:
    if not supported():
        return False, "Automatic scheduling is Windows-only here. On macOS/Linux add a cron entry for run_alerts.pyw."
    remove(run)
    for cmd in create_commands(times):
        r = run(cmd)
        if r.returncode != 0:
            return False, (r.stderr or r.stdout).strip()
    return True, f"Scheduled daily at {', '.join(times)}."


def remove(run=_run) -> tuple[bool, str]:
    if not supported():
        return True, ""
    names = [t["name"] for t in installed(run)]
    for name in names:
        run(["schtasks", "/Delete", "/F", "/TN", name])
    return True, f"Removed {len(names)} scheduled search(es)."
