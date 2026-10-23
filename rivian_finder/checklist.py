"""Pre-purchase checklist and seller contact log. Some answers feed the truck's verified values."""
from __future__ import annotations

import sqlite3
from datetime import date

from . import attributes
from .db import utcnow

STATUSES = {"todo": "Not checked", "ok": "OK", "problem": "Problem", "na": "N/A"}
CHANNELS = ["call", "text", "email", "visit", "other"]

# key, label, hint
ITEMS: list[tuple[str, str, str]] = [
    ("tonneau", "Powered tonneau opens and closes fully", "Watch it run both ways; listen for grinding."),
    ("title", "Title is clean (seen on Carfax/AutoCheck or the title)", "Problem = branded, salvage, rebuilt, flood."),
    ("accidents", "No accidents or structural damage reported", "Carfax/AutoCheck; ask about paintwork."),
    ("in_service", "Warranty in-service date confirmed", "Carfax 'first sold' date or Rivian; enter it under Verify equipment."),
    ("config", "Battery pack and motor match the listing", "Rivian app/window sticker. OK copies them into verified values."),
    ("warranty", "Remaining warranty confirmed with Rivian", "Ask Rivian service with the VIN."),
    ("recalls", "Recalls and service campaigns done", "NHTSA VIN lookup or Rivian service history."),
    ("account", "Previous owner removed from the truck/app; keys and cards handed over", "Truck must transfer to your Rivian account."),
    ("charging", "Charges on DC fast and Level 2; charge port door works", ""),
    ("software", "Software current; no warning lights", ""),
    ("suspension", "Air suspension raises/lowers in every mode", ""),
    ("gear", "Gear tunnel, frunk and Gear Guard cable work", ""),
    ("tires", "Tire tread and brand acceptable", "R1T tires are expensive; note tread depth."),
    ("glass_body", "Windshield/glass and paint OK; no underbody or off-road damage", ""),
    ("price_quote", "Out-the-door price in writing (doc fee, add-ons, tax)", ""),
    ("delivery", "Shipping / delivery arranged and quoted", ""),
    ("financing", "Financing approved at the APR you planned", ""),
]
ITEM_LABELS = {k: label for k, label, _ in ITEMS}


def get(conn: sqlite3.Connection, vehicle_id: int) -> dict[str, dict]:
    rows = {r["item"]: dict(r) for r in conn.execute("SELECT * FROM checklist WHERE vehicle_id=?", (vehicle_id,))}
    return {k: rows.get(k, {"item": k, "status": "todo", "note": "", "updated_at": None}) for k, _, _ in ITEMS}


def save(conn: sqlite3.Connection, vehicle_id: int, answers: dict[str, tuple[str, str]]) -> list[str]:
    """answers: item -> (status, note). Returns the verified values that were set from the answers."""
    now = utcnow()
    current = get(conn, vehicle_id)
    changed = {k: v for k, v in answers.items() if (current[k]["status"], current[k]["note"]) != v}
    with conn:
        for item, (status, note) in changed.items():
            conn.execute(
                "INSERT INTO checklist(vehicle_id, item, status, note, updated_at) VALUES (?,?,?,?,?)"
                " ON CONFLICT(vehicle_id, item) DO UPDATE SET status=excluded.status, note=excluded.note,"
                " updated_at=excluded.updated_at", (vehicle_id, item, status, note, now))
    return _feed(conn, vehicle_id, {k: v[0] for k, v in changed.items()})


def _feed(conn: sqlite3.Connection, vehicle_id: int, statuses: dict[str, str]) -> list[str]:
    """Turn checklist answers into verified values (only for items that changed)."""
    fed = []
    note = "From pre-purchase checklist"
    rules = {
        ("tonneau", "ok"): ("tonneau", "yes"),
        ("title", "ok"): ("title_status", "clean"),
        ("title", "problem"): ("title_status", "branded"),
        ("accidents", "ok"): ("accident_history", "none_reported"),
        ("accidents", "problem"): ("accident_history", "reported"),
    }
    for item, status in statuses.items():
        target = rules.get((item, status))
        if target:
            attributes.set_override(conn, vehicle_id, target[0], target[1], note)
            fed.append(f"{target[0]} = {target[1]}")
    if statuses.get("config") == "ok":
        resolved = attributes.resolve(conn, vehicle_id)
        for f in ("battery", "motor"):
            r = resolved.get(f)
            if r and r.value not in (None, "Unknown") and r.confidence != "verified":
                attributes.set_override(conn, vehicle_id, f, r.value, note)
                fed.append(f"{f} = {r.value}")
    return fed


def progress(conn: sqlite3.Connection) -> dict[int, dict]:
    """vehicle_id -> {'done': n, 'total': N, 'problems': p, 'text': '7/17 · 1 problem'}."""
    total = len(ITEMS)
    out: dict[int, dict] = {}
    for r in conn.execute("SELECT vehicle_id, SUM(status != 'todo') AS done, SUM(status = 'problem') AS problems"
                          " FROM checklist GROUP BY vehicle_id"):
        done, problems = int(r["done"] or 0), int(r["problems"] or 0)
        text = f"{done}/{total}" + (f" · {problems} problem{'s' if problems != 1 else ''}" if problems else "")
        out[r["vehicle_id"]] = {"done": done, "total": total, "problems": problems, "text": text}
    return out


def add_contact(conn: sqlite3.Connection, vehicle_id: int, channel: str, person: str, summary: str,
                follow_up: date | None = None) -> int:
    with conn:
        cur = conn.execute(
            "INSERT INTO contacts(vehicle_id, at, channel, person, summary, follow_up) VALUES (?,?,?,?,?,?)",
            (vehicle_id, utcnow(), channel if channel in CHANNELS else "other", person.strip(), summary.strip(),
             follow_up.isoformat() if follow_up else None))
    return cur.lastrowid


def contacts(conn: sqlite3.Connection, vehicle_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM contacts WHERE vehicle_id=? ORDER BY at DESC", (vehicle_id,))]


def delete_contact(conn: sqlite3.Connection, contact_id: int) -> None:
    with conn:
        conn.execute("DELETE FROM contacts WHERE id=?", (contact_id,))


def contact_summary(conn: sqlite3.Connection) -> dict[int, dict]:
    """vehicle_id -> last contact time and the latest pending follow-up date."""
    out: dict[int, dict] = {}
    for r in conn.execute("SELECT vehicle_id, MAX(at) AS last_at, MAX(follow_up) AS follow_up FROM contacts"
                          " GROUP BY vehicle_id"):
        out[r["vehicle_id"]] = {"last_contact": r["last_at"], "follow_up": r["follow_up"]}
    return out
