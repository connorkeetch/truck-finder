"""Attribute claims with source attribution, and resolution of one canonical value per field.

Resolution order: user override (verified) > highest confidence > most recent observation.
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field

from .db import utcnow
from .models import CONFIDENCE_RANK, AttributeClaim

RESOLVED_FIELDS = [
    "generation", "battery", "motor", "tonneau", "epa_range", "wheels", "in_service_date",
    "warranty_expiration", "warranty_miles", "battery_warranty_expiration", "battery_warranty_miles",
    "title_status", "accident_history", "exterior_color", "interior_color", "trim",
    "model_year", "tow_capacity_lbs",
]
DEFAULTS = {"tonneau": "unknown", "title_status": "unknown", "accident_history": "unknown",
            "battery": "Unknown", "motor": "Unknown", "generation": "Unknown"}
# A claim of the key value is compatible with (and refined by) a claim of any listed value.
REFINEMENTS = {"motor": {"Dual": {"Performance Dual"}}}
# Values that do not contradict each other (a verified "working" tonneau is consistent with "listed").
COMPATIBLE = {"tonneau": {},
              "motor": {"Performance Dual": {"Dual"}}}
NON_CONFLICT_FIELDS = {"tonneau_mention", "vpic_decoded", "plant"}


@dataclass
class Resolved:
    field: str
    value: str | None
    source: str = ""
    method: str = ""
    confidence: str = ""
    evidence: str | None = None
    conflict: bool = False
    alternatives: list[dict] = field(default_factory=list)


def record_claims(conn: sqlite3.Connection, vehicle_id: int, claims: list[AttributeClaim],
                  listing_id: int | None = None, default_source: str = "", now: str | None = None) -> int:
    """Insert claims, refreshing observed_at for identical ones. Returns number of new rows."""
    now = now or utcnow()
    added = 0
    for c in claims:
        source = c.source or default_source
        row = conn.execute(
            "SELECT id FROM vehicle_attributes WHERE vehicle_id=? AND field=? AND value=? AND source=?"
            " AND method=? AND listing_id IS ?",
            (vehicle_id, c.field, str(c.value), source, c.method, listing_id),
        ).fetchone()
        if row:
            conn.execute("UPDATE vehicle_attributes SET observed_at=?, evidence=COALESCE(?, evidence) WHERE id=?",
                         (now, c.evidence, row[0]))
        else:
            conn.execute(
                "INSERT INTO vehicle_attributes(vehicle_id, listing_id, field, value, source, method, confidence,"
                " evidence, observed_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (vehicle_id, listing_id, c.field, str(c.value), source, c.method, c.confidence, c.evidence, now),
            )
            added += 1
    return added


def _resolve_field(fname: str, claims: list[dict], override: dict | None) -> Resolved:
    alternatives = [
        {"value": c["value"], "source": c["source"], "method": c["method"], "confidence": c["confidence"],
         "evidence": c["evidence"], "observed_at": c["observed_at"]}
        for c in claims
    ]
    if override:
        ok = {override["value"]} | COMPATIBLE.get(fname, {}).get(override["value"], set())
        conflict = any(c["value"] not in ok for c in claims)
        return Resolved(fname, override["value"], "user", "Manually verified" + (f": {override['note']}" if override.get("note") else ""),
                        "verified", None, conflict, alternatives)
    if not claims:
        return Resolved(fname, DEFAULTS.get(fname), "", "No source has reported this", "", None, False, [])
    ranked = sorted(claims, key=lambda c: (CONFIDENCE_RANK.get(c["confidence"], 0), c["observed_at"]), reverse=True)
    best = ranked[0]
    # Among equally trusted claims, the value more independent sources agree on wins (not just the newest).
    top = [c for c in claims if CONFIDENCE_RANK.get(c["confidence"], 0) == CONFIDENCE_RANK.get(best["confidence"], 0)]
    support: dict[str, set] = {}
    for c in top:
        support.setdefault(c["value"], set()).add((c["source"], c["method"]))
    if len(support) > 1:
        most = max(len(v) for v in support.values())
        leaders = [val for val, srcs in support.items() if len(srcs) == most]
        if len(leaders) == 1 and leaders[0] != best["value"]:
            best = next(c for c in ranked if c["value"] == leaders[0])
    values = {c["value"] for c in claims}
    refinements = REFINEMENTS.get(fname, {}).get(best["value"], set())
    refined = [c for c in ranked if c["value"] in refinements]
    if refined:
        r = refined[0]
        others = values - {best["value"], r["value"]}
        return Resolved(fname, r["value"], r["source"],
                        f"{r['method']} (consistent with {best['source']}: {best['value']})",
                        r["confidence"], r["evidence"], bool(others), alternatives)
    return Resolved(fname, best["value"], best["source"], best["method"], best["confidence"], best["evidence"],
                    len(values) > 1, alternatives)


def resolve_many(conn: sqlite3.Connection, vehicle_ids: list[int] | None = None) -> dict[int, dict[str, Resolved]]:
    """Canonical attributes for many vehicles with two queries."""
    where, params = "", []
    if vehicle_ids is not None:
        if not vehicle_ids:
            return {}
        where = f" WHERE vehicle_id IN ({','.join('?' * len(vehicle_ids))})"
        params = list(vehicle_ids)
    claims: dict[int, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for r in conn.execute("SELECT * FROM vehicle_attributes" + where, params):
        claims[r["vehicle_id"]][r["field"]].append(dict(r))
    overrides: dict[int, dict[str, dict]] = defaultdict(dict)
    for r in conn.execute("SELECT * FROM user_overrides" + where, params):
        overrides[r["vehicle_id"]][r["field"]] = dict(r)
    ids = vehicle_ids if vehicle_ids is not None else sorted(set(claims) | set(overrides))
    out: dict[int, dict[str, Resolved]] = {}
    for vid in ids:
        fields = set(RESOLVED_FIELDS) | set(claims[vid]) | set(overrides[vid])
        out[vid] = {f: _resolve_field(f, claims[vid].get(f, []), overrides[vid].get(f)) for f in fields}
        for f in NON_CONFLICT_FIELDS & set(out[vid]):
            out[vid][f].conflict = False
    return out


def resolve(conn: sqlite3.Connection, vehicle_id: int) -> dict[str, Resolved]:
    return resolve_many(conn, [vehicle_id]).get(vehicle_id, {})


def set_override(conn: sqlite3.Connection, vehicle_id: int, fname: str, value: str | None, note: str = "") -> None:
    """Set (or clear, when value is None/empty) a manually verified value."""
    with conn:
        if value in (None, ""):
            conn.execute("DELETE FROM user_overrides WHERE vehicle_id=? AND field=?", (vehicle_id, fname))
        else:
            conn.execute(
                "INSERT INTO user_overrides(vehicle_id, field, value, note, created_at) VALUES (?,?,?,?,?)"
                " ON CONFLICT(vehicle_id, field) DO UPDATE SET value=excluded.value, note=excluded.note,"
                " created_at=excluded.created_at",
                (vehicle_id, fname, str(value), note, utcnow()),
            )


def generation_for_year(year: int | None) -> str | None:
    """Rivian's second-generation R1 platform began with model year 2025."""
    if not year:
        return None
    if 2022 <= year <= 2024:
        return "Gen 1"
    if year >= 2025:
        return "Gen 2"
    return None
