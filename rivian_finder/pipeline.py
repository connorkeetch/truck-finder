"""Ingest normalized listings, track history, and detect changes between runs."""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from dataclasses import dataclass, field

from . import dedup
from .attributes import record_claims, resolve_many
from .db import utcnow
from .extract import canonical_url, extract_attributes
from .geo import distance_from_zip
from .models import AttributeClaim, FetchResult, NormalizedListing, NotConfigured, RateLimited, SourceError
from .sources.base import collection_scopes, matches_target
from .trims import excluded_trim, standard_range
from .vin import clean_vin, is_valid_vin

log = logging.getLogger(__name__)

EQUIPMENT_FIELDS = ("battery", "motor", "tonneau", "wheels", "epa_range", "tow_capacity_lbs", "exterior_color")
EVENT_LABELS = {
    "new_listing": "New vehicle",
    "new_source_for_vin": "New source for known vehicle",
    "price_drop": "Price decrease",
    "price_increase": "Price increase",
    "mileage_update": "Mileage update",
    "seller_change": "Seller change",
    "disappeared": "Not seen in latest complete scan",
    "returned": "Returned after disappearing",
    "equipment_change": "Equipment change",
    "description_change": "Description change",
    "marked_removed": "Marked sold/removed",
    "provider_removed": "Provider reports removed",
}


def _content_hash(nl: NormalizedListing) -> str:
    payload = {
        "trim": nl.trim, "title": nl.title, "desc": (nl.description or "")[:20000],
        "equip": sorted((c.field, c.value) for c in nl.attributes if c.field in EQUIPMENT_FIELDS),
    }
    return hashlib.sha1(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


@dataclass
class IngestOutcome:
    listing_id: int
    vehicle_id: int
    created_listing: bool
    created_vehicle: bool
    events: list[str] = field(default_factory=list)


class Ingestor:
    def __init__(self, conn: sqlite3.Connection, run_id: int | None, now: str | None = None):
        self.conn = conn
        self.run_id = run_id
        self.now = now or utcnow()

    def _event(self, listing_id, vehicle_id, kind, old=None, new=None):
        self.conn.execute(
            "INSERT INTO change_events(run_id, listing_id, vehicle_id, event_type, old_value, new_value, created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (self.run_id, listing_id, vehicle_id, kind, None if old is None else str(old),
             None if new is None else str(new), self.now),
        )

    def _find_listing(self, nl: NormalizedListing, canon: str | None):
        if nl.source_listing_id:
            row = self.conn.execute("SELECT * FROM listings WHERE source_key=? AND source_listing_id=?",
                                    (nl.source_key, nl.source_listing_id)).fetchone()
            if row:
                return row
        if canon:
            vin = clean_vin(nl.vin)
            for row in self.conn.execute(
                    "SELECT l.*, v.vin AS v_vin FROM listings l JOIN vehicles v ON v.id = l.vehicle_id"
                    " WHERE l.url_canonical=? ORDER BY l.id", (canon,)):
                if vin and is_valid_vin(vin) and row["v_vin"] and row["v_vin"] != vin:
                    continue        # same page address, different truck (e.g. shared aggregator URL)
                return row
        return None

    def _listing_claims(self, listing_id: int) -> dict[str, set[str]]:
        out: dict[str, set[str]] = {}
        for r in self.conn.execute(
                "SELECT field, value FROM vehicle_attributes WHERE listing_id=? AND field IN (%s)"
                % ",".join("?" * len(EQUIPMENT_FIELDS)), (listing_id, *EQUIPMENT_FIELDS)):
            out.setdefault(r["field"], set()).add(r["value"])
        return out

    def ingest(self, nl: NormalizedListing, vehicle_id: int | None = None) -> IngestOutcome:
        """Record one listing. Pass vehicle_id to attach a new listing to a known truck (e.g. a seller link
        the user found for a VIN-less vehicle)."""
        conn, now = self.conn, self.now
        forced_vehicle = vehicle_id
        canon = canonical_url(nl.url)
        content_hash = _content_hash(nl)
        existing = self._find_listing(nl, canon)
        vin = clean_vin(nl.vin)
        created_vehicle = False

        if existing:
            vehicle_id = dedup.resolve_vehicle_id(conn, existing["vehicle_id"])
            if vin and is_valid_vin(vin):
                current_vin = conn.execute("SELECT vin FROM vehicles WHERE id=?", (vehicle_id,)).fetchone()[0]
                if not current_vin:
                    vehicle_id, _ = dedup.set_vin(conn, vehicle_id, vin)
                elif current_vin != vin:
                    record_claims(conn, vehicle_id, [AttributeClaim(
                        "vin_conflict", vin, "low", "Listing now reports a different VIN", source=nl.source_key)],
                        listing_id=existing["id"], now=now)
        elif forced_vehicle is not None:
            vehicle_id = dedup.resolve_vehicle_id(conn, forced_vehicle)
        else:
            vehicle_id, created_vehicle = dedup.get_or_create_vehicle(
                conn, nl.vin, nl.year, nl.make, nl.model, nl.trim, nl.is_demo, now)

        events: list[str] = []
        if existing:
            listing_id = existing["id"]
            old_claims = self._listing_claims(listing_id)
            user_removed = existing["status"] == "removed" and (existing["status_reason"] or "").startswith("Marked")
            if existing["status"] in ("missing", "removed") and nl.available and not user_removed:
                self._event(listing_id, vehicle_id, "returned", existing["status"], "active")
                events.append("returned")
            if nl.price is not None and existing["current_price"] is not None and nl.price != existing["current_price"]:
                kind = "price_drop" if nl.price < existing["current_price"] else "price_increase"
                self._event(listing_id, vehicle_id, kind, existing["current_price"], nl.price)
                events.append(kind)
            if nl.miles is not None and existing["current_miles"] is not None and nl.miles != existing["current_miles"]:
                self._event(listing_id, vehicle_id, "mileage_update", existing["current_miles"], nl.miles)
                events.append("mileage_update")
            if (nl.seller_name and existing["seller_name"]
                    and dedup.norm_seller(nl.seller_name) != dedup.norm_seller(existing["seller_name"])):
                self._event(listing_id, vehicle_id, "seller_change", existing["seller_name"], nl.seller_name)
                events.append("seller_change")
            new_claims: dict[str, set[str]] = {}
            for c in nl.attributes:
                if c.field in EQUIPMENT_FIELDS:
                    new_claims.setdefault(c.field, set()).add(str(c.value))
            changed = [f"{f}: {', '.join(sorted(old_claims.get(f, []))) or '—'} → {', '.join(sorted(new_claims.get(f, []))) or '—'}"
                       for f in EQUIPMENT_FIELDS
                       if f in new_claims and old_claims.get(f) and new_claims.get(f) != old_claims.get(f)]
            if changed:
                self._event(listing_id, vehicle_id, "equipment_change", None, "; ".join(changed))
                events.append("equipment_change")
            elif existing["content_hash"] and existing["content_hash"] != content_hash and nl.description:
                self._event(listing_id, vehicle_id, "description_change", None, (nl.description or "")[:200])
                events.append("description_change")
            status = "removed" if (nl.removed_at or user_removed) else ("active" if nl.available else existing["status"])
            conn.execute(
                """UPDATE listings SET vehicle_id=?, url=COALESCE(?, url), url_canonical=COALESCE(?, url_canonical),
                   title=COALESCE(?, title), description=COALESCE(?, description),
                   seller_name=COALESCE(?, seller_name), seller_type=COALESCE(?, seller_type),
                   city=COALESCE(?, city), state=COALESCE(?, state), zip=COALESCE(?, zip),
                   lat=COALESCE(?, lat), lon=COALESCE(?, lon),
                   exterior_color=COALESCE(?, exterior_color), interior_color=COALESCE(?, interior_color),
                   current_price=COALESCE(?, current_price), current_miles=COALESCE(?, current_miles),
                   transport_cost=COALESCE(transport_cost, ?), dealer_website=COALESCE(?, dealer_website),
                   seller_phone=COALESCE(?, seller_phone), history_report_url=COALESCE(?, history_report_url),
                   days_on_market=COALESCE(?, days_on_market), days_on_market_here=COALESCE(?, days_on_market_here),
                   photo_url=COALESCE(?, photo_url), photo_count=COALESCE(?, photo_count),
                   listed_at=CASE WHEN ? IS NOT NULL AND (listed_at IS NULL OR ? < listed_at) THEN ? ELSE listed_at END,
                   status=?, status_reason=?, missing_since=CASE WHEN ?='active' THEN NULL ELSE missing_since END,
                   last_seen_at=?, last_run_id=?, content_hash=?, raw_json=COALESCE(?, raw_json)
                   WHERE id=?""",
                (vehicle_id, nl.url, canon, nl.title, nl.description, nl.seller_name, nl.seller_type,
                 nl.city, nl.state, nl.zip, nl.lat, nl.lon, nl.exterior_color, nl.interior_color,
                 nl.price, nl.miles, nl.transport_cost, nl.dealer_website, nl.seller_phone, nl.history_report_url,
                 nl.days_on_market, nl.days_on_market_here, nl.photo_url, nl.photo_count, nl.listed_at, nl.listed_at,
                 nl.listed_at, status,
                 existing["status_reason"] if user_removed else (f"Provider reports removed at {nl.removed_at}"
                                                                 if nl.removed_at else None), status,
                 now, self.run_id, content_hash, json.dumps(nl.raw) if nl.raw else None, listing_id),
            )
            if nl.removed_at and existing["status"] != "removed":
                self._event(listing_id, vehicle_id, "provider_removed", existing["status"], nl.removed_at)
                events.append("provider_removed")
        else:
            had_listings = conn.execute("SELECT COUNT(*) FROM listings WHERE vehicle_id=?", (vehicle_id,)).fetchone()[0]
            cur = conn.execute(
                """INSERT INTO listings(vehicle_id, source_key, import_method, source_listing_id, url, url_canonical,
                   title, description, seller_name, seller_type, city, state, zip, lat, lon, exterior_color,
                   interior_color, current_price, current_miles, status, status_reason, first_seen_at, last_seen_at,
                   last_run_id, content_hash, transport_cost, is_demo, raw_json, dealer_website, seller_phone,
                   history_report_url, listed_at, days_on_market, photo_url, photo_count, days_on_market_here)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (vehicle_id, nl.source_key, nl.import_method, nl.source_listing_id, nl.url, canon, nl.title,
                 nl.description, nl.seller_name, nl.seller_type, nl.city, nl.state, nl.zip, nl.lat, nl.lon,
                 nl.exterior_color, nl.interior_color, nl.price, nl.miles,
                 "removed" if nl.removed_at else "active",
                 f"Provider reports removed at {nl.removed_at}" if nl.removed_at else None,
                 now, now, self.run_id, content_hash, nl.transport_cost, int(nl.is_demo),
                 json.dumps(nl.raw) if nl.raw else None, nl.dealer_website, nl.seller_phone, nl.history_report_url,
                 nl.listed_at, nl.days_on_market, nl.photo_url, nl.photo_count, nl.days_on_market_here),
            )
            listing_id = cur.lastrowid
            kind = "new_listing" if (created_vehicle or had_listings == 0) else "new_source_for_vin"
            self._event(listing_id, vehicle_id, kind, None, nl.price)
            events.append(kind)

        conn.execute(
            "INSERT INTO observations(listing_id, run_id, observed_at, import_method, price, miles, available,"
            " seller_name, content_hash) VALUES (?,?,?,?,?,?,?,?,?)",
            (listing_id, self.run_id, now, nl.import_method, nl.price, nl.miles, int(nl.available and not nl.removed_at),
             nl.seller_name, content_hash),
        )
        claims = list(nl.attributes)
        if nl.trim:
            claims.append(AttributeClaim("trim", nl.trim, "medium", f"Listing trim field ({nl.source_key})"))
            have = {(c.field, c.value) for c in claims}
            claims += [c for c in extract_attributes(nl.trim, "Listing trim name", "medium", structured=True,
                                                    make=nl.make, model=nl.model)
                       if c.field in ("battery", "motor") and (c.field, c.value) not in have]
        if nl.exterior_color and not any(c.field == "exterior_color" for c in claims):
            claims.append(AttributeClaim("exterior_color", nl.exterior_color, "medium", "Listing color field"))
        if nl.interior_color:
            claims.append(AttributeClaim("interior_color", nl.interior_color, "medium", "Listing color field"))
        record_claims(conn, vehicle_id, claims, listing_id=listing_id, default_source=nl.source_key, now=now)
        if created_vehicle:
            dedup.find_candidates(conn, vehicle_id, now)
        return IngestOutcome(listing_id, vehicle_id, not existing, created_vehicle, events)


def outside_scope(year, price, miles, scope: dict | None) -> str | None:
    """Why a listing would not be returned by the collection query any more (None if it would be)."""
    if not scope:
        return None
    if year and scope.get("year_min") and year < int(scope["year_min"]):
        return f"model year {year} is before {scope['year_min']}"
    if year and scope.get("year_max") and year > int(scope["year_max"]):
        return f"model year {year} is after {scope['year_max']}"
    if price and scope.get("max_price") and price > int(scope["max_price"]):
        return f"last price ${price:,} is above ${int(scope['max_price']):,}"
    if miles is not None and scope.get("max_miles") and miles > int(scope["max_miles"]):
        return f"last mileage {miles:,} is above {int(scope['max_miles']):,}"
    return None


def mark_disappeared(conn: sqlite3.Connection, run_id: int, source_key: str, seen_listing_ids: set[int],
                     now: str | None = None, scope: dict | None = None, detect_missing: bool = True) -> tuple[int, int]:
    """After a COMPLETE scan, active listings from this source that were not seen become 'missing'.

    Listings the collection query no longer covers (e.g. a 2022 truck after the scope moved to 2023+) are marked
    'missing' with a "not re-checked" reason but are NOT counted as disappeared. Returns (disappeared, unchecked).
    """
    now = now or utcnow()
    rows = conn.execute(
        "SELECT l.id, l.vehicle_id, l.current_price, l.current_miles, l.lat, l.lon, l.zip, l.city, l.state, l.title,"
        " v.year, v.make, v.model, v.trim FROM listings l"
        " JOIN vehicles v ON v.id = l.vehicle_id WHERE l.source_key=? AND l.import_method IN ('api', 'demo')"
        " AND l.status='active'", (source_key,)).fetchall()
    n, unchecked = 0, 0
    brands = None if (scope or {}).get("brands") is None else {b.lower() for b in scope["brands"]}
    resolved = resolve_many(conn, list({r["vehicle_id"] for r in rows if r["id"] not in seen_listing_ids})) \
        if (scope or {}).get("exclude_standard_range") else {}
    for r in rows:
        if r["id"] in seen_listing_ids:
            continue
        if brands is not None and (r["make"] or "").lower() not in brands:
            continue
        if excluded_trim(r["make"], r["model"], r["trim"], (scope or {}).get("excluded_trims")):
            continue
        battery = resolved.get(r["vehicle_id"], {}).get("battery")
        if (scope or {}).get("exclude_standard_range") and standard_range(
                r["make"], r["model"], r["trim"], r["title"], battery.value if battery else None):
            continue
        listing_scope = scope
        if source_key in ("autodev", "marketcheck"):
            listing_scope = next((s for s in collection_scopes(scope or {}, source_key)
                                  if (matches_target(r["make"], r["model"], s)
                                      if (scope or {}).get("searches") is not None else
                                      (r["make"] or "").lower() in s.get("make", "Rivian").lower().split(",")
                                      and (r["model"] or "").lower() in s.get("model", "R1T").lower().split(","))), None)
            if listing_scope is None:
                continue        # This model was never part of the scan.
            radius = listing_scope.get("marketcheck_radius", 100) if source_key == "marketcheck" else listing_scope.get("distance", 0)
            if radius:
                center = listing_scope.get("marketcheck_zip" if source_key == "marketcheck" else "zip", "84020")
                distance = distance_from_zip(center, r["lat"], r["lon"], r["zip"], r["city"], r["state"])
                if distance is None or distance > int(radius):
                    continue    # The geographic query did not re-check this truck.
        why = outside_scope(r["year"], r["current_price"], r["current_miles"], listing_scope)
        if why:
            conn.execute("UPDATE listings SET status='missing', missing_since=?, status_reason=? WHERE id=?",
                         (now, f"Not re-checked: outside the collection scope ({why}). Not confirmed sold.", r["id"]))
            unchecked += 1
            continue
        if not detect_missing:
            continue
        conn.execute(
            "UPDATE listings SET status='missing', missing_since=?, status_reason=? WHERE id=?",
            (now, f"Not observed in complete scan (run {run_id}); not confirmed sold", r["id"]))
        conn.execute(
            "INSERT INTO change_events(run_id, listing_id, vehicle_id, event_type, old_value, new_value, created_at)"
            " VALUES (?,?,?,?,?,?,?)", (run_id, r["id"], r["vehicle_id"], "disappeared", "active", "missing", now))
        n += 1
    return n, unchecked


def mark_removed(conn: sqlite3.Connection, listing_id: int, reason: str = "Marked sold/removed by user") -> None:
    now = utcnow()
    with conn:
        row = conn.execute("SELECT vehicle_id, status FROM listings WHERE id=?", (listing_id,)).fetchone()
        conn.execute("UPDATE listings SET status='removed', status_reason=?, missing_since=COALESCE(missing_since, ?)"
                     " WHERE id=?", (reason, now, listing_id))
        conn.execute(
            "INSERT INTO change_events(run_id, listing_id, vehicle_id, event_type, old_value, new_value, created_at)"
            " VALUES (NULL,?,?,?,?,?,?)", (listing_id, row["vehicle_id"], "marked_removed", row["status"], reason, now))


def start_run(conn: sqlite3.Connection, trigger: str, sources: list[str], now: str | None = None) -> int:
    with conn:
        cur = conn.execute("INSERT INTO runs(started_at, trigger, sources_requested) VALUES (?,?,?)",
                           (now or utcnow(), trigger, json.dumps(sources)))
    return cur.lastrowid


def _previous_scope(conn: sqlite3.Connection, source_key: str, run_id: int) -> str | None:
    row = conn.execute(
        "SELECT scope_hash FROM source_runs WHERE source_key=? AND run_id<? AND status IN ('success','partial')"
        " AND scope_hash IS NOT NULL ORDER BY id DESC LIMIT 1", (source_key, run_id)).fetchone()
    return row[0] if row else None


def run_source(conn: sqlite3.Connection, run_id: int, adapter, scope: dict, now: str | None = None) -> dict:
    """Run one connector inside a run. Failures never mark existing listings as missing."""
    now = now or utcnow()
    key = adapter.key
    with conn:
        sr_id = conn.execute("INSERT INTO source_runs(run_id, source_key, started_at) VALUES (?,?,?)",
                             (run_id, key, now)).lastrowid
    info = {"source": key, "name": adapter.name, "status": "failed", "complete": False, "listings_seen": 0,
            "api_calls": 0, "disappeared": 0, "error": None, "notes": []}
    scope_hash = None
    calls_before = getattr(adapter, "calls", 0)
    ok, why = adapter.is_configured()
    if not ok:
        info.update(status="skipped", error=why)
    else:
        try:
            result: FetchResult = adapter.fetch(scope)
            info["api_calls"] = result.api_calls
            info["notes"].extend(result.notes)
            with conn:
                ing = Ingestor(conn, run_id, now)
                listings = result.listings
                if scope.get("searches") is not None and key in ("autodev", "marketcheck"):
                    targets = collection_scopes(scope, key)
                    listings = [nl for nl in listings if any(matches_target(nl.make, nl.model, s) for s in targets)]
                if scope.get("brands") is not None:
                    brands = {b.lower() for b in scope["brands"]}
                    listings = [nl for nl in listings if (nl.make or "").lower() in brands]
                seen = {ing.ingest(nl).listing_id for nl in listings}
                info["listings_seen"] = len(listings)
                prev = _previous_scope(conn, key, run_id)
                unchecked = 0
                if not result.complete:
                    info["notes"].append("Incomplete scan: listings not seen were left unchanged.")
                elif prev is not None and prev != result.scope_hash:
                    info["notes"].append("Collection scope changed since the previous scan, so disappearance "
                                         "detection was skipped this time.")
                    _, unchecked = mark_disappeared(conn, run_id, key, seen, now, scope, detect_missing=False)
                else:
                    info["disappeared"], unchecked = mark_disappeared(conn, run_id, key, seen, now, scope)
                if result.complete and unchecked:
                    info["notes"].append(f"{unchecked} listing(s) now fall outside the collection scope; they are "
                                         "no longer checked and were not counted as missing.")
            info["complete"] = result.complete
            info["status"] = "success" if result.complete else "partial"
            if result.error:
                info["error"] = result.error
            scope_hash = result.scope_hash
        except NotConfigured as e:
            info.update(status="skipped", error=str(e))
        except RateLimited as e:
            info.update(status="failed", error=f"Rate limited: {e}")
        except SourceError as e:
            info.update(status="failed", error=str(e))
        except Exception as e:  # keep the run going; record the failure
            log.exception("source %s crashed", key)
            info.update(status="failed", error=f"{type(e).__name__}: {e}")
    finished = utcnow()
    if info["status"] in ("failed", "skipped"):
        info["api_calls"] = getattr(adapter, "calls", 0) - calls_before
    with conn:
        conn.execute(
            "UPDATE source_runs SET finished_at=?, status=?, complete=?, scope_hash=?, listings_seen=?, api_calls=?,"
            " error=?, notes=? WHERE id=?",
            (finished, info["status"], int(info["complete"]), scope_hash, info["listings_seen"],
             info["api_calls"], info["error"], "\n".join(info["notes"]), sr_id))
        conn.execute(
            "UPDATE sources SET last_attempt_at=?, last_status=?, last_error=?,"
            " last_success_at=CASE WHEN ? IN ('success','partial') THEN ? ELSE last_success_at END WHERE key=?",
            (finished, info["status"], info["error"], info["status"], finished, key))
    return info


def event_counts(conn: sqlite3.Connection, run_id: int) -> dict[str, int]:
    """Changes in a run, excluding trucks you marked not interested (those are tallied separately)."""
    counts = {k: 0 for k in EVENT_LABELS}
    counts["hidden_vehicle_updates"] = 0
    for r in conn.execute(
            "SELECT e.event_type, v.hidden_at IS NOT NULL AS hidden, COUNT(*) FROM change_events e"
            " LEFT JOIN vehicles v ON v.id = e.vehicle_id WHERE e.run_id=? GROUP BY e.event_type, hidden", (run_id,)):
        if r[1]:
            counts["hidden_vehicle_updates"] += r[2]
        else:
            counts[r[0]] = r[2]
    return counts


def finish_run(conn: sqlite3.Connection, run_id: int, source_infos: list[dict], extra: dict | None = None) -> dict:
    statuses = [s["status"] for s in source_infos]
    if statuses and all(s == "success" for s in statuses):
        status = "success"
    elif any(s in ("success", "partial") for s in statuses):
        status = "partial"
    else:
        status = "failed"
    summary = {"run_id": run_id, "status": status, "sources": source_infos, "counts": event_counts(conn, run_id)}
    summary.update(extra or {})
    with conn:
        conn.execute("UPDATE runs SET finished_at=?, status=?, summary_json=? WHERE id=?",
                     (utcnow(), status, json.dumps(summary, default=str), run_id))
    return summary


def run_search(conn: sqlite3.Connection, adapters: list, scope: dict, enrich=None) -> dict:
    """Run the given connectors, then optional enrichment. Returns the run summary dict."""
    run_id = start_run(conn, "run_search", [a.key for a in adapters])
    infos = [run_source(conn, run_id, a, scope) for a in adapters]
    extra = {}
    if enrich is not None:
        try:
            extra["enrichment"] = enrich(conn)
        except Exception as e:  # enrichment is best-effort
            extra["enrichment"] = {"error": f"{type(e).__name__}: {e}"}
    return finish_run(conn, run_id, infos, extra)


def import_listings(conn: sqlite3.Connection, listings: list[NormalizedListing], trigger: str) -> dict:
    """Manual/email/capture/CSV imports. These are never 'complete' scans, so nothing is marked missing."""
    run_id = start_run(conn, trigger, sorted({nl.source_key for nl in listings}))
    now = utcnow()
    outcomes = []
    with conn:
        sr_id = conn.execute(
            "INSERT INTO source_runs(run_id, source_key, started_at, status, complete, listings_seen, notes)"
            " VALUES (?,?,?,?,0,?,?)",
            (run_id, trigger, now, "success", len(listings), "User import: not a complete scan")).lastrowid
        ing = Ingestor(conn, run_id, now)
        for nl in listings:
            outcomes.append(ing.ingest(nl))
        conn.execute("UPDATE source_runs SET finished_at=? WHERE id=?", (utcnow(), sr_id))
    info = {"source": trigger, "name": trigger, "status": "success", "complete": False,
            "listings_seen": len(listings), "api_calls": 0, "disappeared": 0, "error": None,
            "notes": ["User import: not a complete scan"]}
    summary = finish_run(conn, run_id, [info])
    summary["listing_ids"] = [o.listing_id for o in outcomes]
    summary["vehicle_ids"] = [o.vehicle_id for o in outcomes]
    return summary
