"""VIN enrichment via NHTSA vPIC (free, no key): https://vpic.nhtsa.dot.gov/api/

vPIC reports Rivian's drive-unit count (Dual/Triple/Quad Motor) from manufacturer-submitted VIN data. It does
not report battery pack size or whether a dual-motor truck has the Performance upgrade, so those stay with
listing claims or the user's verification.
"""
from __future__ import annotations

import logging
import sqlite3
from urllib.parse import urlencode

import requests

from .attributes import record_claims
from .db import utcnow
from .models import AttributeClaim

log = logging.getLogger(__name__)
VPIC_BATCH_URL = "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVINValuesBatch/"
MOTOR_MAP = {"quad motor": "Quad", "triple motor": "Tri", "tri motor": "Tri", "dual motor": "Dual"}


def decode_batch(vins: list[str], session: requests.Session | None = None, timeout: int = 60) -> dict[str, dict]:
    if not vins:
        return {}
    session = session or requests.Session()
    data = ";".join(vins[:50])
    resp = session.post(VPIC_BATCH_URL, data=urlencode({"format": "json", "data": data}),
                        headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=timeout)
    resp.raise_for_status()
    return {r.get("VIN", "").upper(): r for r in resp.json().get("Results", [])}


def claims_from_vpic(result: dict) -> list[AttributeClaim]:
    claims: list[AttributeClaim] = []
    method = "NHTSA vPIC VIN decode (manufacturer-submitted)"
    drive = (result.get("EVDriveUnit") or "").strip().lower()
    if drive in MOTOR_MAP:
        claims.append(AttributeClaim("motor", MOTOR_MAP[drive], "high", method, source="nhtsa_vpic",
                                     evidence=f"EVDriveUnit = {result.get('EVDriveUnit')}"))
    if result.get("Trim"):
        claims.append(AttributeClaim("vpic_trim", result["Trim"], "medium", method, source="nhtsa_vpic",
                                     evidence=f"Trim = {result['Trim']}"))
    if result.get("ModelYear"):
        claims.append(AttributeClaim("model_year", str(result["ModelYear"]), "high", method, source="nhtsa_vpic"))
    if result.get("PlantCity"):
        claims.append(AttributeClaim("plant", f"{result['PlantCity']}, {result.get('PlantState', '')}".strip(", "),
                                     "high", method, source="nhtsa_vpic"))
    claims.append(AttributeClaim("vpic_decoded", utcnow()[:10], "high", method, source="nhtsa_vpic",
                                 evidence=f"ErrorCode {result.get('ErrorCode', '')}"))
    return claims


def enrich_vehicles(conn: sqlite3.Connection, limit: int = 50, session: requests.Session | None = None,
                    brands: list[str] | None = None) -> dict:
    """Decode VINs that have not been decoded yet. Network failures are reported, never raised."""
    if brands is not None and not brands:
        return {"decoded": 0}
    brand_sql = " AND LOWER(make) IN (%s)" % ",".join("?" * len(brands)) if brands is not None else ""
    params = [brand.lower() for brand in brands] if brands is not None else []
    rows = conn.execute(
        "SELECT id, vin FROM vehicles v WHERE vin IS NOT NULL AND merged_into_id IS NULL AND is_demo = 0"
        " AND NOT EXISTS (SELECT 1 FROM vehicle_attributes a WHERE a.vehicle_id=v.id AND a.field='vpic_decoded')"
        + brand_sql + " LIMIT ?", (*params, limit)).fetchall()
    if not rows:
        return {"decoded": 0}
    try:
        results = decode_batch([r["vin"] for r in rows], session=session)
    except (requests.RequestException, ValueError) as e:
        return {"decoded": 0, "error": f"vPIC unavailable: {type(e).__name__}"}
    n = 0
    with conn:
        for r in rows:
            res = results.get(r["vin"])
            if res:
                record_claims(conn, r["id"], claims_from_vpic(res))
                n += 1
    return {"decoded": n}


# ---------------------------------------------------------------- MarketCheck second opinion on battery/motor
MC_METHOD = "MarketCheck VIN decode (built from listing data, not factory build records)"


def claims_from_mc_decode(d: dict, year: int | None, motor: str | None,
                          make: str = "Rivian", model: str = "R1T") -> list[AttributeClaim]:
    """Battery/motor from the decoder's 'version' text; EPA range; and the pack implied by that EPA range."""
    from . import epa
    from .extract import extract_attributes, structured_truck_specs
    claims: list[AttributeClaim] = []
    for claim in structured_truck_specs(d, MC_METHOD):
        claim.source = "marketcheck_decode"
        claims.append(claim)
    for group in (d.get("installed_equipment") or {}).values():
        for equipment in group:
            label = str(equipment.get("attribute") or "")
            value = str(equipment.get("value") or "")
            extracted = structured_truck_specs({label: value}, MC_METHOD)
            extracted += extract_attributes(f"{label}: {value}", MC_METHOD, confidence="medium", make=make, model=model)
            for claim in extracted:
                if claim.field in ("epa_range", "tow_capacity_lbs"):
                    claim.source = "marketcheck_decode"
                    claims.append(claim)
    version = d.get("version") or ""
    for c in extract_attributes(version, MC_METHOD, confidence="medium", make=make, model=model):
        if c.field in ("battery", "motor", "tow_capacity_lbs"):
            c.source, c.evidence = "marketcheck_decode", f"version = {version}"
            claims.append(c)
    rng = d.get("electric_range")
    if isinstance(rng, (int, float)) and rng > 0:
        claims.append(AttributeClaim("epa_range", str(int(rng)), "medium", MC_METHOD, source="marketcheck_decode",
                                     evidence=f"electric_range = {int(rng)}"))
        if make.lower() == "rivian" and model.upper() == "R1T" and year and not any(c.field == "battery" for c in claims):
            packs = epa.batteries_for_range(year, motor, int(rng))
            if len(packs) == 1:
                claims.append(AttributeClaim("battery", packs.pop(), "low",
                                             f"Only pack with a {int(rng)}-mile EPA rating for this year/motor",
                                             source="epa_match", evidence=f"electric_range = {int(rng)}"))
    claims.append(AttributeClaim("mc_decoded", utcnow()[:10], "high", MC_METHOD, source="marketcheck_decode",
                                 evidence=str(d.get("record_source") or "")))
    return claims


def mc_second_opinion(conn: sqlite3.Connection, vehicle_id: int, api_key: str | None = None,
                      session: requests.Session | None = None, max_calls: int | None = None) -> dict:
    """One MarketCheck call: decode the VIN and record its battery/motor/EPA claims next to the listing's."""
    from . import credentials
    from .sources.marketcheck import BASE_URL, MarketCheckAdapter
    v = conn.execute("SELECT vin, year, make, model FROM vehicles WHERE id=?", (vehicle_id,)).fetchone()
    if not v or not v["vin"]:
        return {"ok": False, "error": "no validated VIN"}
    key = api_key or credentials.get_api_key("marketcheck")[0]
    if not key:
        return {"ok": False, "error": "no MarketCheck API key"}
    adapter = MarketCheckAdapter(key, session=session, conn=conn)
    if max_calls is not None:
        adapter.set_call_limit(max_calls)
    try:
        d = adapter.get_json(f"{BASE_URL}/v2/decode/car/neovin/{v['vin']}/specs", params={"api_key": key})
    except Exception as e:  # SourceError / network — reported, not raised
        return {"ok": False, "error": str(e), "api_calls": adapter.calls}
    motor_row = conn.execute("SELECT value FROM vehicle_attributes WHERE vehicle_id=? AND field='motor'"
                             " ORDER BY confidence='high' DESC LIMIT 1", (vehicle_id,)).fetchone()
    claims = claims_from_mc_decode(d, v["year"], motor_row[0] if motor_row else None,
                                   v["make"] or "Rivian", v["model"] or "R1T")
    with conn:
        record_claims(conn, vehicle_id, claims)
    return {"ok": True, "version": d.get("version"), "epa_range": d.get("electric_range"), "api_calls": adapter.calls,
            "claims": [(c.field, c.value) for c in claims if c.field != "mc_decoded"]}


def auto_second_opinions(conn: sqlite3.Connection, settings: dict, limit: int = 15,
                         max_calls: int | None = None) -> dict:
    """For matching trucks whose battery is unknown or disputed, ask MarketCheck once per VIN (budget permitting)."""
    from . import credentials, queries
    if not credentials.get_api_key("marketcheck")[0]:
        return {"checked": 0, "skipped": "no MarketCheck key"}
    b = queries.api_budget(conn, "marketcheck", 500)
    reserve = (b["per_run"] or 2) * 10            # keep enough calls for the regular searches
    allowed = max(min(limit, b["left"] - reserve), 0)
    if max_calls is not None:
        allowed = min(allowed, max_calls)
    if not allowed:
        return {"checked": 0, "skipped": "saving MarketCheck calls for searches"}
    inv = queries.inventory_frame(conn, settings)
    if inv.empty:
        return {"checked": 0}
    pool = queries.apply_filters(inv, {**settings["filters"], "near_misses": True})
    decoded = {r[0] for r in conn.execute("SELECT vehicle_id FROM vehicle_attributes WHERE field='mc_decoded'")}
    unsure = pool[(pool["vin"] != "") & ~pool["is_demo"] & ~pool["vehicle_id"].isin(decoded)
                  & pool["make"].str.lower().eq("rivian") & pool["model"].str.upper().eq("R1T")
                  & ((pool["battery"] == "Unknown") | pool["conflicts"].str.contains("battery", regex=False))]
    done, calls = 0, 0
    for vid in unsure["vehicle_id"].head(allowed):
        remaining = allowed - calls
        if remaining <= 0:
            break
        result = mc_second_opinion(conn, int(vid), max_calls=remaining)
        calls += result.get("api_calls", 1)
        if result.get("ok"):
            done += 1
    return {"checked": done, "waiting": max(len(unsure) - done, 0), "api_calls": calls}
