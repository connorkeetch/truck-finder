"""Single-process Streamlit runtime and opt-in scheduling behind the private cloud proxy."""
from __future__ import annotations

import logging
import os
import re
import sys
import threading
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import cli, config, db, services
from .credentials import RedactingFilter

log = logging.getLogger(__name__)
POLL_SECONDS = 15


def is_cloud() -> bool:
    return os.environ.get("RIVIAN_FINDER_CLOUD") == "1"


def schedule_timezone() -> ZoneInfo:
    name = os.environ.get("TZ", "America/Denver")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError(f"Unknown scheduling timezone {name!r}; install timezone data and set TZ.") from None


def _times(values) -> tuple[str, ...]:
    if not isinstance(values, list) or not values or any(
            not isinstance(value, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value)
            for value in values):
        raise ValueError("Scheduled search times must be a nonempty list of HH:MM values.")
    return tuple(sorted(set(values)))


def next_run(now: datetime, times: list[str] | tuple[str, ...], tz: ZoneInfo) -> datetime:
    """Next strictly future time in UTC; skip nonexistent DST times and repeated local hours."""
    times = _times(list(times))
    now = now.astimezone(timezone.utc)
    today = now.astimezone(tz).date()
    for offset in range(3):
        day = today + timedelta(days=offset)
        for value in times:
            hour, minute = map(int, value.split(":"))
            local = datetime.combine(day, time(hour, minute), tzinfo=tz)
            candidate = local.astimezone(timezone.utc)
            if candidate.astimezone(tz).replace(tzinfo=None) != local.replace(tzinfo=None):
                continue
            if candidate > now:
                return candidate
    raise ValueError("No future scheduled time found.")


def _scheduled_search(conn) -> None:
    with services.SEARCH_LOCK:
        settings = db.load_settings(conn)
        if not settings.get("alerts", {}).get("enabled"):
            return
        if services.mailbox_enabled(settings):       # alert emails cost no listing API calls
            mail = services.check_mailbox(conn, settings)
            log.info("Scheduled mailbox check %s: %s", mail["status"], mail["text"])
        keys, skipped = cli.budget_ok_sources(conn, settings)
        if skipped:
            log.info("Scheduled search skipped connectors: %s", "; ".join(skipped))
        if not keys:
            log.info("Scheduled search: no connectors ready within the API budget.")
            return
        summary = services.run_sources(conn, keys, settings)
        log.info("Scheduled search %s: %s", summary.get("status"), summary.get("text", ""))


class Scheduler:
    """A polling schedule whose first action is always to choose a future due time."""

    def __init__(self, conn, *, clock=None, run_search=None, tz=None):
        self.conn = conn
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.run_search = run_search or _scheduled_search
        self.tz = tz or schedule_timezone()
        self.next_due = None
        self._schedule = None

    def tick(self) -> None:
        now = self.clock().astimezone(timezone.utc)
        alerts = db.load_settings(self.conn).get("alerts") or {}
        enabled = bool(alerts.get("enabled"))
        try:
            times = _times(alerts.get("times")) if enabled else ()
        except ValueError as error:
            log.warning("Scheduling disabled: %s", error)
            times = ()
        schedule = (enabled, times)
        if schedule != self._schedule:
            self._schedule = schedule
            self.next_due = next_run(now, times, self.tz) if times else None
            return
        if self.next_due is None or now < self.next_due:
            return
        try:
            # A stopped or suspended server never catches up on missed search minutes.
            if now < self.next_due + timedelta(minutes=1):
                self.run_search(self.conn)
            else:
                log.info("Skipped a missed scheduled search; waiting for the next future time.")
        finally:
            self.next_due = next_run(self.clock(), times, self.tz)


def start_scheduler(stop_event: threading.Event | None = None) -> threading.Thread | None:
    """Start once from the cloud entry point, independently of browser connections."""
    if not is_cloud():
        return None
    stop_event = stop_event or threading.Event()
    tz = schedule_timezone()

    def work():
        conn = db.connect()
        try:
            scheduler = Scheduler(conn, tz=tz)
            while not stop_event.is_set():
                try:
                    scheduler.tick()
                except Exception:
                    log.exception("Scheduled search failed; the server will continue.")
                stop_event.wait(POLL_SECONDS)
        finally:
            conn.close()

    thread = threading.Thread(target=work, name="cloud-scheduler", daemon=True)
    thread.start()
    return thread


def _run_streamlit() -> None:
    from streamlit.web import cli as streamlit_cli

    previous = sys.argv
    sys.argv = ["streamlit", "run", str(config.PROJECT_ROOT / "app.py"),
                "--server.address=127.0.0.1", "--server.port=8501", "--server.headless=true",
                "--browser.gatherUsageStats=false"]
    try:
        streamlit_cli.main()
    finally:
        sys.argv = previous


def main() -> None:
    if not is_cloud():
        raise SystemExit("Set RIVIAN_FINDER_CLOUD=1 to use the private cloud runtime.")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for handler in logging.getLogger().handlers:
        handler.addFilter(RedactingFilter())
    config.ensure_dirs()
    # Finish migrations before browser sessions and the scheduler open their own connections.
    db.connect().close()
    stop = threading.Event()
    thread = start_scheduler(stop)
    try:
        _run_streamlit()
    finally:
        stop.set()
        if thread:
            thread.join(timeout=1)


if __name__ == "__main__":
    main()
