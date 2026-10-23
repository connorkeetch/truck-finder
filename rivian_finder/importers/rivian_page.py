"""Rivian Pre-Owned listing pages pasted by the user (Ctrl+A, Ctrl+C on the page) — nothing is fetched.

Rivian's own page is the best source there is for a truck: the build sheet (battery, motor, colors, wheels,
options), the price, and the VIN-specific warranty dates. Battery, motor, powered tonneau and warranty are saved as
your verified values; the rest as high-confidence claims from Rivian.
"""
from __future__ import annotations

import re
import sqlite3

from .. import attributes, pipeline
from ..extract import parse_int, parse_warranty
from ..models import AttributeClaim, NormalizedListing
from ..vin import clean_vin

LABELS = ["Year", "Generation", "Condition", "VIN", "Mileage", "Trim", "Build", "Motor", "Battery", "Exterior",
          "Wheels", "Interior", "Accents & Badging", "Utility", "Audio", "Roof", "Wraps", "Accessories", "Tonneau",
          "Total"]
MOTORS = [("performance dual", "Performance Dual"), ("quad", "Quad"), ("tri", "Tri"), ("dual", "Dual")]
BATTERIES = {"max": "Max", "large+": "Large+", "large plus": "Large+", "large": "Large", "standard+": "Standard+",
             "standard plus": "Standard+", "standard": "Standard"}
METHOD = "Rivian Pre-Owned listing (pasted)"
NOTE = "From Rivian's Pre-Owned listing page"


def looks_like(text: str | None) -> bool:
    t = text or ""
    return bool(re.search(r"^VIN\s*$", t, re.M) and re.search(r"^Build\s*$", t, re.M)
                and re.search(r"Battery pack & drivetrain|Pre-owned inspection|Pickup in .+ in \d", t))


def split_pages(text: str) -> list[str]:
    """Several pages pasted together → one text per page (each starts with 'R1T …' then a mileage line)."""
    lines = (text or "").splitlines()
    starts = []
    for i, line in enumerate(lines):
        if re.match(r"^\s*R1[TS]\b", line):
            nxt = next((ln.strip() for ln in lines[i + 1:] if ln.strip()), "")
            if re.match(r"^[\d,]+\s*mi$", nxt):
                starts.append(i)
    if len(starts) <= 1:
        return [text] if looks_like(text) else []
    bounds = starts + [len(lines)]
    pages = ["\n".join(lines[a:b]) for a, b in zip(bounds, bounds[1:])]
    return [p for p in pages if looks_like(p)]


def _sections(text: str) -> dict[str, list[str]]:
    """{label: [value lines]} from the label/value list on the page."""
    out: dict[str, list[str]] = {}
    current = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line in LABELS:
            current = line
            out.setdefault(current, [])
            continue
        if current:
            out[current].append(line)
            if current == "Total":          # the price; everything after it is payment / warranty text
                current = None
    return out


def parse(text: str) -> dict:
    s = _sections(text)
    first = lambda k: (s.get(k) or [""])[0]  # noqa: E731
    motor_text = first("Motor").lower()
    motor = next((m for key, m in MOTORS if key in motor_text), None)
    battery = BATTERIES.get(first("Battery").strip().lower())
    pickup = re.search(r"Pickup in (.+?),\s*([A-Z]{2})\b", text)
    rng = re.search(r"^(\d{3})\s*mi range", text, re.M)
    title = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    options = []
    for k in ("Accents & Badging", "Utility", "Audio", "Roof", "Wraps", "Accessories", "Tonneau"):
        options += s.get(k, [])
    return {
        "title": title, "vin": clean_vin(first("VIN")), "year": parse_int(first("Year")),
        "generation": first("Generation") or None, "trim": first("Trim") or None, "build": first("Build") or None,
        "miles": parse_int(first("Mileage")), "motor": motor, "battery": battery,
        "exterior_color": first("Exterior") or None, "interior_color": first("Interior") or None,
        "wheels": first("Wheels") or None, "options": options,
        "tonneau": "yes" if any("powered tonneau" in o.lower() for o in s.get("Tonneau", [])) else "no",
        "price": parse_int(first("Total")), "epa_range": int(rng.group(1)) if rng else None,
        "city": pickup.group(1).strip() if pickup else None, "state": pickup.group(2) if pickup else None,
        "warranty": parse_warranty(text),
    }


def apply(conn: sqlite3.Connection, text: str, url: str | None = None) -> dict:
    """Add or update the truck from one pasted Rivian page. Returns what happened."""
    p = parse(text)
    if not p["vin"] or len(p["vin"]) != 17:
        raise ValueError("Couldn't find a VIN on that page — copy the whole Rivian listing page.")
    row = conn.execute("SELECT id FROM vehicles WHERE vin=? AND merged_into_id IS NULL", (p["vin"],)).fetchone()
    existed = row is not None
    if url is None and row:          # reuse the Rivian page link we already have for this truck, if any
        hit = conn.execute("SELECT url FROM listings WHERE vehicle_id=? AND url LIKE '%rivian.com%' ORDER BY id",
                           (row[0],)).fetchone()
        url = hit[0] if hit else None
    claims = [AttributeClaim(f, str(v), "high", METHOD, source="rivian", evidence=f"Rivian page: {v}")
              for f, v in (("exterior_color", p["exterior_color"]), ("interior_color", p["interior_color"]),
                           ("wheels", p["wheels"]), ("epa_range", p["epa_range"]), ("trim", p["trim"])) if v]
    city = p["city"]
    desc = "; ".join(x for x in [
        f"{p['build']} · {p['battery']} pack" if p["build"] else "",
        f"Options: {', '.join(p['options'])}" if p["options"] else "",
        f"Pickup in {city}, {p['state']}" if city else "",
        "Rivian Pre-Owned: 137-point inspection, 7-day returns"] if x)
    nl = NormalizedListing(
        source_key="rivian", import_method="paste", source_listing_id=None if url else f"po:{p['vin']}", url=url,
        vin=p["vin"], year=p["year"], make="Rivian", model="R1T", trim=p["trim"], price=p["price"], miles=p["miles"],
        seller_name=f"Rivian {city} (Pre-Owned)" if city else "Rivian Pre-Owned", seller_type="manufacturer",
        city=city, state=p["state"], exterior_color=p["exterior_color"], interior_color=p["interior_color"],
        title=f"{p['year']} {p['title']}".strip(), description=desc, attributes=claims)
    summary = pipeline.import_listings(conn, [nl], "rivian_page")
    vid = conn.execute("SELECT id FROM vehicles WHERE vin=?", (p["vin"],)).fetchone()[0]
    verified = {"battery": p["battery"], "motor": p["motor"], "tonneau": p["tonneau"]}
    verified.update({k: str(v) for k, v in p["warranty"].items()})
    for field, value in verified.items():
        if value:
            attributes.set_override(conn, vid, field, value, NOTE)
    return {"vehicle_id": vid, "vin": p["vin"], "added": not existed, "counts": summary["counts"], "parsed": p}
