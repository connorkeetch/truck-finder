"""Vehicle identity: VIN-first deduplication, conservative fuzzy candidates, and reviewed merges."""
from __future__ import annotations

import re
import sqlite3

from .attributes import generation_for_year, record_claims
from .db import utcnow
from .models import AttributeClaim
from .vin import clean_vin, is_rivian_r1t, model_year, validate_vin

CANDIDATE_THRESHOLD = 6.0


CHAINS = ("carvana", "carmax", "vroom", "rivian", "autonation", "drivetime", "echopark", "shift")
_SELLER_NOISE = re.compile(r"\b(?:of|the|inc|llc|co|corp|ltd)\b")


def norm_seller(name: str | None) -> str:
    """Comparison key for a seller: chain locations collapse to the chain; 'of', suffixes and punctuation ignored."""
    n = (name or "").lower()
    n = re.split(r"\s+[-–(|]\s*|\s*\(", n, maxsplit=1)[0]      # drop " - Columbus", " (South Jordan)"
    key = re.sub(r"[^a-z0-9]", "", _SELLER_NOISE.sub(" ", n))
    for chain in CHAINS:
        if key.startswith(chain):
            return chain
    return key


def vin_claims(vin: str) -> list[AttributeClaim]:
    """Facts that follow deterministically from a validated VIN."""
    claims = []
    yr = model_year(vin)
    if yr:
        claims.append(AttributeClaim("model_year", str(yr), "high", "VIN position 10 (model year code)",
                                     source="vin_rule", evidence=vin))
        gen = generation_for_year(yr) if is_rivian_r1t(vin) else None
        if gen:
            claims.append(AttributeClaim("generation", gen, "high",
                                         "Model-year rule: MY2022–2024 = Gen 1, MY2025+ = Gen 2",
                                         source="vin_rule", evidence=f"MY{yr} from VIN"))
    return claims


def resolve_vehicle_id(conn: sqlite3.Connection, vehicle_id: int) -> int:
    """Follow merged_into_id pointers to the surviving vehicle."""
    seen = set()
    while True:
        row = conn.execute("SELECT merged_into_id FROM vehicles WHERE id=?", (vehicle_id,)).fetchone()
        if not row or not row[0] or vehicle_id in seen:
            return vehicle_id
        seen.add(vehicle_id)
        vehicle_id = row[0]


def get_or_create_vehicle(conn: sqlite3.Connection, vin: str | None, year: int | None, make: str | None,
                          model: str | None, trim: str | None, is_demo: bool, now: str) -> tuple[int, bool]:
    """Return (vehicle_id, created). Valid VINs map to exactly one vehicle; anything else is provisional."""
    cleaned = clean_vin(vin)
    valid, _ = validate_vin(cleaned) if cleaned else (False, "")
    if valid:
        row = conn.execute("SELECT id FROM vehicles WHERE vin=?", (cleaned,)).fetchone()
        if row:
            vid = resolve_vehicle_id(conn, row[0])
            conn.execute(
                "UPDATE vehicles SET year=COALESCE(year, ?), make=COALESCE(make, ?), model=COALESCE(model, ?),"
                " trim=COALESCE(trim, ?), updated_at=? WHERE id=?",
                (year, make, model, trim, now, vid),
            )
            return vid, False
        yr = model_year(cleaned) or year
        cur = conn.execute(
            "INSERT INTO vehicles(vin, year, make, model, trim, is_demo, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (cleaned, yr, make, model, trim, int(is_demo), now, now),
        )
        vid = cur.lastrowid
        record_claims(conn, vid, vin_claims(cleaned), now=now)
        return vid, True
    cur = conn.execute(
        "INSERT INTO vehicles(vin, vin_raw, year, make, model, trim, is_demo, created_at, updated_at)"
        " VALUES (NULL,?,?,?,?,?,?,?,?)",
        (cleaned or None, year, make, model, trim, int(is_demo), now, now),
    )
    vid = cur.lastrowid
    gen = generation_for_year(year) if (model or "").upper() == "R1T" else None
    if gen:
        record_claims(conn, vid, [AttributeClaim("generation", gen, "medium",
                                                 "Model-year rule applied to the listed year (VIN unknown)",
                                                 source="listing_year", evidence=f"Listed as {year}")], now=now)
    return vid, True


def _listing_profile(conn: sqlite3.Connection, vehicle_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT l.*, v.year AS v_year, v.make AS v_make, v.model AS v_model, v.vin AS v_vin FROM listings l"
        " JOIN vehicles v ON v.id = l.vehicle_id WHERE l.vehicle_id=?", (vehicle_id,))]


def score_pair(a: dict, b: dict) -> tuple[float, list[str]]:
    """Similarity of two listings that lack a shared VIN. Higher = more likely the same truck."""
    if a.get("v_vin") and b.get("v_vin") and a["v_vin"] != b["v_vin"]:
        return 0.0, ["different VINs"]
    if a.get("v_make") and b.get("v_make") and a["v_make"].casefold() != b["v_make"].casefold():
        return 0.0, ["different makes"]
    score, reasons = 0.0, []
    if a.get("v_year") and b.get("v_year"):
        if a["v_year"] != b["v_year"]:
            return 0.0, ["different model years"]
        score += 2
        reasons.append(f"same year {a['v_year']}")
    if a.get("v_model") and b.get("v_model") and a["v_model"].upper() != b["v_model"].upper():
        return 0.0, ["different models"]
    ca, cb = (a.get("exterior_color") or "").lower(), (b.get("exterior_color") or "").lower()
    if ca and cb:
        if ca == cb:
            score += 1.5
            reasons.append(f"same color {a['exterior_color']}")
        else:
            score -= 3
            reasons.append("different colors")
    ma, mb = a.get("current_miles"), b.get("current_miles")
    if ma is not None and mb is not None:
        diff = abs(ma - mb)
        if diff <= 300:
            score += 3
            reasons.append(f"mileage within {diff:,} mi")
        elif diff <= 2000:
            score += 1.5
            reasons.append(f"mileage within {diff:,} mi")
        elif diff > 8000:
            score -= 2
            reasons.append(f"mileage differs by {diff:,} mi")
    pa, pb = a.get("current_price"), b.get("current_price")
    if pa and pb:
        rel = abs(pa - pb) / max(pa, pb)
        if rel <= 0.03:
            score += 1.5
            reasons.append(f"price within {rel:.0%}")
        elif rel > 0.15:
            score -= 1
            reasons.append(f"price differs by {rel:.0%}")
    sa, sb = norm_seller(a.get("seller_name")), norm_seller(b.get("seller_name"))
    if sa and sb and sa == sb:
        score += 2
        reasons.append("same seller")
    if a.get("state") and b.get("state"):
        if a["state"] == b["state"]:
            score += 0.5
            if a.get("city") and b.get("city") and a["city"].lower() == b["city"].lower():
                score += 1
                reasons.append(f"same city {a['city']}")
            else:
                reasons.append(f"same state {a['state']}")
        else:
            score -= 1.5
            reasons.append("different states")
    return score, reasons


def find_candidates(conn: sqlite3.Connection, vehicle_id: int, now: str | None = None) -> list[tuple[int, float, str]]:
    """Queue possible duplicates of `vehicle_id` for review. Never merges anything automatically."""
    now = now or utcnow()
    mine = _listing_profile(conn, vehicle_id)
    if not mine:
        return []
    me = conn.execute("SELECT vin FROM vehicles WHERE id=?", (vehicle_id,)).fetchone()
    has_vin = bool(me and me[0])
    # Only pairs where at least one side lacks a VIN can be ambiguous.
    others = conn.execute(
        "SELECT id FROM vehicles WHERE id != ? AND merged_into_id IS NULL"
        + (" AND vin IS NULL" if has_vin else ""), (vehicle_id,)).fetchall()
    found = []
    for (oid,) in others:
        best, best_reasons = 0.0, []
        for la in mine:
            for lb in _listing_profile(conn, oid):
                s, r = score_pair(la, lb)
                if s > best:
                    best, best_reasons = s, r
        if best >= CANDIDATE_THRESHOLD:
            a, b = sorted((vehicle_id, oid))
            conn.execute(
                "INSERT OR IGNORE INTO match_candidates(vehicle_id, candidate_vehicle_id, score, reasons, created_at)"
                " VALUES (?,?,?,?,?)", (a, b, best, "; ".join(best_reasons), now))
            found.append((oid, best, "; ".join(best_reasons)))
    return found


def merge_vehicles(conn: sqlite3.Connection, keep_id: int, merge_id: int, reason: str = "user review") -> int:
    """Fold merge_id into keep_id, preserving every listing, observation, claim, and note."""
    if keep_id == merge_id:
        return keep_id
    now = utcnow()
    keep = conn.execute("SELECT * FROM vehicles WHERE id=?", (keep_id,)).fetchone()
    gone = conn.execute("SELECT * FROM vehicles WHERE id=?", (merge_id,)).fetchone()
    if not keep or not gone:
        raise ValueError("vehicle not found")
    if keep["vin"] and gone["vin"] and keep["vin"] != gone["vin"]:
        raise ValueError("refusing to merge two vehicles with different validated VINs")
    with conn:
        conn.execute("UPDATE listings SET vehicle_id=? WHERE vehicle_id=?", (keep_id, merge_id))
        conn.execute("UPDATE vehicle_attributes SET vehicle_id=? WHERE vehicle_id=?", (keep_id, merge_id))
        conn.execute("UPDATE change_events SET vehicle_id=? WHERE vehicle_id=?", (keep_id, merge_id))
        # Keep the surviving vehicle's overrides when both have one for the same field.
        conn.execute(
            "UPDATE OR IGNORE user_overrides SET vehicle_id=? WHERE vehicle_id=?", (keep_id, merge_id))
        conn.execute("DELETE FROM user_overrides WHERE vehicle_id=?", (merge_id,))
        if conn.execute("SELECT 1 FROM watchlist WHERE vehicle_id=?", (merge_id,)).fetchone():
            conn.execute("INSERT OR IGNORE INTO watchlist(vehicle_id, added_at) VALUES (?, ?)", (keep_id, now))
            conn.execute("DELETE FROM watchlist WHERE vehicle_id=?", (merge_id,))
        notes = "\n".join(n for n in (keep["notes"], gone["notes"]) if n)
        vin = keep["vin"] or gone["vin"]
        conn.execute("UPDATE vehicles SET vin=NULL, merged_into_id=?, updated_at=? WHERE id=?", (keep_id, now, merge_id))
        conn.execute(
            "UPDATE vehicles SET vin=?, year=COALESCE(year, ?), trim=COALESCE(trim, ?), notes=?, updated_at=?,"
            " hidden_at=COALESCE(hidden_at, ?), hidden_reason=COALESCE(hidden_reason, ?),"
            " hidden_note=COALESCE(hidden_note, ?), photo_url=COALESCE(photo_url, ?) WHERE id=?",
            (vin, gone["year"], gone["trim"], notes, now, gone["hidden_at"], gone["hidden_reason"],
             gone["hidden_note"], gone["photo_url"], keep_id))
        conn.execute(
            "UPDATE match_candidates SET status='merged', resolved_at=? WHERE status='pending' AND"
            " ((vehicle_id=? AND candidate_vehicle_id=?) OR (vehicle_id=? AND candidate_vehicle_id=?))",
            (now, keep_id, merge_id, merge_id, keep_id))
        conn.execute(
            "UPDATE match_candidates SET status='rejected', resolved_at=? WHERE status='pending' AND"
            " (vehicle_id=? OR candidate_vehicle_id=?)", (now, merge_id, merge_id))
        conn.execute("INSERT INTO merges(kept_vehicle_id, merged_vehicle_id, reason, created_at) VALUES (?,?,?,?)",
                     (keep_id, merge_id, reason, now))
    return keep_id


def reject_candidate(conn: sqlite3.Connection, candidate_id: int) -> None:
    with conn:
        conn.execute("UPDATE match_candidates SET status='rejected', resolved_at=? WHERE id=?", (utcnow(), candidate_id))


def set_vin(conn: sqlite3.Connection, vehicle_id: int, raw_vin: str) -> tuple[int, str]:
    """Attach a VIN to a vehicle. If another vehicle already has it, merge into that one (same validated VIN)."""
    vin = clean_vin(raw_vin)
    ok, reason = validate_vin(vin)
    if not ok:
        raise ValueError(reason)
    now = utcnow()
    current = conn.execute("SELECT vin FROM vehicles WHERE id=?", (vehicle_id,)).fetchone()
    if current and current[0] == vin:
        return vehicle_id, "VIN unchanged"
    if current and current[0]:
        raise ValueError(f"vehicle already has VIN {current[0]}")
    existing = conn.execute("SELECT id FROM vehicles WHERE vin=?", (vin,)).fetchone()
    if existing:
        keep = merge_vehicles(conn, existing[0], vehicle_id, reason="same VIN entered by user")
        return keep, "merged into existing vehicle with the same VIN"
    with conn:
        conn.execute("UPDATE vehicles SET vin=?, year=COALESCE(?, year), updated_at=? WHERE id=?",
                     (vin, model_year(vin), now, vehicle_id))
        record_claims(conn, vehicle_id, vin_claims(vin), now=now)
    return vehicle_id, "VIN set"
