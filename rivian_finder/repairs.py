"""One-time data repairs that run automatically when the app opens the database.

2026-10-url-fragments: before this fix, listing URLs that differ only in a '#vin=…' fragment (Autolist links that
Auto.dev returns) were treated as the same listing, so many different trucks were folded into one listing and
produced fake price/mileage/seller changes. The repair removes each affected listing (its history is a mix of
several trucks) so the next search recreates every truck correctly. A backup is written first.
"""
from __future__ import annotations

import logging
import sqlite3

log = logging.getLogger(__name__)


def _done(conn, key) -> bool:
    return conn.execute("SELECT 1 FROM preferences WHERE key=?", (f"repair:{key}",)).fetchone() is not None


def _mark(conn, key, detail: str) -> None:
    import json
    with conn:
        conn.execute("INSERT OR REPLACE INTO preferences(key, value) VALUES (?, ?)", (f"repair:{key}", json.dumps(detail)))


def delete_listing(conn: sqlite3.Connection, listing_id: int) -> int | None:
    """Delete a listing with its history; delete its vehicle too if nothing else (listings or user data) remains."""
    row = conn.execute("SELECT vehicle_id FROM listings WHERE id=?", (listing_id,)).fetchone()
    if not row:
        return None
    vid = row[0]
    conn.execute("DELETE FROM vehicle_attributes WHERE listing_id=?", (listing_id,))
    conn.execute("DELETE FROM change_events WHERE listing_id=?", (listing_id,))
    conn.execute("DELETE FROM observations WHERE listing_id=?", (listing_id,))
    conn.execute("DELETE FROM listings WHERE id=?", (listing_id,))
    remaining = conn.execute("SELECT COUNT(*) FROM listings WHERE vehicle_id=?", (vid,)).fetchone()[0]
    user_data = any(conn.execute(q, (vid,)).fetchone()[0] for q in (
        "SELECT COUNT(*) FROM user_overrides WHERE vehicle_id=?", "SELECT COUNT(*) FROM watchlist WHERE vehicle_id=?",
        "SELECT COUNT(*) FROM checklist WHERE vehicle_id=?", "SELECT COUNT(*) FROM contacts WHERE vehicle_id=?",
        "SELECT COUNT(*) FROM vehicles WHERE id=? AND (notes != '' OR hidden_at IS NOT NULL)"))
    if remaining or user_data:
        return None
    for table, col in (("vehicle_attributes", "vehicle_id"), ("change_events", "vehicle_id"),
                       ("match_candidates", "vehicle_id"), ("match_candidates", "candidate_vehicle_id")):
        conn.execute(f"DELETE FROM {table} WHERE {col}=?", (vid,))  # noqa: S608 - fixed names
    conn.execute("UPDATE vehicles SET merged_into_id=NULL WHERE merged_into_id=?", (vid,))
    conn.execute("DELETE FROM vehicles WHERE id=?", (vid,))
    return vid


def repair_url_fragments(conn: sqlite3.Connection) -> dict:
    from .dedup import norm_seller
    key = "2026-10-url-fragments"
    if _done(conn, key):
        return {}
    polluted = [r[0] for r in conn.execute(
        "SELECT DISTINCT listing_id FROM vehicle_attributes WHERE field='vin_conflict' AND listing_id IS NOT NULL")]
    noisy = [r["id"] for r in conn.execute("SELECT id, old_value, new_value FROM change_events WHERE event_type='seller_change'")
             if norm_seller(r["old_value"]) == norm_seller(r["new_value"])]
    if not polluted and not noisy:
        _mark(conn, key, "nothing to repair")
        return {}
    db_file = conn.execute("PRAGMA database_list").fetchone()[2]
    if db_file:  # real file (not :memory:): keep a copy of the pre-repair state
        from . import backup
        from pathlib import Path
        backup.backup_db(conn, Path(db_file).parent / "backups", label="before_repair")
    removed_vehicles = []
    with conn:
        for lid in polluted:
            vid = delete_listing(conn, lid)
            if vid:
                removed_vehicles.append(vid)
        if noisy:
            conn.execute(f"DELETE FROM change_events WHERE id IN ({','.join('?' * len(noisy))})", noisy)  # noqa: S608
        conn.execute("DELETE FROM vehicle_attributes WHERE field='vin_conflict'")
    if removed_vehicles:
        from . import photos
        for vid in removed_vehicles:
            for size in ("t", "m"):
                photos.path_for(vid, size).unlink(missing_ok=True)
    detail = (f"removed {len(polluted)} mixed-up listing(s), {len(removed_vehicles)} vehicle(s), "
              f"{len(noisy)} name-variant seller change(s)")
    log.warning("data repair %s: %s", key, detail)
    _mark(conn, key, detail)
    return {"listings": len(polluted), "vehicles": len(removed_vehicles), "seller_events": len(noisy)}


def reread_trim_names(conn: sqlite3.Connection) -> dict:
    """Older versions didn't recognise names like 'Dual Large' or 'Tri Max'; re-read stored trims (adds claims only)."""
    from .attributes import record_claims
    from .extract import extract_attributes
    key = "2026-10-reread-config-names"
    if _done(conn, key):
        return {}
    added = 0
    rows = conn.execute("SELECT vehicle_id, listing_id, value, source FROM vehicle_attributes WHERE field='trim'").fetchall()
    with conn:
        for r in rows:
            claims = [c for c in extract_attributes(r["value"], "Listing trim name (re-read)", confidence="medium")
                      if c.field in ("battery", "motor")]
            added += record_claims(conn, r["vehicle_id"], claims, listing_id=r["listing_id"], default_source=r["source"])
    _mark(conn, key, f"added {added} claim(s)")
    return {"added": added}


def clear_zero_coords(conn: sqlite3.Connection) -> dict:
    """Auto.dev sends lat/lon 0,0 for some sellers (e.g. Carvana); that read as 7,356 mi away. Use the ZIP instead."""
    key = "2026-10-zero-coords"
    if _done(conn, key):
        return {}
    with conn:
        n = conn.execute("UPDATE listings SET lat=NULL, lon=NULL WHERE ABS(lat) < 0.000001 AND ABS(lon) < 0.000001").rowcount
    _mark(conn, key, f"cleared {n} listing(s)")
    return {"cleared": n}


def run_all(conn: sqlite3.Connection) -> dict:
    return {"url_fragments": repair_url_fragments(conn), "trim_names": reread_trim_names(conn),
            "zero_coords": clear_zero_coords(conn)}
