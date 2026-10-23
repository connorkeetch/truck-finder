"""Desktop notifications without extra dependencies (Windows toast via PowerShell, macOS osascript, Linux notify-send)."""
from __future__ import annotations

import base64
import html
import platform
import shutil
import subprocess

# Windows only shows toasts for registered app IDs; Windows PowerShell's is always registered.
WIN_APP_ID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"


def windows_script(title: str, body: str, url: str | None = None) -> str:
    launch = f' activationType="protocol" launch="{html.escape(url, quote=True)}"' if url else ""
    lines = "".join(f"<text>{html.escape(t)}</text>" for t in [title, *body.splitlines()[:3]] if t)
    xml = f'<toast{launch}><visual><binding template="ToastGeneric">{lines}</binding></visual></toast>'
    return (
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null;"
        "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null;"
        "$x = New-Object Windows.Data.Xml.Dom.XmlDocument;"
        f"$x.LoadXml('{xml.replace(chr(39), chr(39) * 2)}');"
        "$t = New-Object Windows.UI.Notifications.ToastNotification $x;"
        f"[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{WIN_APP_ID}').Show($t)"
    )


def command(title: str, body: str, url: str | None = None, system: str | None = None) -> list[str] | None:
    system = system or platform.system()
    if system == "Windows":
        encoded = base64.b64encode(windows_script(title, body, url).encode("utf-16-le")).decode()
        return ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                "-EncodedCommand", encoded]
    if system == "Darwin":
        esc = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')  # noqa: E731
        return ["osascript", "-e", f'display notification "{esc(body)}" with title "{esc(title)}"']
    if shutil.which("notify-send"):
        return ["notify-send", title, body]
    return None


def notify(title: str, body: str, url: str | None = None) -> tuple[bool, str]:
    cmd = command(title, body, url)
    if not cmd:
        return False, "No notification method available on this system."
    kwargs = {"capture_output": True, "text": True, "timeout": 30}
    if platform.system() == "Windows":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    try:
        r = subprocess.run(cmd, **kwargs)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, f"{type(e).__name__}: {e}"
    return r.returncode == 0, (r.stderr or r.stdout or "").strip()[:300]
