"""What's worth a notification after a run: new matching trucks, price drops on favorites, new great deals."""
from __future__ import annotations

import sqlite3

import pandas as pd

from . import queries

DEFAULTS = {
    "enabled": False,          # scheduled search on/off (the schedule itself lives in the OS task scheduler)
    "times": ["08:00"],
    "new_matches": True,
    "favorite_drops": True,
    "great_deals": True,
    "min_drop": 0,
    "notify_when_nothing": False,
}


def _name(r) -> str:
    year = f"{int(r['year'])} " if pd.notna(r.get("year")) else ""
    price = f"${r['price']:,.0f}" if pd.notna(r.get("price")) else "price ?"
    return f"{year}{r.get('make') or ''} {r.get('model') or 'Vehicle'} {r.get('trim') or ''}".strip() + f" {price} · {r.get('location') or ''}".rstrip(" ·")


def collect(conn: sqlite3.Connection, run_id: int, settings: dict) -> dict:
    """Return {'title', 'lines', 'count'} describing this run's notification-worthy changes."""
    a = {**DEFAULTS, **(settings.get("alerts") or {})}
    inv = queries.inventory_frame(conn, settings)
    if inv.empty:
        return {"title": "", "lines": [], "count": 0}
    matching = queries.apply_filters(inv, settings["filters"]).set_index("vehicle_id")
    rows = inv.set_index("vehicle_id")
    ev = conn.execute("SELECT vehicle_id, event_type, old_value, new_value FROM change_events WHERE run_id=?",
                      (run_id,)).fetchall()
    new_ids = [e["vehicle_id"] for e in ev if e["event_type"] == "new_listing" and e["vehicle_id"] in matching.index]
    lines, parts = [], []
    if a["new_matches"] and new_ids:
        parts.append(f"{len(new_ids)} new truck{'s' if len(new_ids) != 1 else ''}")
        for vid in new_ids[:3]:
            r = matching.loc[vid]
            tag = f" ({r['deal_label']})" if a["great_deals"] and r["deal_label"] in ("Great deal", "Good deal") else ""
            lines.append("New: " + _name(r) + tag)
    drops = []
    if a["favorite_drops"]:
        for e in ev:
            if e["event_type"] != "price_drop" or e["vehicle_id"] not in rows.index:
                continue
            r = rows.loc[e["vehicle_id"]]
            if not bool(r["favorite"]) or bool(r["hidden"]):
                continue
            try:
                amount = int(e["old_value"]) - int(e["new_value"])
            except (TypeError, ValueError):
                continue
            if amount >= int(a["min_drop"] or 0):
                drops.append((amount, r))
    if drops:
        parts.append(f"{len(drops)} favorite price drop{'s' if len(drops) != 1 else ''}")
        for amount, r in sorted(drops, key=lambda t: -t[0])[:3]:
            lines.append(f"★ −${amount:,}: " + _name(r))
    if a["great_deals"] and not a["new_matches"]:
        deals = [vid for vid in new_ids if matching.loc[vid]["deal_label"] == "Great deal"]
        if deals:
            parts.append(f"{len(deals)} new great deal{'s' if len(deals) != 1 else ''}")
            lines += ["Deal: " + _name(matching.loc[vid]) for vid in deals[:3]]
    count = len(new_ids) * bool(a["new_matches"]) + len(drops)
    title = "Truck Finder: " + (", ".join(parts) if parts else "no changes")
    return {"title": title, "lines": lines, "count": count}
