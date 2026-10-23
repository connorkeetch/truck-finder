"""API key lookup: environment variables first, then the OS credential store (keyring). Never the database."""
from __future__ import annotations

import logging
import os
import re

log = logging.getLogger(__name__)
SERVICE = "rivian-finder"
KEYS = {"autodev": "AUTODEV_API_KEY", "marketcheck": "MARKETCHECK_API_KEY"}


def _keyring():
    try:
        import keyring  # noqa: PLC0415
        return keyring
    except Exception:  # pragma: no cover - keyring backend missing
        return None


def get_api_key(source: str) -> tuple[str | None, str]:
    """Return (key, where) where 'where' is 'env', 'keyring', or 'missing'."""
    env_name = KEYS[source]
    val = os.environ.get(env_name, "").strip()
    if val:
        return val, "env"
    kr = _keyring()
    if kr:
        try:
            val = kr.get_password(SERVICE, env_name)
        except Exception as e:  # pragma: no cover
            log.warning("keyring unavailable: %s", type(e).__name__)
            val = None
        if val:
            return val, "keyring"
    return None, "missing"


def save_api_key(source: str, value: str) -> None:
    kr = _keyring()
    if not kr:
        raise RuntimeError("No OS credential store available; set the environment variable in .env instead.")
    kr.set_password(SERVICE, KEYS[source], value.strip())


def delete_api_key(source: str) -> None:
    kr = _keyring()
    if kr:
        try:
            kr.delete_password(SERVICE, KEYS[source])
        except Exception:
            pass


def mask(value: str | None) -> str:
    if not value:
        return ""
    return value[:4] + "…" + value[-2:] if len(value) > 8 else "••••"


_REDACT_RE = re.compile(r"((?:api_key|apikey|token|key|access_token)=)[^&\s]+", re.I)
_BEARER_RE = re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]+", re.I)


def redact(text: str | None) -> str:
    """Strip credentials from URLs and messages before they are logged or shown."""
    if not text:
        return ""
    return _BEARER_RE.sub(r"\1***", _REDACT_RE.sub(r"\1***", str(text)))


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(str(record.msg))
        if record.args:
            record.args = tuple(redact(str(a)) for a in record.args) if isinstance(record.args, tuple) else record.args
        return True
