"""Optional phone access on your home network, protected by a PIN.

The setting lives in data/app_access.json because the launcher reads it before the app starts (to choose between
listening on 127.0.0.1 only, or on the local network). Connections from this computer never need the PIN.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import socket

from . import config

ITERATIONS = 200_000


def path():
    return config.DATA_DIR / "app_access.json"


def load() -> dict:
    try:
        return {"lan": False, "pin_hash": None, "salt": None, **json.loads(path().read_text(encoding="utf-8"))}
    except (OSError, ValueError):
        return {"lan": False, "pin_hash": None, "salt": None}


def _hash(pin: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt), ITERATIONS).hex()


def save(lan: bool, pin: str | None = None) -> None:
    data = load()
    if pin is not None:
        if not (pin.isdigit() and 4 <= len(pin) <= 12):
            raise ValueError("PIN must be 4–12 digits")
        data["salt"] = secrets.token_hex(16)
        data["pin_hash"] = _hash(pin, data["salt"])
    if lan and not data.get("pin_hash"):
        raise ValueError("Set a PIN before turning on phone access")
    data["lan"] = bool(lan)
    config.ensure_dirs()
    path().write_text(json.dumps(data), encoding="utf-8")


def check_pin(pin: str) -> bool:
    data = load()
    if not data.get("pin_hash") or not data.get("salt") or not pin:
        return False
    return hmac.compare_digest(_hash(pin, data["salt"]), data["pin_hash"])


def lan_ips() -> list[str]:
    """This computer's private IPv4 addresses (what your phone types in)."""
    ips = set()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))     # no packet is sent; picks the outbound interface
            ips.add(s.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    private = [ip for ip in ips if ip.startswith(("192.168.", "10.")) or
               (ip.startswith("172.") and 16 <= int(ip.split(".")[1]) <= 31)]
    return sorted(private, key=lambda ip: (not ip.startswith("192.168."), ip))


def port() -> int:
    return int(os.environ.get("RIVIAN_FINDER_PORT", "8501"))
