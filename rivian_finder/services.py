"""Application-level operations used by the UI (and usable from scripts)."""
from __future__ import annotations

import sqlite3
import threading

from . import attributes, backup, credentials, enrich, photos, pipeline, queries, recalls
from .extract import identify_site
from .geo import zip_latlon
from .models import NormalizedListing
from .db import load_settings
from .sources.autodev import AutoDevAdapter
from .sources.base import API_CAPS, collection_scopes, configured_brands
from .sources.demo import DemoAdapter
from .sources.marketcheck import MarketCheckAdapter

API_SOURCES = ("autodev", "marketcheck")
SEARCH_LOCK = threading.RLock()


def source_enabled(conn: sqlite3.Connection, key: str) -> bool:
    row = conn.execute("SELECT enabled FROM sources WHERE key=?", (key,)).fetchone()
    return bool(row and row[0])


def make_adapter(conn: sqlite3.Connection, key: str):
    if key == "autodev":
        return AutoDevAdapter(credentials.get_api_key("autodev")[0], conn=conn)
    if key == "marketcheck":
        return MarketCheckAdapter(credentials.get_api_key("marketcheck")[0], conn=conn)
    if key == "demo":
        return DemoAdapter(conn)
    raise KeyError(key)


def available_sources(conn: sqlite3.Connection) -> list[dict]:
    """Automatic connectors with their readiness, for the Sources page."""
    out = []
    for key in (*API_SOURCES, "demo"):
        adapter = make_adapter(conn, key)
        ok, why = adapter.is_configured()
        out.append({"key": key, "name": adapter.name, "enabled": source_enabled(conn, key), "configured": ok,
                    "reason": why})
    return out


def run_sources(conn: sqlite3.Connection, keys: list[str] | None = None, settings: dict | None = None,
                brands: list[str] | None = None) -> dict:
    """Run the requested connectors (default: every enabled and configured one)."""
    with SEARCH_LOCK:
        return _run_sources(conn, keys, settings, brands)


def _run_sources(conn: sqlite3.Connection, keys: list[str] | None = None, settings: dict | None = None,
                 brands: list[str] | None = None) -> dict:
    settings = settings or load_settings(conn)
    try:
        names = {brand.casefold(): brand for brand in configured_brands(settings["collection"])}
    except ValueError as e:
        return {"status": "failed", "sources": [], "counts": {}, "text": str(e)}
    if brands is not None:
        if not isinstance(brands, list) or not brands or any(
                not isinstance(brand, str) or brand.strip().casefold() not in names for brand in brands):
            return {"status": "failed", "sources": [], "counts": {},
                    "text": "Choose at least one configured brand to refresh."}
        brands = list(dict.fromkeys(names[brand.strip().casefold()] for brand in brands))
    if keys is None:
        keys = [s["key"] for s in available_sources(conn) if s["enabled"] and s["configured"]]
    if not keys:
        return {"status": "failed", "sources": [], "counts": {},
                "text": "No connectors are ready. Add an API key in Settings, or enable demo data."}
    scope = {**settings["collection"], "home_zip": settings["home_zip"],
             "other_max_price": settings["filters"].get("max_price") or settings["collection"]["max_price"]}
    if brands is not None:
        scope["brands"] = brands
    try:
        refresh_scopes = collection_scopes(scope, "autodev")
        if scope.get("searches") is not None:
            for key in keys:
                if key not in API_SOURCES:
                    continue
                for query in collection_scopes(scope, key):
                    radius = query["distance"] if key == "autodev" else query["marketcheck_radius"]
                    if radius > 0 and not zip_latlon(query["zip"]):
                        return {"status": "failed", "sources": [], "counts": {},
                                "text": "Enter a valid Home ZIP in Settings before running a radius search "
                                        f"with {key}. Choose nationwide (radius 0) if your API plan supports it."}
    except (TypeError, ValueError) as e:
        return {"status": "failed", "sources": [], "counts": {}, "text": str(e)}
    refresh_brands = sorted({names.get(make.casefold(), make) for query in refresh_scopes
                             for make in query["make"].split(",")})
    refresh_rivian = any(query["make"].casefold() == "rivian" and query["model"].casefold() == "r1t"
                         for query in refresh_scopes)
    adapters = [make_adapter(conn, k) for k in keys]
    backup.daily_backup(conn)
    do_enrich = settings["collection"].get("vpic_enrichment", True)
    def _enrich(c):
        out = {"photos": photos.cache_missing(c, brands=refresh_brands)}
        if refresh_rivian:
            out["recalls"] = recalls.refresh(c)
        if do_enrich:
            out["vpic"] = enrich.enrich_vehicles(c, brands=refresh_brands)
        if refresh_rivian and "marketcheck" in keys and settings["collection"].get("mc_second_opinion", True):
            spent = sum(a.calls for a in adapters if a.key == "marketcheck")
            remaining = max(0, int(settings["collection"].get("max_pages_per_run", 40)) - spent)
            out["battery_second_opinion"] = enrich.auto_second_opinions(c, settings, max_calls=remaining)
        return out

    summary = pipeline.run_search(conn, adapters, scope, enrich=_enrich)
    inv = queries.inventory_frame(conn, settings)
    matching = len(queries.apply_filters(inv, settings["filters"])) if not inv.empty else 0
    summary["matching"] = matching
    summary["brands"] = refresh_brands
    summary["text"] = queries.summary_text(summary, matching)
    return summary


def verify_missing_with_autodev(conn: sqlite3.Connection, limit: int = 10) -> dict:
    """Spend up to `limit` Auto.dev calls checking whether 'missing' VINs are reported removed."""
    adapter = make_adapter(conn, "autodev")
    ok, why = adapter.is_configured()
    if not ok:
        return {"checked": 0, "error": why}
    rows = conn.execute(
        "SELECT l.id, v.vin FROM listings l JOIN vehicles v ON v.id=l.vehicle_id WHERE l.status='missing'"
        " AND l.source_key='autodev' AND v.vin IS NOT NULL ORDER BY l.missing_since LIMIT ?", (limit,)).fetchall()
    run_id = pipeline.start_run(conn, "verify_missing", ["autodev"])
    checked, removed, back = 0, 0, 0
    with conn:
        ing = pipeline.Ingestor(conn, run_id)
        for r in rows:
            nl = adapter.lookup_vin(r["vin"])
            checked += 1
            if nl is None:
                continue
            out = ing.ingest(nl)
            removed += "provider_removed" in out.events
            back += "returned" in out.events
    pipeline.finish_run(conn, run_id, [{"source": "autodev", "name": "Auto.dev VIN check", "status": "success",
                                        "complete": False, "listings_seen": checked, "api_calls": adapter.calls,
                                        "disappeared": 0, "error": None, "notes": []}])
    return {"checked": checked, "removed": removed, "returned": back, "api_calls": adapter.calls}


def purge_demo(conn: sqlite3.Connection) -> int:
    """Delete all synthetic demo records."""
    ids = [r[0] for r in conn.execute("SELECT id FROM vehicles WHERE is_demo=1")]
    if not ids:
        return 0
    marks = ",".join("?" * len(ids))
    with conn:
        conn.execute(f"DELETE FROM change_events WHERE vehicle_id IN ({marks})", ids)  # noqa: S608
        conn.execute(f"DELETE FROM listings WHERE vehicle_id IN ({marks})", ids)  # noqa: S608
        conn.execute(f"DELETE FROM vehicle_attributes WHERE vehicle_id IN ({marks})", ids)  # noqa: S608
        conn.execute(f"DELETE FROM user_overrides WHERE vehicle_id IN ({marks})", ids)  # noqa: S608
        conn.execute(f"DELETE FROM watchlist WHERE vehicle_id IN ({marks})", ids)  # noqa: S608
        conn.execute(f"DELETE FROM match_candidates WHERE vehicle_id IN ({marks}) OR candidate_vehicle_id IN ({marks})", ids + ids)  # noqa: S608
        conn.execute(f"UPDATE vehicles SET merged_into_id=NULL WHERE merged_into_id IN ({marks})", ids)  # noqa: S608
        conn.execute(f"DELETE FROM vehicles WHERE id IN ({marks})", ids)  # noqa: S608
        conn.execute("DELETE FROM preferences WHERE key='demo_run_index'")
        conn.execute("DELETE FROM source_runs WHERE source_key='demo'")
        conn.execute("UPDATE sources SET last_attempt_at=NULL, last_success_at=NULL, last_status=NULL, last_error=NULL"
                     " WHERE key='demo'")
    return len(ids)


def toggle_favorite(conn: sqlite3.Connection, vehicle_id: int, on: bool) -> None:
    with conn:
        if on:
            conn.execute("INSERT OR IGNORE INTO watchlist(vehicle_id, added_at) VALUES (?, datetime('now'))", (vehicle_id,))
        else:
            conn.execute("DELETE FROM watchlist WHERE vehicle_id=?", (vehicle_id,))


def add_listing_link(conn: sqlite3.Connection, vehicle_id: int, url: str, price: int | None = None,
                     miles: int | None = None, seller_name: str | None = None) -> dict:
    """Attach another URL for this truck (typically the seller's own page found from an aggregator listing).
    The URL is stored as a link only; nothing is fetched."""
    url = url.strip()
    if not url.lower().startswith(("http://", "https://")):
        raise ValueError("Enter a full URL starting with http:// or https://")
    v = conn.execute("SELECT * FROM vehicles WHERE id=?", (vehicle_id,)).fetchone()
    site, site_id = identify_site(url)
    nl = NormalizedListing(source_key=site, import_method="manual", source_listing_id=site_id, url=url, vin=v["vin"],
                           year=v["year"], make=v["make"] or "Rivian", model=v["model"] or "R1T", price=price,
                           miles=miles, seller_name=seller_name or None,
                           seller_type="dealer" if site == "dealer" else None)
    run_id = pipeline.start_run(conn, "manual_entry", [site])
    with conn:
        out = pipeline.Ingestor(conn, run_id).ingest(nl, vehicle_id=vehicle_id)
    pipeline.finish_run(conn, run_id, [{"source": "manual_entry", "name": "Seller link", "status": "success",
                                        "complete": False, "listings_seen": 1, "api_calls": 0, "disappeared": 0,
                                        "error": None, "notes": ["User-added link"]}])
    return {"listing_id": out.listing_id, "vehicle_id": out.vehicle_id, "created": out.created_listing}


def set_seller_link(conn: sqlite3.Connection, vehicle_id: int, listing_id: int | None, new_url: str) -> str:
    """Correct or remove a truck's seller link ('' removes it). A link you added yourself is fixed in place; a
    provider's link is overridden for this truck, so the next search can't put the wrong one back."""
    from .extract import canonical_url
    new_url = (new_url or "").strip()
    if new_url and not new_url.lower().startswith(("http://", "https://")):
        raise ValueError("Enter a full link starting with http:// or https://")
    row = conn.execute("SELECT * FROM listings WHERE id=? AND vehicle_id=?", (listing_id, vehicle_id)).fetchone() \
        if listing_id else None
    if row is not None and row["import_method"] != "api":          # yours: fix the listing itself
        if new_url:
            canon = canonical_url(new_url)
            clash = conn.execute("SELECT vehicle_id FROM listings WHERE url_canonical=? AND id!=?", (canon, listing_id)).fetchone()
            if clash and clash[0] != vehicle_id:
                raise ValueError("That link already belongs to a different truck in your data.")
            site, site_id = identify_site(new_url)
            try:
                with conn:
                    conn.execute("UPDATE listings SET url=?, url_canonical=?, source_key=?, source_listing_id=? WHERE id=?",
                                 (new_url, canon, site, site_id, listing_id))
            except sqlite3.IntegrityError:
                raise ValueError("That listing is already recorded for this truck — remove this link instead.") from None
        else:
            others = conn.execute("SELECT COUNT(*) FROM listings WHERE vehicle_id=? AND id!=?",
                                  (vehicle_id, listing_id)).fetchone()[0]
            if not others:
                raise ValueError("This is the truck's only listing — hide the truck instead (🚫 Not interested).")
            from .repairs import delete_listing
            with conn:
                delete_listing(conn, listing_id)
        attributes.set_override(conn, vehicle_id, "seller_url", None, "")
        return "fixed" if new_url else "removed"
    attributes.set_override(conn, vehicle_id, "seller_url", new_url or "none", "You corrected the seller link")
    return "overridden" if new_url else "hidden"


def lookup_vin(conn: sqlite3.Connection, vin: str) -> dict:
    """Ask Auto.dev for one VIN (1 API call) and add it if found."""
    adapter = make_adapter(conn, "autodev")
    ok, why = adapter.is_configured()
    if not ok:
        return {"found": False, "error": why}
    try:
        nl = adapter.lookup_vin(vin)
    except Exception as e:  # SourceError / network
        return {"found": False, "error": str(e)}
    if nl is None:
        return {"found": False}
    pipeline.import_listings(conn, [nl], "vin_lookup")
    return {"found": True, "title": nl.title or vin}
