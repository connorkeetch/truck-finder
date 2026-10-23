"""'Not interested': hide a truck (by vehicle, so it stays hidden on every site) and record why."""
from __future__ import annotations

import sqlite3

from . import attributes, pipeline
from .db import utcnow

# key -> (label, override to record as a verified fact, or None)
HIDE_REASONS: dict[str, tuple[str, tuple[str, str] | None]] = {
    "title_issues": ("Title issues", ("title_status", "branded")),
    "too_far": ("Too far", None),
    "sold": ("Sold / dead link", None),
    "other": ("Other", None),
}


def hide_vehicle(conn: sqlite3.Connection, vehicle_id: int, reason: str, note: str = "") -> None:
    """Hide a truck. 'Title issues' also records the title as branded; 'Sold / dead link' marks its listings
    removed."""
    if reason not in HIDE_REASONS:
        raise ValueError(f"unknown reason {reason}")
    label, override = HIDE_REASONS[reason]
    if override:
        attributes.set_override(conn, vehicle_id, override[0], override[1],
                                f"Recorded when marked not interested{': ' + note if note else ''}")
    if reason == "sold":
        for (lid,) in conn.execute("SELECT id FROM listings WHERE vehicle_id=? AND status != 'removed'",
                                   (vehicle_id,)).fetchall():
            pipeline.mark_removed(conn, lid, "Marked sold by user")
    with conn:
        conn.execute("UPDATE vehicles SET hidden_at=?, hidden_reason=?, hidden_note=? WHERE id=?",
                     (utcnow(), reason, note or None, vehicle_id))


def restore_vehicle(conn: sqlite3.Connection, vehicle_id: int) -> None:
    """Show a hidden truck again. Facts recorded when hiding (e.g. branded title) are kept."""
    with conn:
        conn.execute("UPDATE vehicles SET hidden_at=NULL, hidden_reason=NULL, hidden_note=NULL WHERE id=?",
                     (vehicle_id,))


def reason_label(key: str | None) -> str:
    return HIDE_REASONS.get(key or "", (key or "", None))[0]
