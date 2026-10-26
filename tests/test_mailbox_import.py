"""Automatic alert-email import over IMAP, against a fake mail server (no network, no real mailbox)."""
import imaplib
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from rivian_finder import cli, db, services
from rivian_finder.importers import mailbox

FIXTURES = Path(__file__).parent / "fixtures"
PASSWORD = "abcd efgh ijkl mnop"
NOW = datetime(2026, 10, 26, 12, tzinfo=timezone.utc)


def _email(name: str, message_id: str) -> bytes:
    return f"Message-ID: <{message_id}@example.com>\r\n".encode() + (FIXTURES / name).read_bytes()


KSL_TACOMA = (b"Message-ID: <ksl-1@example.com>\r\nFrom: KSL Cars <alerts@ksl.com>\r\nSubject: New listings\r\n"
              b"Date: Sun, 25 Oct 2026 07:00:00 -0600\r\nContent-Type: text/plain\r\n\r\n"
              b"SYNTHETIC. 2021 Toyota Tacoma TRD Off-Road\r\n$33,900 | 52,000 miles | Reno, NV\r\nFor Sale By Owner\r\n"
              b"https://cars.ksl.com/listing/9900123\r\n")
FORUM_WTB = (b"Message-ID: <wtb-1@example.com>\r\nFrom: Rivian Forum <noreply@rivianforums.com>\r\n"
             b"Subject: New thread in watched forum: Washington - WTB 2023 Large pack R1T around $52k\r\n"
             b"Content-Type: text/html\r\n\r\n<div><p>buyer9 started a new thread.</p>"
             b'<a href="https://www.rivianforums.com/forum/threads/wtb.70001/">'
             b"Washington - WTB 2023 Large pack R1T around $52k</a></div>")


class FakeIMAP:
    """Just enough of imaplib.IMAP4 for the importer. Fails the test if a message would be marked read."""

    def __init__(self, messages: dict[int, bytes], folders=("Truck alerts",)):
        self.messages, self.folders, self.calls = messages, folders, []

    def login(self, user, password):
        self.calls.append(("login", user))
        if password != PASSWORD:
            raise imaplib.IMAP4.error(b"[AUTHENTICATIONFAILED] Invalid credentials (Failure)")
        return "OK", [b"logged in"]

    def select(self, folder, readonly=False):
        assert readonly, "the mailbox must be opened read-only"
        self.calls.append(("select", folder))
        return ("OK", [str(len(self.messages)).encode()]) if folder.strip('"') in self.folders else ("NO", [b"no"])

    def uid(self, command, *args):
        self.calls.append(("uid", command, *args))
        if command == "SEARCH":
            return "OK", [b" ".join(str(u).encode() for u in sorted(self.messages))]
        uids, part = args
        assert "BODY.PEEK[" in part, "fetches must not mark messages read"
        out = []
        for n, uid in enumerate(uids.split(","), 1):
            raw = self.messages[int(uid)]
            if "HEADER.FIELDS" in part:
                m = re.search(rb"^Message-ID:[^\r\n]*\r?\n", raw, re.M)
                raw = (m.group(0) if m else b"") + b"\r\n"
            out += [(f"{n} (UID {uid} BODY[] {{{len(raw)}}}".encode(), raw), b")"]
        return "OK", out

    def logout(self):
        self.calls.append(("logout",))
        return "BYE", [b""]


@pytest.fixture
def setup(conn):
    s = db.load_settings(conn)          # fresh defaults: one saved search, Rivian R1T
    s["email_import"].update(enabled=True, username="shopper@example.com", mailbox="Truck alerts")
    return conn, s


def _check(conn, s, server, password=PASSWORD):
    return mailbox.check(conn, s, password=password, connect=lambda host, port: server, now=NOW)


def test_new_alert_emails_import_once(setup):
    conn, s = setup
    server = FakeIMAP({11: _email("synthetic_autotrader_alert.eml", "at-1"),
                       12: _email("synthetic_rivianforums_alert.eml", "rf-1")})
    first = _check(conn, s, server)
    assert first["status"] == "success" and first["emails"] == 2
    assert first["saved"] == 3 and first["skipped"] == 1           # 2 AutoTrader R1Ts + 1 forum R1T; not the Lightning
    assert conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0] == 3
    forum = conn.execute("SELECT seller_type, current_price FROM listings WHERE source_key='rivianforums'").fetchone()
    assert tuple(forum) == ("private", 52500)
    assert ("select", '"Truck alerts"') in server.calls and server.calls[-1] == ("logout",)

    again = _check(conn, s, server)
    assert (again["emails"], again["saved"]) == (0, 0)
    fetched_bodies = [c for c in server.calls if c[:2] == ("uid", "FETCH") and c[3] == "(UID BODY.PEEK[])"]
    assert len(fetched_bodies) == 1                                   # the second check fetched headers only
    rows = conn.execute("SELECT message_id, listings, saved FROM email_inbox ORDER BY message_id").fetchall()
    assert [tuple(r) for r in rows] == [("<at-1@example.com>", 3, 2), ("<rf-1@example.com>", 1, 1)]


def test_wanted_posts_are_skipped_and_other_makes_found_in_text(setup):
    conn, s = setup
    s["collection"]["searches"] = [{"make": "Rivian", "model": "R1T"}, {"make": "Toyota", "model": "Tacoma"}]
    result = _check(conn, s, FakeIMAP({1: FORUM_WTB, 2: KSL_TACOMA}))
    assert (result["emails"], result["saved"], result["skipped"]) == (2, 1, 1)
    row = conn.execute("SELECT v.make, v.model, l.source_key, l.seller_type, l.current_price FROM listings l"
                       " JOIN vehicles v ON v.id = l.vehicle_id").fetchone()
    assert tuple(row) == ("Toyota", "Tacoma", "ksl", "private", 33900)


def test_per_check_limit_leaves_the_rest_for_next_time(setup):
    conn, s = setup
    s["email_import"]["max_per_run"] = 1
    server = FakeIMAP({1: _email("synthetic_autotrader_alert.eml", "a"), 2: _email("synthetic_cars_com_alert.eml", "b")})
    first = _check(conn, s, server)
    assert first["emails"] == 1 and "1 more will be read" in first["text"]
    assert _check(conn, s, server)["emails"] == 1
    assert _check(conn, s, server)["emails"] == 0


def test_wrong_password_explains_app_passwords_without_echoing_it(setup):
    conn, s = setup
    result = _check(conn, s, FakeIMAP({}), password="my-real-password")
    assert result["status"] == "failed" and "app password" in result["text"]
    assert "my-real-password" not in result["text"]


def test_missing_folder_is_named(setup):
    conn, s = setup
    s["email_import"]["mailbox"] = "Car alerts"
    result = _check(conn, s, FakeIMAP({}))
    assert result["status"] == "failed" and "Car alerts" in result["text"]


def test_unreachable_server(setup):
    conn, s = setup

    def refuse(host, port):
        raise ConnectionRefusedError("refused")

    result = mailbox.check(conn, s, password=PASSWORD, connect=refuse, now=NOW)
    assert result["status"] == "failed" and "imap.gmail.com" in result["text"]


def test_not_set_up_is_skipped(conn):
    s = db.load_settings(conn)
    assert s["email_import"]["enabled"] is False            # off until you turn it on
    assert mailbox.check(conn, s, password=PASSWORD, connect=lambda h, p: FakeIMAP({}))["status"] == "skipped"


def test_search_uses_an_english_imap_date(setup):
    conn, s = setup
    server = FakeIMAP({})
    _check(conn, s, server)
    assert ("uid", "SEARCH", None, "SINCE", "12-Oct-2026") in server.calls


def test_scheduled_run_imports_email_even_without_connectors(setup, monkeypatch, capsys):
    conn, s = setup
    file_conn = db.connect()                    # the CLI opens the (isolated) data folder's database
    db.save_settings(file_conn, s)
    with file_conn:
        file_conn.execute("UPDATE sources SET enabled=0")
    monkeypatch.setenv("TRUCK_FINDER_IMAP_PASSWORD", PASSWORD)
    server = FakeIMAP({1: _email("synthetic_rivianforums_alert.eml", "rf-1")})
    monkeypatch.setattr(mailbox, "_connect", lambda host, port: server)
    assert cli.cmd_run(notify=False) == 0
    out = capsys.readouterr().out
    assert "1 listing saved" in out and "No connectors ready" in out
    assert services.mailbox_enabled(db.load_settings(file_conn))
    assert db.get_pref(file_conn, "email_import_last")["saved"] == 1
