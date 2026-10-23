"""Command line: run a search without the UI (used by the optional scheduled task) and send a notification.

    python -m rivian_finder.cli run [--notify]
    python -m rivian_finder.cli notify-test
"""
from __future__ import annotations

import argparse
import logging
import logging.handlers
import sys

from . import alerts, config, db, notifier, queries, services
from .credentials import RedactingFilter

APP_URL = "http://127.0.0.1:8501"


def _logger() -> logging.Logger:
    config.ensure_dirs()
    log = logging.getLogger("rivian_finder.cli")
    if not log.handlers:
        h = logging.handlers.RotatingFileHandler(config.LOG_DIR / "scheduled.log", maxBytes=500_000, backupCount=2,
                                                 encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        h.addFilter(RedactingFilter())
        log.addHandler(h)
        log.setLevel(logging.INFO)
    return log


def budget_ok_sources(conn, settings) -> tuple[list[str], list[str]]:
    """Ready connectors whose free-plan budget still covers a full run (20% headroom)."""
    keep, skipped = [], []
    for s in services.available_sources(conn):
        if not (s["enabled"] and s["configured"]):
            continue
        cap = services.API_CAPS.get(s["key"])
        if cap:
            b = queries.api_budget(conn, s["key"], cap)
            if b["per_run"] and b["left"] < b["per_run"] * 1.2:
                skipped.append(f"{s['name']} (only {b['left']} calls left this month)")
                continue
        keep.append(s["key"])
    return keep, skipped


def cmd_run(notify: bool) -> int:
    log = _logger()
    conn = db.connect()
    settings = db.load_settings(conn)
    keys, skipped = budget_ok_sources(conn, settings)
    if not keys:
        msg = "No connectors ready" + (f"; skipped for budget: {', '.join(skipped)}" if skipped else "")
        log.warning(msg)
        print(msg)
        return 1
    summary = services.run_sources(conn, keys, settings)
    text = summary.get("text", "")
    if skipped:
        text += f" Skipped to protect your API budget: {', '.join(skipped)}."
    log.info("run %s: %s", summary.get("run_id"), text)
    print(text)
    if notify and summary.get("run_id"):
        a = alerts.collect(conn, summary["run_id"], settings)
        want = a["count"] or (settings.get("alerts") or {}).get("notify_when_nothing")
        if want:
            ok, detail = notifier.notify(a["title"], "\n".join(a["lines"]) or text[:200], APP_URL)
            log.info("notification %s: %s %s", "sent" if ok else "failed", a["title"], detail)
    return 0 if summary.get("status") in ("success", "partial") else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="rivian_finder")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run a search now")
    r.add_argument("--notify", action="store_true", help="send a desktop notification for new trucks / price drops")
    r.add_argument("--scheduled", action="store_true", help=argparse.SUPPRESS)
    sub.add_parser("notify-test", help="send a test notification")
    sub.add_parser("check-links", help="check that listing links still lead to the truck's page")
    args = p.parse_args(argv)
    if args.cmd == "run":
        return cmd_run(args.notify)
    if args.cmd == "check-links":
        from . import linkcheck
        print("Checking listing links (sites that block automated checks are skipped, not worked around)...")
        summary = linkcheck.check_all(db.connect(config.DB_PATH))
        print(linkcheck.summary_text(summary))
        for url in summary["problems"]:
            print("  dead/moved:", url)
        return 0
    ok, detail = notifier.notify("Truck Finder", "Test notification — alerts are working.", APP_URL)
    print("sent" if ok else f"failed: {detail}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
