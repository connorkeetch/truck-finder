"""Automatic alert-email import: read saved-search alerts (KSL, RivianForums, AutoTrader…) from one mailbox folder.

The sites email you; this reads those emails over IMAP, so their listings arrive without the app visiting any site.
The folder is opened read-only and messages are fetched with BODY.PEEK, so nothing is marked read, moved or deleted.
Each email is imported once (by Message-ID). Only listings that match your saved make/model searches are saved;
wanted-to-buy posts and sold forum threads are skipped. Like every import, it never marks trucks missing.
"""
from __future__ import annotations

import email.utils
import imaplib
import re
import sqlite3
from datetime import datetime, timedelta, timezone

from .. import credentials, pipeline
from ..db import utcnow
from ..models import NormalizedListing
from ..sources.base import matches_target, search_targets
from . import email_alerts, forum_listing

TRIGGER = "email_auto"
TIMEOUT = 30
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_UID_RE = re.compile(rb"\bUID (\d+)")
_MESSAGE_ID_RE = re.compile(rb"^Message-ID:\s*(\S+)", re.I | re.M)


class MailboxError(Exception):
    """The mailbox couldn't be read. The message is safe to show: it never contains the password."""


def _connect(host: str, port: int) -> imaplib.IMAP4:
    return imaplib.IMAP4_SSL(host, port, timeout=TIMEOUT)


def _quote(mailbox: str) -> str:
    """IMAP folder names with spaces ("Truck alerts") must be quoted."""
    return '"' + mailbox.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _imap_date(day: datetime) -> str:
    return f"{day.day:02d}-{_MONTHS[day.month - 1]}-{day.year}"   # strftime('%b') would follow the OS locale


def _iso(date_header: str) -> str | None:
    try:
        return email.utils.parsedate_to_datetime(date_header).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError, IndexError):
        return None


def matching_search(nl: NormalizedListing, targets: list[dict]) -> dict | None:
    """The saved search this listing belongs to. Alert emails often name the vehicle only in their text, so a
    "Toyota Tacoma" in the title or description fills in the make and model when the parser couldn't."""
    for target in targets:
        if matches_target(nl.make, nl.model, target):
            return target
    text = f"{nl.title or ''} {nl.description or ''}"
    for target in targets:
        if re.search(rf"\b{re.escape(target['make'])}\s+{re.escape(target['model'])}\b", text, re.I):
            nl.make, nl.model = target["make"], target["model"]
            return target
    return None


def wanted(nl: NormalizedListing, targets: list[dict]) -> bool:
    if nl.source_key == forum_listing.SITE and forum_listing.parse_title(nl.title)["status"] in ("wanted", "sold"):
        return False
    return matching_search(nl, targets) is not None


def _fetch(imap: imaplib.IMAP4, uids: list[bytes], part: str) -> dict[bytes, bytes]:
    """{uid: bytes} for a FETCH of one message part, without changing the messages' read state."""
    typ, data = imap.uid("FETCH", b",".join(uids).decode(), f"(UID BODY.PEEK[{part}])")
    if typ != "OK":
        raise MailboxError("The mail server refused to send the messages.")
    out = {}
    for item in data or []:
        if isinstance(item, tuple) and len(item) == 2:
            m = _UID_RE.search(item[0])
            if m:
                out[m.group(1)] = item[1]
    return out


def check(conn: sqlite3.Connection, settings: dict, password: str | None = None, connect=None,
          now: datetime | None = None) -> dict:
    """Import new alert emails from the configured folder. Returns a summary with a one-line 'text'."""
    cfg = settings.get("email_import") or {}
    username, folder = (cfg.get("username") or "").strip(), (cfg.get("mailbox") or "INBOX").strip()
    password = password or credentials.get_api_key("imap")[0]
    if not username or not password:
        return {"status": "skipped", "emails": 0, "saved": 0,
                "text": "Mailbox import isn't set up: add your email address and app password in Sources → Email alerts."}
    try:
        targets = search_targets(settings["collection"])
    except ValueError as e:
        return {"status": "failed", "emails": 0, "saved": 0, "text": f"Mailbox import: {e}"}
    now = now or datetime.now(timezone.utc)
    since = _imap_date(now - timedelta(days=int(cfg.get("lookback_days") or 14)))
    host, port = cfg.get("host") or "imap.gmail.com", int(cfg.get("port") or 993)
    try:
        imap = (connect or _connect)(host, port)
    except OSError as e:
        return {"status": "failed", "emails": 0, "saved": 0, "text": f"Couldn't reach {host}: {type(e).__name__}."}
    try:
        try:
            imap.login(username, password)
        except imaplib.IMAP4.error:
            raise MailboxError(f"{host} rejected the sign-in for {username}. For Gmail, use an app password "
                               "(myaccount.google.com/apppasswords), not your normal password.") from None
        if imap.select(_quote(folder), readonly=True)[0] != "OK":
            raise MailboxError(f"There's no folder or label named “{folder}” in {username}.")
        typ, data = imap.uid("SEARCH", None, "SINCE", since)
        if typ != "OK":
            raise MailboxError("The mail server refused the search.")
        uids = (data[0] or b"").split() if data else []
        ids = {}                                     # uid -> Message-ID, the key that makes each email import once
        for uid, head in (_fetch(imap, uids, "HEADER.FIELDS (MESSAGE-ID)") if uids else {}).items():
            m = _MESSAGE_ID_RE.search(head)
            ids[uid] = m.group(1).decode(errors="replace") if m else f"{folder}:{uid.decode()}"
        known = {r[0] for r in conn.execute(
            f"SELECT message_id FROM email_inbox WHERE message_id IN ({','.join('?' * len(ids))})",  # noqa: S608
            list(ids.values()))} if ids else set()
        pending = [uid for uid in uids if uid in ids and ids[uid] not in known]     # oldest first
        new = pending[:int(cfg.get("max_per_run") or 50)]
        bodies = _fetch(imap, new, "") if new else {}
    except (MailboxError, imaplib.IMAP4.error, OSError) as e:
        text = str(e) if isinstance(e, MailboxError) else f"Mailbox error: {credentials.redact(str(e))[:200]}"
        return {"status": "failed", "emails": 0, "saved": 0, "text": text}
    finally:
        try:
            imap.logout()
        except (imaplib.IMAP4.error, OSError):
            pass

    rows, keep, found_total = [], [], 0
    for uid in new:
        raw = bodies.get(uid)
        if raw is None:
            continue
        meta, found = email_alerts.parse_eml_bytes(raw)
        chosen = [nl for nl in found if wanted(nl, targets)]
        found_total += len(found)
        keep += chosen
        rows.append([ids[uid], folder, _iso(meta["date"]), meta["from"][:200], meta["subject"][:300], len(found),
                     len(chosen)])
    run_id = pipeline.import_listings(conn, keep, TRIGGER)["run_id"] if keep else None
    with conn:
        conn.executemany("INSERT OR IGNORE INTO email_inbox(message_id, mailbox, received_at, sender, subject,"
                         " listings, saved, run_id, imported_at) VALUES (?,?,?,?,?,?,?,?,?)",
                         [(*r, run_id, utcnow()) for r in rows])
    skipped = found_total - len(keep)
    text = (f"Mailbox: {len(rows)} new alert email{'s' if len(rows) != 1 else ''}, {len(keep)} listing"
            f"{'s' if len(keep) != 1 else ''} saved" + (f", {skipped} skipped (not in your searches, wanted or sold)"
                                                         if skipped else "") + ".")
    if len(new) < len(pending):
        text += f" {len(pending) - len(new)} more will be read on the next check."
    return {"status": "success", "emails": len(rows), "listings": found_total, "saved": len(keep),
            "skipped": skipped, "run_id": run_id, "text": text}
